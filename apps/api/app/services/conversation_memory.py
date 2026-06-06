"""跨轮会话记忆 — 供接话 ReAct 复用上一轮查数结果。"""

from __future__ import annotations

from typing import Any

from app.services.agent_state import AgentRunResult
from app.services.tool_payloads import (
    normalize_focus_bundle,
    order_from_payload,
    store_from_payload,
    unwrap_tool_result,
    voucher_from_payload,
)
from app.services.usage_rules import reservation_context


def _clip(text: str, n: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def summarize_tool_call(name: str, result: Any) -> str | None:
    raw = unwrap_tool_result(result)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("ok") is False:
        err = raw.get("error")
        return f"{name} 未成功：{_clip(str(err or ''), 60)}" if err else None

    if name == "query_focus_bundle":
        bundle = normalize_focus_bundle(raw)
        chunks: list[str] = []
        order = order_from_payload(bundle) or {}
        if order.get("title"):
            paid = f"，实付 ¥{order.get('paid_amount')}" if order.get("paid_amount") is not None else ""
            chunks.append(
                f"订单「{_clip(str(order['title']), 20)}」状态 {order.get('status') or '?'}{paid}"
            )
        voucher = voucher_from_payload(bundle) or {}
        if voucher:
            rule = str(voucher.get("usage_rule") or "").strip()
            chunks.append(
                f"券码 {voucher.get('code')}，{voucher.get('status') or '状态未知'}"
                + (f"；规则 {_clip(rule, 48)}" if rule else "")
            )
            store = store_from_payload(bundle) or {}
            resv = reservation_context(
                usage_rule=rule,
                service_type=str(order.get("service_type") or ""),
                supports_reservation=bool(store.get("supports_reservation")),
                order_metadata=order.get("metadata") if isinstance(order.get("metadata"), dict) else {},
            )
            chunks.append(f"预约 {resv['label']}（{resv['detail'][:40]}）")
        store = store_from_payload(bundle) or {}
        if store.get("store_name"):
            chunks.append(
                f"门店「{_clip(str(store['store_name']), 16)}」"
                f"营业 {store.get('business_hours') or '时间待确认'}"
            )
        return "；".join(c for c in chunks if c) or None

    if name == "query_voucher":
        v = voucher_from_payload(raw)
        if not v:
            return None
        rule = str(v.get("usage_rule") or "").strip()
        base = f"券「{_clip(str(v.get('title') or ''), 18)}」{v.get('status') or ''}，码 {v.get('code') or '?'}"
        return f"{base}；{_clip(rule, 56)}" if rule else base

    if name == "query_order":
        order = order_from_payload(raw) or {}
        if not order:
            return None
        return f"订单「{_clip(str(order.get('title') or ''), 20)}」{order.get('status') or ''}"

    if name == "query_store":
        s = store_from_payload(raw) or {}
        if not s:
            return None
        name_part = s.get("store_name") or s.get("name") or ""
        return f"门店 {_clip(str(name_part), 16)}，{s.get('business_hours') or ''}"

    if name == "query_refund":
        r = raw.get("refund") or raw.get("case") or {}
        if isinstance(r, dict) and r:
            return f"售后 {r.get('status') or '处理中'}"
        return "当前无进行中的售后单" if raw.get("eligible") is False else None

    if name == "run_diagnosis":
        case = raw.get("case_id") or raw.get("case_name")
        return f"诊断结论 {case}" if case else None

    if name == "list_orders":
        n = raw.get("count") or len(raw.get("orders") or [])
        return f"共 {n} 笔订单"

    return None


def build_agent_context(result: AgentRunResult) -> dict:
    """持久化到 Redis，供下一轮接话读取。"""
    lines: list[str] = []
    seen: set[str] = set()
    for tc in result.tool_calls:
        if not isinstance(tc, dict):
            continue
        summary = summarize_tool_call(str(tc.get("name") or ""), tc.get("result"))
        if summary and summary not in seen:
            seen.add(summary)
            lines.append(summary)

    for step in result.trace[-6:]:
        obs = step.observation
        if isinstance(obs, dict):
            summary = summarize_tool_call(str(step.action or ""), obs)
            if summary and summary not in seen:
                seen.add(summary)
                lines.append(summary)

    return {
        "focus_order_id": result.focus_order_id,
        "intent": result.intent_result.route_intent,
        "route_category": result.intent_result.route_category,
        "digest": "\n".join(lines[:8]),
        "last_reply": _clip(result.finish.draft_message, 480),
        "tool_names": [str(tc.get("name")) for tc in result.tool_calls[-8:] if isinstance(tc, dict) and tc.get("name")],
    }


def format_memory_block(ctx: dict | None) -> str:
    if not ctx:
        return "（无上一轮查数记忆，本轮需按需查询）"
    parts = [
        f"聚焦订单：{ctx.get('focus_order_id') or '未指定'}",
        f"上一轮意图：{ctx.get('intent') or '?'}",
    ]
    digest = str(ctx.get("digest") or "").strip()
    if digest:
        parts.append("已掌握事实：\n" + digest)
    last = str(ctx.get("last_reply") or "").strip()
    if last:
        parts.append("上一轮回复摘要：\n" + last)
    return "\n".join(parts)
