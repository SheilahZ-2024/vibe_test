"""意图识别：SDS v1 Intent Space + 轻量 LLM + 置信度阈值。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.config import settings
from app.services.llm import LLMService

# SDS v1 可进入诊断引擎的意图
ACTIONABLE_INTENTS = frozenset(
    {
        "QueryOrder",
        "QueryVoucher",
        "QueryCoupon",
        "QueryStore",
        "QueryReservation",
        "QueryRefund",
        "QueryTicket",
        "CheckVoucherAvailability",
        "CheckRefundEligibility",
        "CheckReservationEligibility",
        "VoucherUnavailable",
        "ReservationFailure",
        "MerchantReject",
        "StoreUnavailable",
        "ServiceMismatch",
        "RefundRequest",
        "CompensationRequest",
        "AppealRequest",
        "MerchantComplaint",
        "ServiceComplaint",
        "SafetyComplaint",
        "PriceDispute",
        "HumanTransfer",
    }
)

INTENT_CATALOG: dict[str, str] = {
    "QueryOrder": "查询订单状态、支付是否成功、订单详情",
    "QueryVoucher": "查询团购券/券码/有效期/怎么用",
    "QueryCoupon": "查询平台优惠券状态与规则",
    "QueryStore": "查询门店地址、营业时间、电话",
    "QueryReservation": "查询预约是否成功",
    "QueryRefund": "查询退款/售后进度",
    "QueryTicket": "查询工单进度",
    "CheckVoucherAvailability": "判断券能不能用、资格校验",
    "CheckRefundEligibility": "判断能不能退款",
    "CheckReservationEligibility": "判断能不能预约",
    "VoucherUnavailable": "券用不了、核销失败、扫不出来、老板不给用（口语化履约受阻）",
    "ReservationFailure": "预约失败、约不上",
    "MerchantReject": "商家拒绝核销/接待/声称活动结束",
    "StoreUnavailable": "门店关门、暂停营业、搬迁",
    "ServiceMismatch": "套餐缩水、服务不符、强制消费、临时加价",
    "RefundRequest": "申请退款、退票、不想要了",
    "CompensationRequest": "申请补偿",
    "AppealRequest": "申诉处理结果",
    "MerchantComplaint": "投诉商家违规/虚假宣传",
    "ServiceComplaint": "投诉服务态度/质量",
    "SafetyComplaint": "食品安全、人身安全类投诉",
    "PriceDispute": "价格争议",
    "HumanTransfer": "转人工、找客服",
    "chitchat": "闲聊寒暄，与履约无关",
    "clarify": "意图模糊，需澄清",
    "unconfigured": "不在已配置履约意图范围内",
}


@dataclass
class IntentResult:
    raw_intent: str
    route_intent: str
    confidence: float
    reasoning: str
    source: str
    needs_clarify: bool
    alternatives: list[dict[str, float | str]] = field(default_factory=list)
    route_category: str = "configured"  # configured | chitchat | unconfigured

    def to_pipeline_detail(self) -> str:
        flag = "需澄清" if self.needs_clarify else "已路由"
        return (
            f"[{self.route_category}] {self.route_intent} ({self.confidence:.0%}, {self.source}, {flag})"
            f"{f' — {self.reasoning}' if self.reasoning else ''}"
        )


_KEYWORD_RULES: list[tuple[str, tuple[str, ...], float]] = [
    ("SafetyComplaint", ("食品安全", "吃坏", "中毒", "异物", "变质", "被骚扰", "被威胁", "不安全", "偷拍"), 0.95),
    ("MerchantReject", ("老板不给", "商家拒绝", "不给核销", "说不认", "活动结束", "平台券不能用", "不让核销", "不让我核销"), 0.88),
    ("VoucherUnavailable", ("核销失败", "扫不出来", "刷不出来", "券用不了", "扫不了"), 0.87),
    ("StoreUnavailable", ("关门", "没开门", "倒闭", "暂停营业", "打不通", "电话没人接"), 0.84),
    ("ServiceMismatch", ("缩水", "少给", "不一样", "缺货", "缺菜", "货不对板"), 0.86),
    ("PriceDispute", ("加价", "多收钱", "临时涨价", "乱收费"), 0.84),
    ("ReservationFailure", ("约不上", "预约失败", "没法约", "不给预约"), 0.83),
    ("RefundRequest", ("退款", "退掉", "不要了", "退票", "不去了"), 0.85),
    ("AppealRequest", ("申诉", "投诉好几次", "没人管", "不公平"), 0.83),
    ("CompensationRequest", ("补偿", "赔偿"), 0.82),
    ("MerchantComplaint", ("虚假宣传", "骗人", "举报", "黑店"), 0.84),
    ("ServiceComplaint", ("态度差", "服务差", "体验差", "凶"), 0.83),
    ("QueryCoupon", ("优惠券", "满减", "用不了券", "不能叠加"), 0.82),
    ("QueryVoucher", ("券码", "团购券", "二维码", "还能用", "看看券", "券在哪", "我的券"), 0.84),
    ("QueryStore", ("营业", "几点", "地址", "电话", "搬迁"), 0.8),
    ("QueryReservation", ("预约状态", "约了吗"), 0.78),
    ("QueryRefund", ("退款进度", "退到哪", "什么时候退", "退款失败"), 0.82),
    ("QueryOrder", ("订单", "团购", "付款成功", "买的", "付了钱", "看看订单", "我的团购"), 0.8),
    ("HumanTransfer", ("人工", "投诉", "客服", "真人"), 0.9),
    ("chitchat", ("你好", "谢谢", "在吗", "哈哈", "早上好"), 0.75),
]


def preview_intent_for_retrieval(message: str) -> str:
    """同步关键词预判，供知识库检索与意图 LLM 并行时使用。"""
    kw = _keyword_classify(message)
    if kw.route_category == "chitchat":
        return "clarify"
    return kw.route_intent


def should_prefetch_knowledge(message: str) -> bool:
    return _keyword_classify(message).route_category != "chitchat"


def _keyword_classify(message: str) -> IntentResult:
    text = message.strip()
    best_intent = "clarify"
    best_score = 0.35
    reasoning = "还需要您说具体一点，我才能确定要帮您办什么"
    alts: list[dict[str, float | str]] = []

    for intent, keywords, base in _KEYWORD_RULES:
        hits = sum(1 for k in keywords if k in text)
        if hits == 0:
            continue
        score = min(0.95, base + 0.04 * (hits - 1))
        alts.append({"intent": intent, "confidence": round(score, 2)})
        if score > best_score:
            best_score = score
            best_intent = intent
            reasoning = "从您的表述里能听出比较明确的问题方向"

    alts.sort(key=lambda x: float(x["confidence"]), reverse=True)
    return _apply_threshold(best_intent, best_score, reasoning, "keyword", alts[:3])


def _need_hint(code: str) -> str:
    desc = INTENT_CATALOG.get(code, "")
    if not desc:
        return "其他相关问题"
    return desc.split("（")[0].strip()


def _apply_threshold(
    raw_intent: str,
    confidence: float,
    reasoning: str,
    source: str,
    alternatives: list[dict[str, float | str]],
) -> IntentResult:
    threshold = settings.intent_confidence_threshold

    if raw_intent == "chitchat" and confidence >= threshold:
        return IntentResult(raw_intent, "chitchat", confidence, reasoning, source, False, alternatives, "chitchat")

    if raw_intent == "unconfigured":
        return IntentResult(raw_intent, "unconfigured", confidence, reasoning, source, True, alternatives, "unconfigured")

    if raw_intent in ACTIONABLE_INTENTS and confidence >= threshold:
        return IntentResult(raw_intent, raw_intent, confidence, reasoning, source, False, alternatives, "configured")

    alt_hint = ""
    if alternatives:
        top = alternatives[0]
        top_code = str(top.get("intent") or "")
        alt_hint = f"；也可能是{_need_hint(top_code)}"
    return IntentResult(
        raw_intent,
        "clarify",
        confidence,
        (reasoning or "置信度不足") + alt_hint,
        source,
        True,
        alternatives,
        "configured",
    )


def _parse_llm_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None


class IntentClassifier:
    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    async def classify(self, message: str, history: list[dict] | None = None) -> IntentResult:
        """关键词优先：高置信度直接路由，仅模糊表达才调用轻量 LLM。"""
        kw = _keyword_classify(message)
        threshold = settings.intent_confidence_threshold
        if kw.route_intent != "clarify" and kw.confidence >= threshold:
            return kw
        if settings.intent_use_llm and not self.llm.use_mock:
            llm_result = await self._classify_with_llm(message, history or [])
            if llm_result:
                return llm_result
        return kw

    async def _classify_with_llm(self, message: str, history: list[dict]) -> IntentResult | None:
        recent = "\n".join(f"{m['role']}: {m['content'][:120]}" for m in history[-4:]) or "无"

        system = f"""你是抖音生活服务 SDS v1 意图分类器。理解口语、省略、口水话，输出 JSON。

已配置 Intent 列表（route_category=configured 时从中选择 intent）：
{chr(10).join(f"- {k}: {v}" for k, v in INTENT_CATALOG.items() if k not in ("chitchat", "clarify", "unconfigured"))}

route_category 三类（必填）：
- configured：能映射到上述某一 Intent
- chitchat：寒暄、与履约无关
- unconfigured：明确是履约/生活诉求，但不在已配置 Intent 中

规则：
1. 「到了刷不出来」「老板不给用」→ configured + VoucherUnavailable
2. 明显闲聊 → chitchat
3. 无法判断具体 Intent 但仍属履约 → configured + clarify 且 confidence 偏低
4. confidence 0~1；alternatives 给 1-2 个次选

只输出 JSON：
{{"route_category":"configured|chitchat|unconfigured", "intent":"...", "confidence":0.0, "reasoning":"...", "alternatives":[{{"intent":"...", "confidence":0.0}}]}}"""

        raw = await self.llm.complete(system, f"最近对话：\n{recent}\n\n用户最新：{message}", temperature=settings.intent_llm_temperature, max_tokens=settings.intent_llm_max_tokens)
        if not raw:
            return None
        data = _parse_llm_json(raw)
        if not data:
            return None

        raw_intent = str(data.get("intent") or "clarify").strip()
        route_category = str(data.get("route_category") or "configured").strip()
        if route_category not in ("configured", "chitchat", "unconfigured"):
            route_category = "configured"

        if route_category == "chitchat":
            raw_intent = "chitchat"
        elif route_category == "unconfigured":
            raw_intent = "unconfigured"
        elif raw_intent not in INTENT_CATALOG or raw_intent in ("chitchat", "unconfigured"):
            raw_intent = "clarify"
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0

        reasoning = str(data.get("reasoning") or "").strip()
        alternatives: list[dict[str, float | str]] = []
        for item in data.get("alternatives") or []:
            if not isinstance(item, dict):
                continue
            alt = str(item.get("intent") or "").strip()
            if alt not in INTENT_CATALOG:
                continue
            try:
                alternatives.append({"intent": alt, "confidence": round(max(0.0, min(1.0, float(item.get("confidence", 0)))), 2)})
            except (TypeError, ValueError):
                pass

        result = _apply_threshold(raw_intent, confidence, reasoning, "llm", alternatives)
        if route_category == "unconfigured":
            result.route_category = "unconfigured"
            result.route_intent = "unconfigured"
            result.needs_clarify = True
        elif route_category == "chitchat":
            result.route_category = "chitchat"
        else:
            result.route_category = "configured"
        return result
