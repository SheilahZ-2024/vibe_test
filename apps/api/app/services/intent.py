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
    "QueryReservation": "查询预约是否成功、如何预约/预约方式",
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
    turn_mode: str = "full"  # full | continuation | acknowledgment | topic_shift

    def to_pipeline_detail(self) -> str:
        flag = "需澄清" if self.needs_clarify else "已路由"
        turn = f", {self.turn_mode}" if self.turn_mode != "full" else ""
        return (
            f"[{self.route_category}] {self.route_intent} ({self.confidence:.0%}, {self.source}{turn}, {flag})"
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
    ("CheckVoucherAvailability", ("没预约", "能否核销", "能不能核销", "能核销吗", "可以核销", "没约能", "未预约"), 0.86),
    ("QueryReservation", ("预约状态", "约了吗", "怎么预约", "如何预约", "预约方式", "在哪约", "怎么约", "去哪约"), 0.82),
    ("CheckReservationEligibility", ("能不能约", "可以预约吗", "需要预约吗", "要不要预约"), 0.8),
    ("QueryRefund", ("退款进度", "退到哪", "什么时候退", "退款失败"), 0.82),
    ("QueryOrder", ("订单", "团购", "付款成功", "买的", "付了钱", "看看订单", "我的团购"), 0.8),
    ("HumanTransfer", ("人工", "投诉", "客服", "真人"), 0.9),
    ("chitchat", ("你好", "谢谢", "在吗", "哈哈", "早上好"), 0.75),
]

_ACK_WORDS = ("谢谢", "感谢", "多谢", "好的", "好哒", "明白", "知道了", "收到", "嗯嗯", "没问题", "OK", "ok")
_CONT_PREFIX = ("那", "然后", "还有", "另外", "刚才", "这个", "再问", "顺便")
_CONT_SUFFIX = ("呢", "吗")
_TOPIC_SHIFT = ("换个话题", "另外一笔", "别的订单", "不聊这个", "重新来", "新问题")
_CONT_BLOCK = ("预约", "核销", "退款", "订单", "券", "投诉", "人工")


def _has_assistant_turn(history: list[dict]) -> bool:
    return any(m.get("role") == "assistant" for m in history[-8:])


def _keyword_turn_mode(message: str, history: list[dict], agent_ctx: dict | None) -> str | None:
    """有会话记忆时的接话/致谢判定（关键词层，偏保守，避免把新问题误判为接话）。"""
    if not history or not _has_assistant_turn(history) or not agent_ctx:
        return None
    text = message.strip()
    if not text:
        return None
    if any(k in text for k in _TOPIC_SHIFT):
        return "topic_shift"
    if len(text) <= 16 and any(k in text for k in _ACK_WORDS):
        return "acknowledgment"
    # 接话：明显承接词开头，或极短省略追问（电话呢/退款呢）
    if len(text) <= 32 and any(text.startswith(p) for p in _CONT_PREFIX):
        return "continuation"
    if len(text) <= 6 and text.endswith(_CONT_SUFFIX):
        if len(text) > 4 and any(k in text for k in _CONT_BLOCK):
            return None
        return "continuation"
    return None


def _prior_intent_inheritable(agent_ctx: dict) -> bool:
    prior = str(agent_ctx.get("intent") or "").strip()
    return prior not in ("", "clarify", "chitchat", "unconfigured")


def _apply_continuation_intent(kw: IntentResult, agent_ctx: dict) -> IntentResult:
    """接话轮次：在关键词已命中 intent 时，仍继承上一轮 route intent 供 ReAct 复用上下文。"""
    if not _prior_intent_inheritable(agent_ctx):
        return kw
    kw.turn_mode = "continuation"
    kw.route_intent = str(agent_ctx["intent"])
    kw.raw_intent = kw.route_intent
    kw.route_category = str(agent_ctx.get("route_category") or kw.route_category)
    kw.reasoning = (kw.reasoning or "") + "；接上一轮继续聊"
    kw.needs_clarify = False
    return kw


def _intent_from_context(agent_ctx: dict, *, acknowledgment: bool = False) -> tuple[str, str, str]:
    intent = str(agent_ctx.get("intent") or "clarify")
    category = str(agent_ctx.get("route_category") or "configured")
    if acknowledgment:
        return "chitchat", "chitchat", "chitchat"
    return intent, intent, category


def _result_from_turn_hint(
    turn_mode: str,
    message: str,
    agent_ctx: dict,
) -> IntentResult:
    raw, route, category = _intent_from_context(agent_ctx, acknowledgment=(turn_mode == "acknowledgment"))
    reasoning = "用户致谢或确认，承接上一句即可" if turn_mode == "acknowledgment" else "用户在追问上一话题，优先复用已查事实"
    return IntentResult(
        raw_intent=raw,
        route_intent=route,
        confidence=0.9,
        reasoning=reasoning,
        source="turn_hint",
        needs_clarify=False,
        alternatives=[],
        route_category=category,
        turn_mode=turn_mode,
    )


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

    async def classify(
        self,
        message: str,
        history: list[dict] | None = None,
        agent_ctx: dict | None = None,
    ) -> IntentResult:
        """关键词 + 会话接话判定；模糊表达才调轻量 LLM。"""
        history = history or []
        threshold = settings.intent_confidence_threshold

        turn_hint = _keyword_turn_mode(message, history, agent_ctx)
        if turn_hint == "acknowledgment" and agent_ctx:
            return _result_from_turn_hint(turn_hint, message, agent_ctx)

        kw = _keyword_classify(message)
        if (
            history
            and agent_ctx
            and len(message.strip()) <= 16
            and (kw.raw_intent == "chitchat" or any(k in message for k in _ACK_WORDS))
        ):
            return _result_from_turn_hint("acknowledgment", message, agent_ctx)

        if kw.route_intent != "clarify" and kw.confidence >= threshold:
            if history and agent_ctx and turn_hint == "continuation":
                kw = _apply_continuation_intent(kw, agent_ctx)
            return kw

        if turn_hint == "continuation" and agent_ctx and _prior_intent_inheritable(agent_ctx):
            return _result_from_turn_hint("continuation", message, agent_ctx)

        if settings.intent_use_llm and not self.llm.use_mock:
            llm_result = await self._classify_with_llm(message, history, agent_ctx)
            if llm_result:
                return llm_result
        return kw

    async def _classify_with_llm(
        self,
        message: str,
        history: list[dict],
        agent_ctx: dict | None = None,
    ) -> IntentResult | None:
        recent = "\n".join(f"{m['role']}: {m['content'][:120]}" for m in history[-6:]) or "无"
        memory_hint = ""
        if agent_ctx:
            memory_hint = (
                f"\n上一轮意图：{agent_ctx.get('intent') or '?'}\n"
                f"已查事实摘要：{(agent_ctx.get('digest') or '无')[:240]}"
            )

        system = f"""你是抖音生活服务 SDS v1 意图分类器。理解口语、省略、指代（「那」「这个」）、口水话，结合对话判断本轮怎么处理。

已配置 Intent 列表（route_category=configured 时从中选择 intent）：
{chr(10).join(f"- {k}: {v}" for k, v in INTENT_CATALOG.items() if k not in ("chitchat", "clarify", "unconfigured"))}

route_category 三类（必填）：
- configured：能映射到上述某一 Intent
- chitchat：寒暄、与履约无关
- unconfigured：明确是履约/生活诉求，但不在已配置 Intent 中

turn_mode（必填，判断是否为「冷启动」）：
- full：新话题/换订单/与上一轮无关；或**首轮**涉及资格判断（如没预约能核销吗、能不能退款）
- continuation：明确承接上一轮，只补充细节或程序性追问（那电话呢、那怎么预约、门店地址呢）
- acknowledgment：致谢、好的、明白了等短接话
- topic_shift：明确换话题或换订单

规则：
1. 有对话历史时，短句「谢谢/好的/明白了」→ acknowledgment + chitchat
2. 同话题省略/程序性追问：「那退款呢」「那怎么预约」「电话多少」「门店呢」→ continuation，intent **延续上一轮**（不要 unconfigured）
3. 规则 2 优先于「含怎么/如何」：同话题下的「怎么/如何 + 预约/电话/地址/退款」仍是 continuation，不是 full
4. **无历史或明显换话题**时，含「没预约/能不能核销/为什么用不了」等资格判断 → full
5. 明显全新履约问题 → full
6. confidence 0~1；alternatives 给 1-2 个次选

只输出 JSON：
{{"route_category":"...", "intent":"...", "confidence":0.0, "turn_mode":"full|continuation|acknowledgment|topic_shift", "reasoning":"...", "alternatives":[{{"intent":"...", "confidence":0.0}}]}}"""

        raw = await self.llm.complete(
            system,
            f"最近对话：\n{recent}{memory_hint}\n\n用户最新：{message}",
            temperature=settings.intent_llm_temperature,
            max_tokens=settings.intent_llm_max_tokens,
        )
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
        turn_mode = str(data.get("turn_mode") or "full").strip()
        if turn_mode not in ("full", "continuation", "acknowledgment", "topic_shift"):
            turn_mode = "full"
        if not history and turn_mode != "full":
            turn_mode = "full"
        if turn_mode == "topic_shift":
            turn_mode = "full"
        if turn_mode == "acknowledgment":
            route_category = "chitchat"
            raw_intent = "chitchat"
        elif turn_mode == "continuation" and agent_ctx and agent_ctx.get("intent"):
            raw_intent = str(agent_ctx["intent"])
            route_category = str(agent_ctx.get("route_category") or route_category)

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
        result.turn_mode = turn_mode
        if route_category == "unconfigured":
            result.route_category = "unconfigured"
            result.route_intent = "unconfigured"
            result.needs_clarify = True
        elif route_category == "chitchat":
            result.route_category = "chitchat"
        else:
            result.route_category = "configured"
        return result
