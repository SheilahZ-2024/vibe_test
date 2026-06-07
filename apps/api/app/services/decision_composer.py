"""Compose 阶段 — 单次 LLM 理解、推理、自监督与成稿。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.services.agent_state import AgentFinishDecision, AgentState
from app.services.compose_prompts import (
    build_compose_retry_prompt,
    build_compose_system_prompt,
    build_compose_user_prompt,
)
from app.services.decision_verifier import verify_compose_payload
from app.services.fact_sheet import format_fact_sheet_block
from app.services.llm import LLMService
from app.services.react_json import try_parse_react_json
from app.services.turn_plan import TurnPlan


@dataclass
class ComposeResult:
    payload: dict[str, Any]
    finish: AgentFinishDecision
    reply: str
    compose_ms: int = 0
    retries: int = 0
    raw: str = ""


class DecisionComposer:
    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    async def compose(
        self,
        state: AgentState,
        plan: TurnPlan,
        history: list[dict],
        fact_sheet: dict[str, Any],
    ) -> ComposeResult:
        if plan.skip_compose_llm:
            reply = _acknowledgment_reply(state.prior_agent_ctx)
            finish = AgentFinishDecision(
                mode="reply",
                draft_message=reply,
                safe_to_send=True,
                reasoning="致谢接话模板",
            )
            return ComposeResult(
                payload={"reply": reply, "decision": {"mode": "reply"}},
                finish=finish,
                reply=reply,
                compose_ms=0,
            )

        fact_block = format_fact_sheet_block(fact_sheet)
        system = build_compose_system_prompt(state, plan, fact_block)
        user = build_compose_user_prompt(state, history, plan)

        retries = 0
        last_errors: list[str] = []
        started = time.perf_counter()
        raw = ""
        data: dict | None = None

        while retries <= settings.agent_compose_max_retries:
            user_block = user if not last_errors else user + "\n\n" + build_compose_retry_prompt(last_errors)
            raw = await self.llm.complete_with_history(
                system,
                history,
                user_block,
                temperature=settings.agent_compose_temperature,
                max_tokens=settings.agent_compose_max_tokens,
            )
            data = try_parse_react_json(raw or "") if raw else None
            if not data:
                last_errors = ["JSON 解析失败"]
                retries += 1
                continue
            ok, last_errors = verify_compose_payload(data, fact_sheet)
            if ok:
                break
            retries += 1

        compose_ms = int((time.perf_counter() - started) * 1000)

        if not data:
            finish = AgentFinishDecision(
                mode="clarify",
                draft_message="我这边需要再确认一下您的具体情况，您方便说是哪一笔订单或券吗？",
                safe_to_send=True,
                reasoning="compose JSON 失败",
            )
            return ComposeResult(
                payload={},
                finish=finish,
                reply=finish.draft_message,
                compose_ms=compose_ms,
                retries=retries,
                raw=raw or "",
            )

        finish = _finish_from_payload(data, fact_sheet)
        return ComposeResult(
            payload=data,
            finish=finish,
            reply=finish.draft_message,
            compose_ms=compose_ms,
            retries=retries,
            raw=raw or "",
        )


def _finish_from_payload(data: dict[str, Any], fact_sheet: dict[str, Any]) -> AgentFinishDecision:
    decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
    self_check = data.get("self_check") if isinstance(data.get("self_check"), dict) else {}
    mode = str(decision.get("mode") or "reply")
    if self_check.get("needs_clarify"):
        mode = "clarify"

    reply = str(data.get("reply") or "").strip()
    safe = bool(self_check.get("safe_to_send", mode == "reply"))
    if not reply:
        mode = "clarify"
        reply = "我还需要一点信息才能准确帮您，您说的是哪一笔订单呢？"
        safe = True

    reasoning_block = data.get("reasoning") if isinstance(data.get("reasoning"), dict) else {}
    reasoning = str(reasoning_block.get("rule_application") or "")

    suggested = data.get("suggested_actions") or []
    clean_actions: list[dict[str, str]] = []
    if isinstance(suggested, list):
        for item in suggested[:4]:
            if isinstance(item, dict) and item.get("action_id") and item.get("title"):
                clean_actions.append({"action_id": str(item["action_id"]), "title": str(item["title"])})

    adv_case = fact_sheet.get("diagnosis_case_id")
    adv_name = fact_sheet.get("diagnosis_case_name")

    return AgentFinishDecision(
        mode=mode if mode in ("reply", "clarify") else "reply",
        draft_message=reply,
        safe_to_send=safe,
        reasoning=reasoning,
        suggested_actions=clean_actions,
        approved_case_id=str(adv_case) if adv_case else None,
        approved_case_name=str(adv_name) if adv_name else None,
    )


def _acknowledgment_reply(prior_ctx: dict | None) -> str:
    if prior_ctx and prior_ctx.get("last_reply"):
        return "不客气～刚才说的您要是还有哪点不清楚，随时问我；其他订单或券的问题也可以继续说。"
    return "不客气～还有其他订单、核销或退款相关的问题，随时跟我说。"
