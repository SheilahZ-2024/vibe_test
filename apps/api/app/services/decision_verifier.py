"""Compose 结果程序校验 — 自监督第二层。"""

from __future__ import annotations

import re
from typing import Any

from app.services.fact_sheet import reservation_reply_constraints


def verify_compose_payload(data: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []

    reply = str(data.get("reply") or "").strip()
    if not reply:
        errors.append("reply 为空")

    decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
    mode = str(decision.get("mode") or "reply")
    self_check = data.get("self_check") if isinstance(data.get("self_check"), dict) else {}

    if mode == "reply" and self_check.get("needs_clarify") is True and self_check.get("safe_to_send") is True:
        errors.append("needs_clarify 与 safe_to_send 矛盾")

    reasoning = data.get("reasoning") if isinstance(data.get("reasoning"), dict) else {}
    facts_used = reasoning.get("facts_used") or []
    if isinstance(facts_used, list) and facts_used and facts:
        known = set(facts.keys()) | {
            "focus_order_id",
            "order_id",
            "order_title",
            "order_status",
            "usage_rule",
            "store_name",
            "store_phone",
            "needs_reservation",
            "has_reservation",
            "diagnosis_case_id",
            "diagnosis_case_name",
        }
        unknown = [str(k).strip() for k in facts_used if str(k).strip() and str(k).strip() not in known]
        # 未知键仅记录，不阻断发送（避免 compose 双倍 LLM）
        if len(unknown) > len(facts_used) // 2 + 1:
            errors.append(f"facts_used 多数键不在 fact_sheet：{unknown[:3]}")

    constraint = reservation_reply_constraints(facts)
    if constraint and reply:
        bad_patterns = (
            r"没有(?:预约)?(?:要求|规定)",
            r"查不到(?:预约)?(?:要求|规定)",
            r"未预约(?:也)?可以核销",
            r"没预约(?:也)?能核销",
            r"直接核销",
        )
        for pat in bad_patterns:
            if re.search(pat, reply):
                errors.append(f"违反预约硬性约束: {pat}")
                break

    if facts.get("needs_reservation") is True and not facts.get("has_reservation"):
        if re.search(r"无需预约|不用预约|不需要预约", reply):
            errors.append("needs_reservation=true 但回复声称无需预约")

    return len(errors) == 0, errors
