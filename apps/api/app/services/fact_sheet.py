"""从工具结果 + 诊断 + 上下文抽取「不可编造」的业务事实，供终稿与润色锚定。"""

from __future__ import annotations

from typing import Any

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


def _merge_bundle(facts: dict, raw: dict) -> None:
    bundle = normalize_focus_bundle(raw)
    order = order_from_payload(bundle) or {}
    voucher = voucher_from_payload(bundle) or {}
    store = store_from_payload(bundle) or {}

    if order.get("title"):
        facts["order_title"] = str(order["title"])
        facts["order_status"] = str(order.get("status") or "")
        facts["order_id"] = str(order.get("id") or "")
    if voucher.get("usage_rule"):
        facts["usage_rule"] = str(voucher["usage_rule"]).strip()
    if voucher.get("code"):
        facts["voucher_code"] = str(voucher["code"])
    if voucher.get("status"):
        facts["voucher_status"] = str(voucher["status"])
    if store.get("store_name"):
        facts["store_name"] = str(store["store_name"])
    if store.get("business_hours"):
        facts["store_hours"] = str(store["business_hours"])
    if store.get("phone"):
        facts["store_phone"] = str(store["phone"])
    if "supports_reservation" in store:
        facts["supports_reservation"] = bool(store.get("supports_reservation"))

    rule = facts.get("usage_rule") or str(voucher.get("usage_rule") or "")
    resv = reservation_context(
        usage_rule=rule,
        service_type=str(order.get("service_type") or ""),
        supports_reservation=bool(store.get("supports_reservation")),
        order_metadata=order.get("metadata") if isinstance(order.get("metadata"), dict) else {},
    )
    facts["reservation_label"] = resv["label"]
    facts["reservation_detail"] = resv["detail"]
    facts["needs_reservation"] = resv["needs_reservation"]
    facts["has_reservation"] = resv["has_reservation"]


def build_fact_sheet(
    *,
    service_context: dict | None,
    tool_calls: list[dict] | None,
    diagnosis_advisories: list[dict] | None,
    focus_order_id: str | None,
) -> dict[str, Any]:
    facts: dict[str, Any] = {"focus_order_id": focus_order_id}

    ctx = service_context or {}
    if focus_order_id:
        focus_store_id: str | None = None
        for order in ctx.get("orders") or []:
            if str(order.get("id")) == str(focus_order_id):
                if order.get("title"):
                    facts.setdefault("order_title", str(order["title"]))
                    facts.setdefault("order_status", str(order.get("status") or ""))
                focus_store_id = str(order.get("store_id") or "") or None
                for voucher in ctx.get("vouchers") or []:
                    if str(voucher.get("order_id")) == str(focus_order_id):
                        if voucher.get("usage_rule"):
                            facts.setdefault("usage_rule", str(voucher["usage_rule"]).strip())
                        if not focus_store_id and voucher.get("store_id"):
                            focus_store_id = str(voucher["store_id"])
                        break
                break
        if focus_store_id:
            for store in ctx.get("stores") or []:
                if str(store.get("id")) == str(focus_store_id):
                    if store.get("store_name"):
                        facts.setdefault("store_name", str(store["store_name"]))
                    if store.get("business_hours"):
                        facts.setdefault("store_hours", str(store["business_hours"]))
                    if store.get("phone"):
                        facts.setdefault("store_phone", str(store["phone"]))
                    if "supports_reservation" in store:
                        facts.setdefault("supports_reservation", bool(store.get("supports_reservation")))
                    break

    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or "")
        raw = unwrap_tool_result(tc.get("result"))
        if not raw or not isinstance(raw, dict):
            continue
        if name == "query_focus_bundle":
            _merge_bundle(facts, raw)
        elif name == "query_order":
            order = order_from_payload(raw) or {}
            if order.get("title"):
                facts["order_title"] = str(order["title"])
                facts["order_status"] = str(order.get("status") or "")
        elif name == "query_voucher":
            voucher = voucher_from_payload(raw) or {}
            if voucher.get("usage_rule"):
                facts["usage_rule"] = str(voucher["usage_rule"]).strip()
        elif name == "query_store":
            store = store_from_payload(raw) or {}
            if store.get("store_name"):
                facts["store_name"] = str(store["store_name"])
            if store.get("phone"):
                facts["store_phone"] = str(store["phone"])

    for adv in diagnosis_advisories or []:
        if not isinstance(adv, dict):
            continue
        if adv.get("case_id"):
            facts["diagnosis_case_id"] = str(adv["case_id"])
        if adv.get("case_name"):
            facts["diagnosis_case_name"] = str(adv["case_name"])
        break

    if facts.get("usage_rule") and "needs_reservation" not in facts:
        resv = reservation_context(usage_rule=str(facts["usage_rule"]))
        facts["reservation_label"] = resv["label"]
        facts["reservation_detail"] = resv["detail"]
        facts["needs_reservation"] = resv["needs_reservation"]
        facts["has_reservation"] = resv["has_reservation"]

    return facts


def format_fact_sheet_block(facts: dict[str, Any]) -> str:
    if not facts:
        return "（尚无结构化事实）"
    lines: list[str] = []
    if facts.get("order_title"):
        line = f"订单「{facts['order_title']}」"
        if facts.get("order_status"):
            line += f"，状态 {facts['order_status']}"
        lines.append(line)
    if facts.get("usage_rule"):
        lines.append(f"券使用规则：{_clip(str(facts['usage_rule']), 120)}")
    if facts.get("needs_reservation") is not None:
        label = facts.get("reservation_label") or ("须预约" if facts["needs_reservation"] else "无需预约")
        detail = facts.get("reservation_detail") or ""
        lines.append(f"预约要求：{label}（{detail[:80]}）")
    if facts.get("store_name"):
        extra = []
        if facts.get("store_hours"):
            extra.append(f"营业 {facts['store_hours']}")
        if facts.get("store_phone"):
            extra.append(f"电话 {facts['store_phone']}")
        lines.append(f"门店 {facts['store_name']}" + ("，" + "，".join(extra) if extra else ""))
    if facts.get("diagnosis_case_name"):
        lines.append(f"诊断参考 Case：{facts['diagnosis_case_id']} {facts['diagnosis_case_name']}")
    return "\n".join(lines) if lines else "（尚无结构化事实）"


def reservation_reply_constraints(facts: dict[str, Any]) -> str | None:
    """预约类问题的硬性约束 — 终稿/润色不得违背。"""
    if facts.get("needs_reservation") is not True:
        return None
    if facts.get("has_reservation"):
        return "用户已有预约记录，可引导按时到店核销。"
    rule = _clip(str(facts.get("usage_rule") or facts.get("reservation_detail") or "须提前预约"), 100)
    return (
        f"该券/套餐【必须预约】：{rule}。"
        "未预约不可核销；禁止回答「查不到预约要求」或「没有预约规定」。"
    )
