"""Gather 阶段 — 有界 ReAct 循环：模型主导工具与规则核实。"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.agent_state import AgentState, AgentTraceStep
from app.services.agent_tools import AgentToolExecutor
from app.services.evidence_gatherer import EvidenceGatherer
from app.services.fact_sheet import build_fact_sheet
from app.services.gather_prompts import build_gather_system_prompt, build_gather_user_prompt
from app.services.llm import LLMService
from app.services.react_json import try_parse_react_json
from app.services.tool_catalog import TOOL_CATALOG, WRITE_TOOLS
from app.services.tool_payloads import normalize_focus_bundle
from app.services.thinking_narrative import (
    format_gather_thought,
    format_tool_observation_thought,
    format_diagnosis_thought,
    format_rules_hint,
)
from app.services.thinking_stream import stream_thinking_line
from app.services.turn_plan import TurnPlan

logger = logging.getLogger(__name__)

_GATHER_TERMINAL = frozenset({"gather_complete", "finish"})


class BoundedGatherReAct:
    def __init__(self, executor: AgentToolExecutor | None = None, llm: LLMService | None = None):
        self.executor = executor or AgentToolExecutor()
        self.llm = llm or LLMService()
        self._fallback = EvidenceGatherer(self.executor)

    async def gather_stream(
        self,
        db: AsyncSession,
        state: AgentState,
        plan: TurnPlan,
        history: list[dict],
        *,
        on_step: Callable | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        started = time.perf_counter()
        orders = state.service_context.get("orders") or []

        if len(orders) == 1 and not state.focus_order_id:
            state.focus_order_id = str(orders[0]["id"])

        if plan.skip_gather_react:
            fact_sheet = build_fact_sheet(
                service_context=state.service_context,
                tool_calls=state.tool_calls,
                diagnosis_advisories=state.diagnosis_advisories,
                focus_order_id=state.focus_order_id,
            )
            meta = _done_meta(fact_sheet, started, needs_clarify_focus=False)
            yield "gather_done", meta
            return

        if self.llm.use_mock:
            meta = await self._fallback.gather(db, state, plan, on_step=on_step)
            yield "gather_done", meta
            return

        await self._maybe_prefetch(db, state)
        if state.trace and state.trace[-1].action == "query_focus_bundle":
            pf = state.trace[-1]
            obs_line = format_tool_observation_thought(
                "query_focus_bundle", pf.observation, state.service_context
            )
            if obs_line:
                async for ev, pl in stream_thinking_line(obs_line):
                    yield ev, pl
            if on_step:
                on_step(pf, state)
            yield "gather_step", _step_payload(pf, state, prefetch=True)

        max_steps = settings.agent_gather_max_steps
        completed = False

        for react_step in range(max_steps):
            if completed:
                break
            step_idx = len(state.trace)
            step_started = time.perf_counter()
            system = build_gather_system_prompt(state, plan, history, step_idx=react_step)
            user = build_gather_user_prompt(state, history, plan, step_idx=react_step)

            raw = await self.llm.complete_with_history(
                system,
                history,
                user,
                temperature=settings.agent_gather_temperature,
                max_tokens=settings.agent_gather_max_tokens,
            )
            data = try_parse_react_json(raw or "") if raw else None
            if not data:
                logger.warning("gather react JSON parse failed step=%s raw_len=%s", step_idx, len(raw or ""))
                break

            thought = str(data.get("thought") or "").strip() or "继续核实"
            action = str(data.get("action") or "").strip()
            action_input = data.get("action_input") if isinstance(data.get("action_input"), dict) else {}
            rules = data.get("rules_to_check") if isinstance(data.get("rules_to_check"), list) else []
            if rules:
                action_input = {**action_input, "rules_to_check": rules}

            if data.get("focus_order_id"):
                state.focus_order_id = str(data["focus_order_id"])

            # 兼容误输出 finish
            if action == "finish":
                action = "gather_complete"
                if not data.get("gather_summary") and isinstance(data.get("finish"), dict):
                    data["gather_summary"] = str(data["finish"].get("reasoning") or thought)

            if action in _GATHER_TERMINAL:
                summary = str(data.get("gather_summary") or thought).strip()
                missing = data.get("missing_info") if isinstance(data.get("missing_info"), list) else []
                state.gather_meta = {
                    "gather_summary": summary,
                    "rules_to_check": rules,
                    "missing_info": missing,
                    "steps": step_idx + 1,
                }
                thought_line = format_gather_thought(thought or summary, rules=rules)
                if thought_line:
                    async for ev, pl in stream_thinking_line(thought_line):
                        yield ev, pl
                elif summary:
                    async for ev, pl in stream_thinking_line(summary[:280]):
                        yield ev, pl
                trace = AgentTraceStep(
                    step_idx,
                    thought,
                    "gather_complete",
                    action_input,
                    observation={"ok": True, "gather_summary": summary, "missing_info": missing},
                )
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "gather_step", _step_payload(trace, state, step_ms=int((time.perf_counter() - step_started) * 1000))
                completed = True
                break

            if action not in TOOL_CATALOG:
                trace = AgentTraceStep(
                    step_idx,
                    thought,
                    action or "?",
                    action_input,
                    observation={"ok": False, "error": f"未知工具 {action}"},
                    error=f"unknown tool {action}",
                )
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "gather_step", _step_payload(trace, state, step_ms=int((time.perf_counter() - step_started) * 1000))
                step_idx += 1
                continue

            if action in WRITE_TOOLS:
                observation = {
                    "ok": False,
                    "error": "Gather 阶段不执行写操作；请 gather_complete，由 Compose 建议用户确认后再办理",
                    "reference_channel": "gather_write_gate",
                }
                trace = AgentTraceStep(step_idx, thought, action, action_input, observation=observation)
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "gather_step", _step_payload(trace, state, step_ms=int((time.perf_counter() - step_started) * 1000))
                step_idx += 1
                continue

            if action in state.executed_tools and action not in ("search_knowledge", "run_diagnosis"):
                observation = {"ok": False, "error": f"只读工具 {action} 已执行，请换工具或 gather_complete"}
                trace = AgentTraceStep(step_idx, thought, action, action_input, observation=observation)
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "gather_step", _step_payload(trace, state, step_ms=int((time.perf_counter() - step_started) * 1000))
                step_idx += 1
                continue

            try:
                result = await self.executor.execute(db, state, action, action_input)
            except Exception as exc:
                logger.exception("gather tool %s failed", action)
                result = {"ok": False, "error": str(exc)[:200]}
                trace = AgentTraceStep(
                    step_idx, thought, action, action_input, observation=result, error=str(exc)[:120]
                )
                state.trace.append(trace)
                state.tool_calls.append({"name": action, "input": action_input, "result": result})
                if on_step:
                    on_step(trace, state)
                yield "gather_step", _step_payload(trace, state, step_ms=int((time.perf_counter() - step_started) * 1000))
                step_idx += 1
                continue

            self._post_tool(state, action, action_input, result)
            rules_hint = format_rules_hint(rules)
            if rules_hint:
                async for ev, pl in stream_thinking_line(rules_hint):
                    yield ev, pl
            thought_line = format_gather_thought(thought, rules=rules)
            if thought_line:
                async for ev, pl in stream_thinking_line(thought_line):
                    yield ev, pl
            obs_line = format_tool_observation_thought(action, result, state.service_context)
            if obs_line and (not thought_line or obs_line not in (thought_line or "")):
                async for ev, pl in stream_thinking_line(obs_line):
                    yield ev, pl
            if action == "run_diagnosis" and isinstance(result, dict):
                diag_line = format_diagnosis_thought(result)
                if diag_line:
                    async for ev, pl in stream_thinking_line(diag_line):
                        yield ev, pl
            trace = AgentTraceStep(step_idx, thought, action, action_input, observation=result)
            state.trace.append(trace)
            state.tool_calls.append({"name": action, "input": action_input, "result": result})
            if on_step:
                on_step(trace, state)
            yield "gather_step", _step_payload(trace, state, step_ms=int((time.perf_counter() - step_started) * 1000))
            step_idx += 1

        if not completed:
            summary = _auto_gather_summary(state)
            state.gather_meta = {
                "gather_summary": summary,
                "rules_to_check": [],
                "missing_info": [],
                "steps": step_idx,
                "auto_closed": True,
            }
            if summary:
                async for ev, pl in stream_thinking_line(summary):
                    yield ev, pl
            trace = AgentTraceStep(
                step_idx,
                "步数上限，使用已有 observation 进入 Compose",
                "gather_complete",
                {},
                observation={"ok": True, "gather_summary": summary, "auto_closed": True},
            )
            state.trace.append(trace)
            if on_step:
                on_step(trace, state)
            yield "gather_step", _step_payload(trace, state)

        fact_sheet = build_fact_sheet(
            service_context=state.service_context,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            focus_order_id=state.focus_order_id,
        )
        needs_clarify = len(orders) > 1 and not state.focus_order_id
        meta = _done_meta(fact_sheet, started, needs_clarify_focus=needs_clarify)
        yield "gather_done", meta

    async def gather(
        self,
        db: AsyncSession,
        state: AgentState,
        plan: TurnPlan,
        history: list[dict],
        *,
        on_step: Callable | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        async for event, payload in self.gather_stream(db, state, plan, history, on_step=on_step):
            if event == "gather_done":
                meta = payload
        return meta

    async def _maybe_prefetch(self, db: AsyncSession, state: AgentState) -> None:
        if not settings.agent_prefetch_focus_bundle:
            return
        if not state.focus_order_id or state.prefetch_done:
            return
        if "query_focus_bundle" in state.executed_tools:
            return
        result = await self.executor.execute(
            db, state, "query_focus_bundle", {"order_id": state.focus_order_id}
        )
        self._post_tool(state, "query_focus_bundle", {"order_id": state.focus_order_id}, result)
        trace = AgentTraceStep(
            len(state.trace),
            "预取聚焦订单、券与门店（程序预取，供 ReAct 参考）",
            "query_focus_bundle",
            {"order_id": state.focus_order_id, "prefetch": True},
            observation=result,
        )
        state.trace.append(trace)
        state.tool_calls.append(
            {"name": "query_focus_bundle", "input": {"order_id": state.focus_order_id}, "result": result}
        )
        state.executed_tools.add("query_focus_bundle")

    @staticmethod
    def _post_tool(state: AgentState, action: str, action_input: dict, result: Any) -> None:
        state.executed_tools.add(action)
        if action == "query_focus_bundle" and isinstance(result, dict):
            state.prefetch_done = True
            state.focus_bundle_cache = normalize_focus_bundle(result)
        if action == "run_diagnosis" and isinstance(result, dict) and result.get("ok"):
            state.diagnosis_advisories.append(result)


def _step_payload(trace: AgentTraceStep, state: AgentState, **extra) -> dict:
    payload = {
        "step": trace.to_dict(),
        "focus_order_id": state.focus_order_id,
        "trace_length": len(state.trace),
        "diagnosis_script_count": len(state.diagnosis_advisories),
        "phase": "gather_react",
    }
    payload.update(extra)
    return payload


def _done_meta(fact_sheet: dict, started: float, *, needs_clarify_focus: bool) -> dict:
    return {
        "fact_sheet": fact_sheet,
        "gather_ms": int((time.perf_counter() - started) * 1000),
        "needs_clarify_focus": needs_clarify_focus,
    }


def _auto_gather_summary(state: AgentState) -> str:
    if state.gather_meta and state.gather_meta.get("gather_summary"):
        return str(state.gather_meta["gather_summary"])
    parts: list[str] = []
    for tc in state.tool_calls[-4:]:
        name = str(tc.get("name") or "")
        if name:
            parts.append(name)
    if state.diagnosis_advisories:
        adv = state.diagnosis_advisories[-1]
        parts.append(f"诊断 {adv.get('case_id') or adv.get('case_name') or '?'}")
    return "已执行：" + "、".join(parts) if parts else "Gather 步数用尽，请 Compose 基于已有 observation 作答"
