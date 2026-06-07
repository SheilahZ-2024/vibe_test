"""统一 Turn Pipeline — Plan → Gather ReAct → Compose → Emit。"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas.api import EdgeContextPacket
from app.services.agent_state import (
    AgentFinishDecision,
    AgentRunResult,
    AgentState,
)
from app.services.context import ServiceContextBuilder
from app.services.decision_composer import DecisionComposer
from app.services.fact_sheet import build_fact_sheet, reservation_reply_constraints
from app.services.gather_react import BoundedGatherReAct
from app.services.intent import IntentResult
from app.services.llm import LLMService
from app.services.reply_polisher import ReplyPolisher
from app.services.sessions import SessionStore
from app.services.thinking_narrative import (
    build_compose_thought_lines,
    build_gather_react_thought_lines,
)
from app.services.thinking_stream import stream_thinking_lines
from app.services.turn_plan import TurnPlan, TurnPlanner

logger = logging.getLogger(__name__)


def _trim_history(history: list[dict], max_turns: int) -> list[dict]:
    if not history or max_turns <= 0:
        return []
    return history[-max_turns:]


class UnifiedTurnPipeline:
    def __init__(self):
        self.context_builder = ServiceContextBuilder()
        self.llm = LLMService()
        self.planner = TurnPlanner()
        self.gatherer = BoundedGatherReAct(llm=self.llm)
        self.composer = DecisionComposer(self.llm)
        self.polisher = ReplyPolisher(self.llm)

    async def run_stream(
        self,
        db: AsyncSession,
        store: SessionStore,
        *,
        session_id: str,
        user_id: str,
        message: str,
        edge: EdgeContextPacket,
        history: list[dict],
        service_context: dict | None = None,
        on_step: Callable | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        self.llm.ensure_live()

        if service_context is None:
            service_context = await self.context_builder.build(db, edge, user_id)

        trimmed = _trim_history(history, settings.agent_history_max_turns)
        agent_ctx = await store.get_agent_context(session_id) or {}

        plan = await self.planner.plan(message, trimmed, agent_ctx if agent_ctx else None, edge)

        intent_result = plan.intent_result or IntentResult(
            plan.route_intent,
            plan.route_intent,
            plan.confidence,
            plan.reasoning,
            plan.source,
            plan.task_type == "clarify",
            [],
            plan.route_category,
            plan.turn_mode,
        )

        state = AgentState(
            session_id=session_id,
            user_id=user_id,
            message=message,
            service_context=service_context,
            intent_result=intent_result,
            knowledge_articles=[],
            focus_order_id=plan.focus_order_id or edge.focus_order_id,
            prior_agent_ctx=agent_ctx if agent_ctx else None,
        )

        yield "context_ready", {
            "intent": plan.route_intent,
            "intent_meta": plan.to_intent_meta(),
            "focus_order_id": state.focus_order_id,
            "knowledge_titles": [],
            "task_type": plan.task_type,
            "gather_mode": plan.to_intent_meta().get("gather_mode"),
        }

        gather_meta: dict[str, Any] = {}
        thinking_emitted = False
        async for event, payload in self.gatherer.gather_stream(
            db, state, plan, trimmed, on_step=on_step
        ):
            if event == "thinking_token":
                thinking_emitted = True
                yield event, payload
            elif event == "gather_step":
                yield "gather_step", {**payload, "phase": "gather_react"}
            elif event == "gather_done":
                gather_meta = payload

        fact_sheet = gather_meta.get("fact_sheet") or build_fact_sheet(
            service_context=state.service_context,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            focus_order_id=state.focus_order_id,
        )

        if not thinking_emitted:
            async for ev, pl in stream_thinking_lines(
                build_gather_react_thought_lines(state.trace, fact_sheet, state.gather_meta)
            ):
                yield ev, pl

        if gather_meta.get("needs_clarify_focus") and plan.task_type not in ("acknowledgment",):
            titles = "、".join(
                f"「{o.get('title')}」" for o in (service_context.get("orders") or [])[:4]
            )
            finish = AgentFinishDecision(
                mode="clarify",
                draft_message=f"我看到您有多笔订单（{titles}等），请先告诉我要处理哪一笔，或在上方点选。",
                safe_to_send=True,
                reasoning="多订单未聚焦",
            )
            result = _build_result(state, plan, finish, fact_sheet, reply_source="gather_clarify")
            async for ev, pl in self._emit_reply(
                state, plan, result, finish.draft_message, compose_ms=0, user_message=message
            ):
                yield ev, pl
            return

        compose_started = time.perf_counter()
        compose_out = await self.composer.compose(state, plan, trimmed, fact_sheet)
        compose_ms = compose_out.compose_ms or int((time.perf_counter() - compose_started) * 1000)

        async for ev, pl in stream_thinking_lines(
            build_compose_thought_lines(compose_out.payload, compose_ms=compose_ms)
        ):
            yield ev, pl

        if compose_out.payload.get("decision", {}).get("focus_order_id"):
            state.focus_order_id = str(compose_out.payload["decision"]["focus_order_id"])

        reply_source = "compose"
        if plan.skip_compose_llm:
            reply_source = "compose_template"
        elif compose_out.retries > 0:
            reply_source = "compose_retry"

        result = _build_result(state, plan, compose_out.finish, fact_sheet, reply_source=reply_source)
        async for ev, pl in self._emit_reply(
            state,
            plan,
            result,
            compose_out.reply,
            compose_ms=compose_ms,
            gather_ms=gather_meta.get("gather_ms"),
            user_message=message,
        ):
            yield ev, pl

    async def _emit_reply(
        self,
        state: AgentState,
        plan: TurnPlan,
        result: AgentRunResult,
        reply: str,
        *,
        compose_ms: int,
        gather_ms: int | None = None,
        user_message: str = "",
    ) -> AsyncIterator[tuple[str, Any]]:
        mode = str(result.finish.mode or "reply")
        constraints = reservation_reply_constraints(result.fact_sheet)
        tone = self.polisher.should_polish(reply, mode=mode)
        if tone:
            result.reply_source = f"{result.reply_source}+tone"

        yield "agent", {
            "intent": plan.route_intent,
            "intent_meta": plan.to_intent_meta(),
            "focus_order_id": result.focus_order_id,
            "trace": [t.to_dict() for t in result.trace],
            "finish": result.finish.to_dict(),
            "knowledge_titles": result.knowledge_titles,
            "tool_count": len(result.tool_calls),
            "pending_confirmations": [p.to_dict() for p in result.pending_confirmations],
            "reply_source": result.reply_source,
            "fact_sheet": result.fact_sheet,
            "gather_meta": result.gather_meta,
            "compose_ms": compose_ms,
            "gather_ms": gather_ms,
            "pipeline": "unified_gather_react",
            "tone_polish": tone,
        }

        full: list[str] = []
        stream = self.polisher.polish_stream(
            reply,
            user_message=user_message or state.message,
            mode=mode,
            fact_constraints=constraints,
        )
        async for chunk in stream:
            full.append(chunk)
            yield "token", {"text": chunk}

        result.finish.draft_message = "".join(full)
        yield "result", result


def _build_result(
    state: AgentState,
    plan: TurnPlan,
    finish: AgentFinishDecision,
    fact_sheet: dict,
    *,
    reply_source: str,
) -> AgentRunResult:
    return AgentRunResult(
        intent_result=state.intent_result,
        focus_order_id=state.focus_order_id,
        finish=finish,
        trace=state.trace,
        tool_calls=state.tool_calls,
        diagnosis_advisories=state.diagnosis_advisories,
        knowledge_titles=[getattr(a, "title", str(a)) for a in state.knowledge_articles],
        pending_confirmations=list(state.pending_confirmations),
        reply_source=reply_source,
        fact_sheet=fact_sheet,
        gather_meta=dict(state.gather_meta or {}),
    )
