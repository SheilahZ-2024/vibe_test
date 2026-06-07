"""Gather 阶段程序回退 — Mock 或未配置 LLM 时按 task_type 执行固定工具链。"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_state import AgentState, AgentTraceStep
from app.services.agent_tools import AgentToolExecutor
from app.services.fact_sheet import build_fact_sheet
from app.services.intent import ACTIONABLE_INTENTS
from app.services.tool_payloads import normalize_focus_bundle
from app.services.turn_plan import TurnPlan


class EvidenceGatherer:
    def __init__(self, executor: AgentToolExecutor | None = None):
        self.executor = executor or AgentToolExecutor()

    async def gather(
        self,
        db: AsyncSession,
        state: AgentState,
        plan: TurnPlan,
        *,
        on_step=None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        orders = state.service_context.get("orders") or []

        if len(orders) > 1 and not state.focus_order_id and plan.task_type not in ("acknowledgment", "chitchat"):
            obs = await self.executor.execute(db, state, "list_orders", {})
            trace = AgentTraceStep(0, "多订单，先列出可选订单", "list_orders", {}, observation=obs)
            state.trace.append(trace)
            state.tool_calls.append({"name": "list_orders", "input": {}, "result": obs})
            if on_step:
                on_step(trace, state)

        if len(orders) == 1 and not state.focus_order_id:
            state.focus_order_id = str(orders[0]["id"])

        step_idx = len(state.trace)
        for tool_name in _mock_gather_tools(plan, state):
            if tool_name == "query_focus_bundle" and state.prefetch_done:
                continue
            action_input = self._tool_input(tool_name, state, plan)
            result = await self.executor.execute(db, state, tool_name, action_input)
            state.executed_tools.add(tool_name)

            if tool_name == "query_focus_bundle":
                state.prefetch_done = True
                if isinstance(result, dict):
                    state.focus_bundle_cache = normalize_focus_bundle(result)

            if tool_name == "run_diagnosis" and isinstance(result, dict):
                state.diagnosis_advisories.append(result)

            thought = _gather_thought(tool_name)
            trace = AgentTraceStep(step_idx, thought, tool_name, action_input, observation=result)
            state.trace.append(trace)
            state.tool_calls.append({"name": tool_name, "input": action_input, "result": result})
            if on_step:
                on_step(trace, state)
            step_idx += 1

        fact_sheet = build_fact_sheet(
            service_context=state.service_context,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            focus_order_id=state.focus_order_id,
        )

        return {
            "fact_sheet": fact_sheet,
            "gather_ms": int((time.perf_counter() - started) * 1000),
            "needs_clarify_focus": len(orders) > 1 and not state.focus_order_id,
        }

    @staticmethod
    def _tool_input(tool_name: str, state: AgentState, plan: TurnPlan) -> dict[str, Any]:
        if tool_name == "query_focus_bundle":
            oid = state.focus_order_id or plan.focus_order_id
            return {"order_id": oid} if oid else {}
        if tool_name == "run_diagnosis":
            intent = plan.route_intent
            if intent not in ACTIONABLE_INTENTS:
                msg = state.message or ""
                if any(k in msg for k in ("核销", "用不了")):
                    intent = "VoucherUnavailable"
                elif any(k in msg for k in ("退", "退款")):
                    intent = "CheckRefundEligibility"
                else:
                    intent = "CheckVoucherAvailability"
            return {"intent": intent, "order_id": state.focus_order_id}
        if tool_name == "search_knowledge":
            return {"query": state.message[:120], "limit": 3}
        return {}


def _mock_gather_tools(plan: TurnPlan, state: AgentState) -> list[str]:
    if plan.task_type == "acknowledgment":
        return []
    tools: list[str] = []
    if state.focus_order_id:
        tools.append("query_focus_bundle")
        if plan.task_type in ("eligibility", "follow_up", "complaint", "policy"):
            tools.append("run_diagnosis")
    if plan.task_type in ("policy", "complaint"):
        tools.append("search_knowledge")
    seen: set[str] = set()
    ordered: list[str] = []
    for name in tools:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _gather_thought(tool_name: str) -> str:
    labels = {
        "query_focus_bundle": "并行拉取聚焦订单、团购券与门店信息",
        "run_diagnosis": "对照诊断规则树核对资格与 Case",
        "search_knowledge": "检索平台政策与 FAQ",
        "list_orders": "列出用户订单供聚焦",
    }
    return labels.get(tool_name, f"执行 {tool_name}")
