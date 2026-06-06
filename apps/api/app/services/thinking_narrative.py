"""用户可见思考过程 — 透传模型推理/判断/下一步，仅替换工具名与 Case 编号。"""

from __future__ import annotations

import re
from typing import Any

from app.services.intent import INTENT_CATALOG, IntentResult
from app.services.tool_payloads import (
    normalize_focus_bundle,
    order_from_payload,
    store_from_payload,
    voucher_from_payload,
)
from app.services.usage_rules import reservation_context

# 只去掉内部编号，保留语义
_STRIP_PATTERNS = [
    r"\bFC-\d+\b",
    r"\bPC-\d+\b",
    r"\bAC-\d+\b",
    r"\bIC-\d+\b",
    r"Case\s*[:：]?\s*[\w-]+",
    r"approved_case_id",
    r"safe_to_send",
]

_TOOL_PHRASES: dict[str, str] = {
    "list_orders": "列出您的全部订单",
    "query_order": "查询订单详情",
    "query_focus_bundle": "并行查询订单、券与门店",
    "query_voucher": "查询团购券状态",
    "query_store": "查询门店营业信息",
    "query_coupon": "查询优惠券",
    "query_refund": "查询退款资格与进度",
    "query_ticket": "查询工单进度",
    "search_knowledge": "检索平台政策与 FAQ",
    "run_diagnosis": "对照平台诊断规则做结构化分析",
    "regenerate_qr": "重新生成核销码",
    "contact_merchant": "联系商家协助",
    "create_reservation": "创建预约",
    "apply_refund": "提交退款申请",
    "human_handoff": "转接人工客服",
    "finish": "整理结论并回复您",
}

_INTENT_LABELS: dict[str, str] = {
    "VoucherUnavailable": "团购券核销或用不了",
    "MerchantReject": "商家拒绝核销或接待",
    "RefundRequest": "申请退款",
    "QueryVoucher": "查看团购券",
    "QueryOrder": "查看订单",
    "QueryStore": "查看门店信息",
    "QueryRefund": "了解退款进度",
    "QueryCoupon": "优惠券使用问题",
    "HumanTransfer": "转人工客服",
    "clarify": "需求尚不明确",
    "chitchat": "寒暄闲聊",
}

# 订单/券/优惠券状态 — 避免英文 status 透出
_ORDER_STATUS_ZH = {
    "unused": "未核销",
    "scheduled": "已预约",
    "used": "已核销",
    "refunding": "退款中",
    "refunded": "已退款",
    "expired": "已过期",
    "frozen": "已冻结",
    "refund_pending": "退款处理中",
}
_COUPON_STATUS_ZH = {
    "available": "可用",
    "unavailable": "不可用",
    "used": "已使用",
    "expired": "已过期",
}


def build_session_opening_lines(
    intent: IntentResult,
    message: str,
    service_context: dict,
) -> list[str]:
    lines: list[str] = []
    orders = service_context.get("orders") or []

    lines.append(f"嗯，{_user_need_phrase(intent.route_intent)}。")

    if intent.needs_clarify:
        lines.append("不过您刚说的我还差一点点信息，得再确认下才能帮您办")
    elif intent.alternatives:
        alt_labels: list[str] = []
        for alt in intent.alternatives[:2]:
            code = str(alt.get("intent") or "")
            if not code or code == intent.route_intent:
                continue
            desc = INTENT_CATALOG.get(code) or _INTENT_LABELS.get(code, "")
            if desc:
                alt_labels.append(desc.split("（")[0].strip())
        if alt_labels:
            joined = "、".join(alt_labels[:2])
            lines.append(f"也不排除跟{joined}沾边，我先按您刚才说的往下查")

    if len(orders) > 1:
        lines.append(f"您这边有 {len(orders)} 笔订单，得先对上是哪一笔")
    elif len(orders) == 1:
        title = str(orders[0].get("title") or "")
        if title:
            lines.append(f"我先围绕「{_clip(title, 20)}」这笔看看")

    return [ln for ln in lines if ln.strip()]


def build_knowledge_thought_lines(titles: list[str]) -> list[str]:
    if not titles:
        return []
    if len(titles) == 1:
        return [f"我翻翻「{titles[0]}」里的规则，别跟您说岔了"]
    joined = "」「".join(titles[:3])
    return [f"我对照下「{joined}」这些规则再答，不瞎猜"]


_UNCERTAIN_HINTS = (
    "可能",
    "不确定",
    "再看看",
    "核实",
    "怀疑",
    "不太",
    "也许",
    "还得",
    "再查",
    "不够",
    "遗漏",
    "再确认",
)


def _looks_uncertain(text: str) -> bool:
    return any(h in text for h in _UNCERTAIN_HINTS)


def _brief_prev_step(prev: dict[str, Any]) -> str:
    action = str(prev.get("action") or "")
    if prev.get("error"):
        return "刚才那一步没走通"
    obs = prev.get("observation")
    if isinstance(obs, dict) and obs.get("ok") is False:
        err = str(obs.get("error") or "结果不太对")
        return _sanitize(err, 80)
    phrase = _TOOL_PHRASES.get(action, "查了一圈")
    lines = _observation_lines(action, obs, {})
    if lines:
        return f"{phrase}，{lines[0]}"
    return phrase


def build_react_loop_bridge_lines(
    *,
    step_idx: int,
    prev_trace: dict[str, Any] | None,
    thought: str = "",
) -> list[str]:
    """ReAct 进入下一轮前：承接上一步，表达「再想想」。"""
    if step_idx <= 1 or not prev_trace:
        return []

    lines: list[str] = []
    summary = _brief_prev_step(prev_trace)

    if prev_trace.get("error"):
        lines.append("欸，刚才那步好像不太对，我换个思路再看看。")
    else:
        lines.append(f"好，{summary}。")

    if thought and _looks_uncertain(thought):
        cleaned = _sanitize(thought, 160)
        if cleaned:
            lines.append(f"嗯…{cleaned}")
        lines.append("感觉还不够准，再核实一下。")
    elif step_idx >= 3:
        lines.append("我再核对一轮，免得漏掉对您重要的细节。")
    else:
        lines.append("还差一块信息，接着往下捋。")

    return lines


def build_react_reconsider_lines(*, reason: str) -> list[str]:
    return [f"欸，{reason}，我重新捋一下下一步。"]


def build_react_continue_lines(
    *,
    thought: str,
    step_idx: int,
    max_steps: int,
) -> list[str]:
    """工具执行完、尚未 finish 时，提示还会继续循环。"""
    if step_idx >= max_steps - 1:
        return ["步数快用完了，我尽量用已有信息给您说结论。"]
    if _looks_uncertain(thought):
        return ["嗯…刚才的判断还不够稳，再查一项印证下。"]
    return ["这条线先记下，接着往下捋。"]


def build_pre_action_thought_lines(
    *,
    thought: str,
    action: str,
    action_input: dict[str, Any] | None,
    step_idx: int,
) -> list[str]:
    lines: list[str] = []
    cleaned = _sanitize(thought, 320)

    if cleaned:
        parts = _split_sentences(cleaned)
        for i, part in enumerate(parts):
            if i == 0 and step_idx > 1:
                lines.append(f"接下来{part}")
            elif _looks_uncertain(part):
                lines.append(f"嗯…{part}")
            else:
                lines.append(part)
    elif action != "finish":
        lines.append("继续往下看看还缺哪块信息。")

    if action == "finish":
        return lines

    plan = _plan_phrase(action, action_input or {})
    if plan:
        lines.append(f"那我先{plan}。")

    return lines


def build_post_action_thought_lines(
    *,
    thought: str,
    action: str,
    observation: Any,
    service_context: dict,
    step_idx: int,
) -> list[str]:
    if action == "finish":
        return []

    lines: list[str] = []
    obs_lines = _observation_lines(action, observation, service_context)
    for obs in obs_lines:
        lines.append(obs)

    judgment = _judgment_line(action, observation, thought)
    if judgment:
        if _looks_uncertain(thought):
            lines.append(f"不过{judgment}，我还不敢完全说死。")
        else:
            lines.append(judgment)

    return lines


def build_finish_thought_lines(
    *,
    thought: str,
    finish: dict[str, Any],
    step_idx: int,
) -> list[str]:
    lines: list[str] = []
    cleaned = _sanitize(thought, 320)
    if cleaned:
        for part in _split_sentences(cleaned):
            lines.append(part)

    reasoning = _sanitize(str(finish.get("reasoning") or ""), 240)
    if reasoning and reasoning not in (cleaned or ""):
        lines.append(reasoning)

    mode = str(finish.get("mode") or "reply")
    safe = finish.get("safe_to_send", True)
    if mode == "clarify":
        lines.append("信息还不够全，正式回复里会先跟您确认关键点。")
    elif not safe:
        lines.append("有些细节还不能说死，回复会以核实和补充信息为主。")
    else:
        actions = finish.get("suggested_actions") or []
        if actions:
            titles = "、".join(str(a.get("title") or "") for a in actions[:3] if a.get("title"))
            lines.append(f"方案齐了，回复里会建议您{titles}。")
        else:
            lines.append("关键信息都对上了，可以给您明确答复啦。")

    return lines


def build_pre_reply_thought_lines(*, tone_polish: bool) -> list[str]:
    if tone_polish:
        return ["正文写好了，润一下语气，马上给您看。"]
    return ["把结论整理成正式回复，马上给您看。"]


def build_fast_turn_thought_lines(turn_mode: str) -> list[str]:
    if turn_mode == "acknowledgment":
        return [
            "好的收到～",
            "我简短回您，不再从头查一遍啦。",
        ]
    return [
        "接着刚才的话题说～",
        "上一轮查到的还在，我直接接着用。",
    ]


def build_react_thought_lines(
    *,
    thought: str,
    action: str,
    observation: Any,
    action_input: dict[str, Any] | None,
    service_context: dict,
    step_idx: int,
    finish: dict[str, Any] | None = None,
) -> list[str]:
    """兼容旧调用：合并 pre + post + finish。"""
    if action == "finish" and finish is not None:
        return build_finish_thought_lines(thought=thought, finish=finish, step_idx=step_idx)
    pre = build_pre_action_thought_lines(
        thought=thought, action=action, action_input=action_input, step_idx=step_idx
    )
    post = build_post_action_thought_lines(
        thought=thought,
        action=action,
        observation=observation,
        service_context=service_context,
        step_idx=step_idx,
    )
    return pre + post


def _user_need_phrase(code: str) -> str:
    if code == "clarify":
        return "您还没完全说清想办哪件事，我得再确认下"
    if code == "chitchat":
        return "像是在闲聊，我先应一声，再引导到订单或券"
    if code == "unconfigured":
        return "我还得多听两句才能明白您要啥"
    desc = INTENT_CATALOG.get(code) or _INTENT_LABELS.get(code, "")
    if not desc:
        return "像是想咨询生活服务这边的事"
    head = desc.split("（")[0].strip()
    if head.startswith(("查询", "判断", "申请")):
        return f"像是想{head}"
    return f"可能是{head}相关"


def _replace_intent_codes(text: str) -> str:
    out = text
    for code, desc in {**INTENT_CATALOG, **_INTENT_LABELS}.items():
        if code in out:
            label = desc.split("（")[0].strip()
            out = out.replace(code, label)
    return out


def _sanitize(text: str, max_len: int = 280) -> str:
    if not text:
        return ""
    out = text.strip()
    for name, phrase in _TOOL_PHRASES.items():
        out = re.sub(rf"\b{name}\b", phrase, out, flags=re.I)
    out = re.sub(r"\bReAct\b", "分步推理", out, flags=re.I)
    out = re.sub(r"轨道\s*[AB]", "平台规则", out)
    out = _replace_intent_codes(out)
    for pat in _STRIP_PATTERNS:
        out = re.sub(pat, "", out, flags=re.I)
    out = re.sub(r"关键词/口语规则命中\s*\S+", "从您的表述里能听出重点", out)
    out = re.sub(r"匹配.*?意图", "理解您的需求", out)
    out = re.sub(r"意图[:：]?\s*", "", out)
    out = re.sub(r"\b(configured|unconfigured|chitchat|keyword|semantic)\b", "", out, flags=re.I)
    out = re.sub(r"\b[A-Z][a-zA-Z]{2,}(?:Request|Failure|Reject|Unavailable|Transfer|Complaint|Dispute|Eligibility)\b", "", out)
    out = re.sub(r"\s+", " ", out).strip(" ，,、-—")
    if len(out) > max_len:
        out = out[: max_len - 1] + "…"
    return out


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；])", text)
    merged: list[str] = []
    buf = ""
    for p in parts:
        buf += p
        if len(buf) >= 40 or p.endswith(("。", "！", "？", "；")):
            if buf.strip():
                merged.append(buf.strip())
            buf = ""
    if buf.strip():
        merged.append(buf.strip())
    return merged or [text]


def _clip(text: str, n: int) -> str:
    t = text.strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _plan_phrase(action: str, action_input: dict[str, Any]) -> str:
    base = _TOOL_PHRASES.get(action, "继续查一下订单和券的相关信息")
    oid = action_input.get("order_id")
    vid = action_input.get("voucher_id")
    if oid:
        return f"{base}（这笔订单）"
    if vid:
        return f"{base}（这张券）"
    return base


def _status_phrase(status: str) -> str:
    return _ORDER_STATUS_ZH.get(status, "状态待确认")


def _observation_lines(action: str, observation: Any, ctx: dict) -> list[str]:
    if observation is None:
        return []
    if isinstance(observation, str):
        c = _sanitize(observation, 200)
        return [c] if c else []

    obs = observation if isinstance(observation, dict) else {}
    if obs.get("ok") is False:
        err = str(obs.get("error") or "")
        if "聚焦" in err or "order_id" in err:
            return ["有多笔订单，还没法确定您指哪一笔，后面得请您点选或报商品名"]
        if err:
            return [_sanitize(err, 120)]
        return []

    lines: list[str] = []

    if action == "list_orders":
        count = obs.get("count") or len(obs.get("orders") or [])
        orders = obs.get("orders") or []
        if count == 0:
            return ["订单列表为空"]
        if count == 1:
            t = (orders[0] or {}).get("title") or "一笔订单"
            return [f"只有 1 笔：「{_clip(str(t), 18)}」"]
        titles = "；".join(f"「{_clip(str(o.get('title') or ''), 12)}」" for o in orders[:4])
        extra = f"等共 {count} 笔" if count > 4 else f"共 {count} 笔"
        return [f"{titles}，{extra}"]

    if action == "query_order":
        order = obs.get("order") or {}
        if not order:
            return ["没查到匹配订单"]
        title = _clip(str(order.get("title") or "订单"), 20)
        status = _status_phrase(str(order.get("status") or ""))
        parts = [f"「{title}」{status}"]
        if order.get("paid_amount") is not None:
            parts.append(f"实付 ¥{order['paid_amount']}")
        if order.get("can_refund"):
            parts.append("可自助退款")
        elif str(order.get("status")) == "used":
            parts.append("已核销，一般不能自助退")
        if order.get("expire_time"):
            parts.append(f"有效期至 {str(order['expire_time'])[:10]}")
        return ["，".join(parts)]

    if action == "query_voucher":
        voucher = voucher_from_payload(obs)
        if not voucher:
            return ["未找到关联团购券"]
        title = _clip(str(voucher.get("title") or "券"), 16)
        status = _status_phrase(str(voucher.get("status") or ""))
        line = f"券「{title}」{status}"
        rule = str(voucher.get("usage_rule") or "")
        if rule:
            line += f"，{_clip(rule, 56)}"
        code = voucher.get("code")
        if code:
            line += f"；券码 {str(code)[:8]}…" if len(str(code)) > 8 else f"；券码 {code}"
        return [line]

    if action == "query_focus_bundle":
        bundle = normalize_focus_bundle(obs if isinstance(obs, dict) else {})
        lines: list[str] = []
        order = order_from_payload(bundle) or {}
        if order.get("title"):
            lines.append(
                f"订单「{_clip(str(order['title']), 18)}」{_status_phrase(str(order.get('status') or ''))}"
            )
        voucher = voucher_from_payload(bundle) or {}
        if voucher:
            rule = str(voucher.get("usage_rule") or "")
            if rule:
                lines.append(_clip(rule, 72))
            store = store_from_payload(bundle) or {}
            resv = reservation_context(
                usage_rule=rule,
                service_type=str(order.get("service_type") or ""),
                supports_reservation=bool(store.get("supports_reservation")),
                order_metadata=order.get("metadata") if isinstance(order.get("metadata"), dict) else {},
            )
            lines.append(f"预约要求：{resv['label']}，{resv['detail'][:48]}")
        store = store_from_payload(bundle) or {}
        if store.get("store_name"):
            lines.append(
                f"门店 {_clip(str(store['store_name']), 16)}，营业 {store.get('business_hours') or '待确认'}"
            )
        return lines

    if action == "query_store":
        store = obs.get("store") or {}
        if not store:
            return []
        name = _clip(str(store.get("store_name") or store.get("merchant_name") or "门店"), 18)
        hours = store.get("business_hours")
        addr = store.get("address")
        parts = [name]
        if hours:
            parts.append(f"营业 {hours}")
        if addr:
            parts.append(f"地址 {_clip(str(addr), 28)}")
        return ["，".join(parts)]

    if action == "query_refund":
        if obs.get("can_refund"):
            amt = obs.get("refundable_amount")
            return [f"可以退款{f'，预计 ¥{amt}' if amt is not None else ''}"]
        reason = str(obs.get("reason") or obs.get("limit_reason") or "不符合当前退款规则")
        return [f"暂不可退：{_clip(reason, 60)}"]

    if action == "query_coupon":
        coupons = obs.get("coupons") or []
        if not coupons:
            return ["没有可用优惠券记录"]
        out = []
        for c in coupons[:2]:
            out.append(
                f"「{_clip(str(c.get('title') or ''), 12)}」{_COUPON_STATUS_ZH.get(str(c.get('status') or ''), '状态待确认')}"
                f"{('，' + _clip(str(c.get('rule_text') or ''), 40)) if c.get('rule_text') else ''}"
            )
        return out

    if action == "run_diagnosis":
        return _diagnosis_lines(obs)

    return []


def _diagnosis_lines(obs: dict) -> list[str]:
    lines: list[str] = []
    case_name = str(obs.get("case_name") or "").strip()
    if case_name:
        lines.append(f"对照平台规则看，更像是：{case_name}")

    for s in (obs.get("diagnosis") or [])[:5]:
        check = str(s.get("check") or "").strip()
        detail = str(s.get("detail") or "").strip()
        status = str(s.get("status") or "").lower()
        if not check and not detail:
            continue
        mark = "✓" if status in ("ok", "pass", "yes") else "✗" if status in ("fail", "failed", "no") else "·"
        body = detail or check
        lines.append(f"{mark} {_clip(body, 64)}" if not check else f"{mark} {_clip(check, 24)}，{_clip(body, 48)}")

    solutions = obs.get("solution") or []
    if solutions:
        titles = "、".join(str(s.get("title") or "") for s in solutions[:3] if s.get("title"))
        if titles:
            lines.append(f"接下来可以帮您：{titles}")

    if not lines:
        lines.append("完成了一轮规则对照，缩小了可能原因")
    return lines


def _judgment_line(action: str, observation: Any, thought: str) -> str | None:
    if not isinstance(observation, dict):
        return None

    if observation.get("ok") is False:
        return "这一步数据不够，得换查法或请您补充信息"

    if action == "query_order":
        order = observation.get("order") or {}
        st = str(order.get("status") or "")
        if st == "unused":
            return "订单本身有效，问题多半不在「没券/没单」上"
        if st == "used":
            return "已经核销过了，后续得走售后/投诉而不是再核销"
        if st == "expired":
            return "订单/券已过期，得看是否还能过期退"

    if action == "query_voucher":
        voucher = voucher_from_payload(observation if isinstance(observation, dict) else {})
        if not voucher:
            return None
        st = str(voucher.get("status") or "")
        if st == "unused":
            return "平台侧券仍有效，若现场用不了，更该查门店或设备"
        if st == "expired":
            return "券在系统里已过期，跟用户说「还能用」会对不上"

    if action == "run_diagnosis":
        case_name = str(observation.get("case_name") or "")
        if any(k in case_name for k in ("设备", "扫码", "同步")):
            return "倾向于技术/同步问题，不是用户操作失误"
        if any(k in case_name for k in ("商家", "拒绝")):
            return "更像是商家主观不接待，平台侧券没问题"
        if any(k in case_name for k in ("预约",)):
            return "根因可能是没预约或预约无效，不是券码坏了"

    cleaned = _sanitize(thought, 160)
    if cleaned and any(w in cleaned for w in ("因此", "所以", "看来", "判断", "应该", "可能")):
        return _clip(cleaned, 120)

    return None


# 兼容旧接口
def build_opening_thought(intent: IntentResult, message: str, service_context: dict) -> str:
    lines = build_session_opening_lines(intent, message, service_context)
    return lines[0] if lines else ""


def build_knowledge_thought(titles: list[str]) -> str | None:
    lines = build_knowledge_thought_lines(titles)
    return lines[0] if lines else None


def build_pre_reply_thought(*, tone_polish: bool) -> str:
    lines = build_pre_reply_thought_lines(tone_polish=tone_polish)
    return lines[0] if lines else ""


def build_react_thought(**kwargs: Any) -> str | None:
    lines = build_react_thought_lines(**kwargs)
    return "\n".join(lines) if lines else None
