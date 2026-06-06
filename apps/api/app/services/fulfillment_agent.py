"""Fulfillment ReAct Agent — 大模型主导的多步推理与工具调用。"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas.api import EdgeContextPacket
from app.services.agent_state import (
    AgentFinishDecision,
    AgentRunResult,
    AgentState,
    AgentTraceStep,
)
from app.services.agent_tools import AgentToolExecutor
from app.services.context import ServiceContextBuilder
from app.services.intent import ACTIONABLE_INTENTS, IntentClassifier, IntentResult
from app.services.llm import LLMService
from app.services.prompts import (
    build_final_reply_prompt,
    build_react_system_prompt,
    should_use_draft_directly,
)
from app.services.reply_polisher import ReplyPolisher
from app.services.thinking_narrative import (
    build_finish_thought_lines,
    build_knowledge_thought_lines,
    build_post_action_thought_lines,
    build_pre_action_thought_lines,
    build_pre_reply_thought_lines,
    build_session_opening_lines,
)
from app.services.sessions import SessionStore
from app.services.tool_catalog import TOOL_CATALOG


def _parse_json(raw: str) -> dict | None:
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


def _normalize_finish(data: dict) -> AgentFinishDecision:
    finish = data.get("finish") if isinstance(data.get("finish"), dict) else {}
    mode = str(finish.get("mode") or "reply").strip()
    if mode not in ("reply", "clarify"):
        mode = "clarify" if finish.get("safe_to_send") is False else "reply"
    suggested = finish.get("suggested_actions") or []
    clean_actions: list[dict[str, str]] = []
    if isinstance(suggested, list):
        for item in suggested[:4]:
            if isinstance(item, dict) and item.get("action_id") and item.get("title"):
                clean_actions.append({"action_id": str(item["action_id"]), "title": str(item["title"])})
    return AgentFinishDecision(
        mode=mode,
        draft_message=str(finish.get("draft_message") or ""),
        safe_to_send=bool(finish.get("safe_to_send", mode == "reply")),
        reasoning=str(finish.get("reasoning") or data.get("thought") or ""),
        suggested_actions=clean_actions,
        approved_case_id=str(finish.get("approved_case_id")) if finish.get("approved_case_id") else None,
        approved_case_name=str(finish.get("approved_case_name")) if finish.get("approved_case_name") else None,
    )


def _trim_history(history: list[dict], max_turns: int) -> list[dict]:
    if not history or max_turns <= 0:
        return []
    return history[-max_turns:]


def _emit_thinking(lines: list[str]) -> list[tuple[str, dict]]:
    return [("thinking", {"line": ln.strip()}) for ln in lines if ln and ln.strip()]


class FulfillmentAgent:
    def __init__(self):
        self.context_builder = ServiceContextBuilder()
        self.llm = LLMService()
        self.intent_classifier = IntentClassifier(self.llm)
        self.tool_executor = AgentToolExecutor()
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
        trimmed_history = _trim_history(history, settings.agent_history_max_turns)

        intent_result = await self.intent_classifier.classify(message, trimmed_history)
        knowledge_hits: list = []

        state = AgentState(
            session_id=session_id,
            user_id=user_id,
            message=message,
            service_context=service_context,
            intent_result=intent_result,
            knowledge_articles=knowledge_hits,
            focus_order_id=edge.focus_order_id,
        )

        yield "context_ready", {
            "intent": intent_result.route_intent,
            "intent_meta": self._intent_meta(intent_result),
            "focus_order_id": state.focus_order_id,
            "knowledge_titles": [a.title for a in knowledge_hits],
        }
        for kind, payload in _emit_thinking(
            build_session_opening_lines(intent_result, message, service_context)
        ):
            yield kind, payload
        for kind, payload in _emit_thinking(
            build_knowledge_thought_lines([a.title for a in knowledge_hits])
        ):
            yield kind, payload

        agent_result: AgentRunResult | None = None
        async for kind, payload in self._react_loop_stream(db, state, trimmed_history, on_step):
            if kind == "react_step":
                yield "react_step", payload
            elif kind == "complete":
                agent_result = payload

        if agent_result is None:
            raise RuntimeError("ReAct 循环未返回结果")

        finish_dict = agent_result.finish.to_dict()
        raw_source = "draft_direct" if should_use_draft_directly(finish_dict) else "llm_generate"
        raw_text = await self._resolve_raw_reply(
            state,
            finish_dict,
            trimmed_history,
            message,
            use_draft=(raw_source == "draft_direct"),
        )
        tone_polished = self.polisher.should_polish(raw_text, mode=str(finish_dict.get("mode") or "reply"))
        agent_result.reply_source = f"{raw_source}+tone" if tone_polished else raw_source

        for kind, payload in _emit_thinking(build_pre_reply_thought_lines(tone_polish=tone_polished)):
            yield kind, payload

        yield "agent", {
            "intent": intent_result.route_intent,
            "intent_meta": self._intent_meta(intent_result),
            "focus_order_id": agent_result.focus_order_id,
            "trace": [t.to_dict() for t in agent_result.trace],
            "finish": agent_result.finish.to_dict(),
            "knowledge_titles": agent_result.knowledge_titles,
            "tool_count": len(agent_result.tool_calls),
            "pending_confirmations": [p.to_dict() for p in agent_result.pending_confirmations],
            "reply_source": agent_result.reply_source,
        }

        full: list[str] = []
        stream = (
            self.polisher.polish_stream(
                raw_text,
                user_message=message,
                mode=str(finish_dict.get("mode") or "reply"),
            )
            if tone_polished
            else self.llm.stream_text(raw_text)
        )
        async for chunk in stream:
            full.append(chunk)
            yield "token", {"text": chunk}

        agent_result.finish.draft_message = "".join(full)
        yield "result", agent_result

    async def _resolve_raw_reply(
        self,
        state: AgentState,
        finish: dict,
        history: list[dict],
        message: str,
        *,
        use_draft: bool,
    ) -> str:
        if use_draft:
            return (finish.get("draft_message") or "").strip()

        final_prompt = build_final_reply_prompt(state, finish)
        generated = await self.llm.complete_with_history(
            final_prompt,
            history,
            message,
            temperature=settings.llm_temperature,
            max_tokens=min(settings.llm_max_tokens, 900),
        )
        if generated and generated.strip():
            return generated.strip()
        return (finish.get("draft_message") or "").strip()

    async def _react_loop_stream(
        self,
        db: AsyncSession,
        state: AgentState,
        history: list[dict],
        on_step: Callable | None,
    ) -> AsyncIterator[tuple[str, Any]]:
        if self.llm.use_mock:
            async for kind, payload in self._mock_react_stream(db, state, on_step):
                yield kind, payload
            return

        finish: AgentFinishDecision | None = None
        for step_idx in range(1, settings.agent_max_steps + 1):
            if step_idx == 1:
                yield "thinking", {"line": "进入分步推理：先拿系统里的真实数据，再决定怎么帮您"}
            system = build_react_system_prompt(state, history, step_idx=step_idx)
            user_block = f"用户最新：{state.message}\n\n请输出下一步 JSON。"
            raw = await self.llm.complete_with_history(
                system,
                history if step_idx == 1 else [],
                user_block,
                temperature=settings.agent_react_temperature,
                max_tokens=settings.agent_react_max_tokens,
            )
            if not raw:
                finish = self._fallback_finish(state, "LLM 无响应，进入澄清")
                break

            data = _parse_json(raw)
            if not data:
                finish = self._fallback_finish(state, "JSON 解析失败")
                break

            thought = str(data.get("thought") or "")
            action = str(data.get("action") or "finish").strip()
            action_input = data.get("action_input") if isinstance(data.get("action_input"), dict) else {}
            if data.get("focus_order_id"):
                state.focus_order_id = str(data["focus_order_id"])

            if action == "finish":
                finish = _normalize_finish(data)
                trace = AgentTraceStep(step_idx, thought, action, action_input, observation="finish")
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "react_step", self._react_step_payload(trace, state)
                for kind, payload in _emit_thinking(
                    build_finish_thought_lines(
                        thought=thought,
                        finish=finish.to_dict(),
                        step_idx=step_idx,
                    )
                ):
                    yield kind, payload
                break

            if action not in TOOL_CATALOG:
                trace = AgentTraceStep(
                    step_idx,
                    thought,
                    action,
                    action_input,
                    observation=None,
                    error=f"未知工具 {action}",
                )
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "react_step", self._react_step_payload(trace, state)
                continue

            for kind, payload in _emit_thinking(
                build_pre_action_thought_lines(
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    step_idx=step_idx,
                )
            ):
                yield kind, payload

            result = await self.tool_executor.execute(db, state, action, action_input)
            state.tool_calls.append({"name": action, "input": action_input, "result": result})
            trace = AgentTraceStep(step_idx, thought, action, action_input, observation=result)
            state.trace.append(trace)
            if on_step:
                on_step(trace, state)
            yield "react_step", self._react_step_payload(trace, state)
            for kind, payload in _emit_thinking(
                build_post_action_thought_lines(
                    thought=thought,
                    action=action,
                    observation=result,
                    service_context=state.service_context,
                    step_idx=step_idx,
                )
            ):
                yield kind, payload

        if finish is None:
            finish = self._fallback_finish(state, "达到最大 ReAct 步数，请基于已有信息回复或澄清")

        yield "complete", AgentRunResult(
            intent_result=state.intent_result,
            focus_order_id=state.focus_order_id,
            finish=finish,
            trace=state.trace,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            knowledge_titles=[a.title for a in state.knowledge_articles],
            pending_confirmations=list(state.pending_confirmations),
        )

    async def _mock_react_stream(
        self,
        db: AsyncSession,
        state: AgentState,
        on_step: Callable | None,
    ) -> AsyncIterator[tuple[str, Any]]:
        result = await self._mock_react(db, state, on_step)
        for trace in result.trace:
            yield "react_step", self._react_step_payload(trace, state)
            if trace.action == "finish":
                lines = build_finish_thought_lines(
                    thought=trace.thought,
                    finish=result.finish.to_dict(),
                    step_idx=trace.step,
                )
            else:
                pre = build_pre_action_thought_lines(
                    thought=trace.thought,
                    action=trace.action,
                    action_input=trace.action_input,
                    step_idx=trace.step,
                )
                post = build_post_action_thought_lines(
                    thought=trace.thought,
                    action=trace.action,
                    observation=trace.observation,
                    service_context=state.service_context,
                    step_idx=trace.step,
                )
                lines = pre + post
            for kind, payload in _emit_thinking(lines):
                yield kind, payload
        yield "complete", result

    @staticmethod
    def _react_step_payload(trace: AgentTraceStep, state: AgentState) -> dict:
        return {
            "step": trace.to_dict(),
            "focus_order_id": state.focus_order_id,
            "trace_length": len(state.trace),
            "diagnosis_script_count": len(state.diagnosis_advisories),
            "pending_confirmations": [p.to_dict() for p in state.pending_confirmations],
        }

    async def _mock_react(
        self,
        db: AsyncSession,
        state: AgentState,
        on_step: Callable | None,
    ) -> AgentRunResult:
        intent = state.intent_result
        orders = state.service_context.get("orders") or []
        msg = state.message

        if intent.route_category == "chitchat":
            finish = AgentFinishDecision(
                mode="reply",
                draft_message="",
                safe_to_send=True,
                reasoning="闲聊",
            )
            return self._build_result(state, finish)

        if intent.route_category == "unconfigured":
            finish = AgentFinishDecision(
                mode="clarify",
                draft_message="这个问题可能超出当前履约服务范围，你可以描述订单/核销/退款相关问题，或说「转人工」。",
                safe_to_send=True,
                reasoning="未配置意图",
            )
            return self._build_result(state, finish)

        if len(orders) > 1 and not state.focus_order_id:
            titles = "、".join(f"「{o.get('title')}」" for o in orders[:4])
            step = AgentTraceStep(
                1,
                "多订单未聚焦，需先确认",
                "list_orders",
                {},
                observation=await self.tool_executor.execute(db, state, "list_orders", {}),
            )
            state.trace.append(step)
            if on_step:
                on_step(step, state)
            finish = AgentFinishDecision(
                mode="clarify",
                draft_message=f"我看到你有多笔订单（{titles}等），你想处理的是哪一笔？可以在上方点选，或直接告诉我商品名。",
                safe_to_send=True,
                reasoning="多订单未聚焦",
            )
            return self._build_result(state, finish, focus_override=None)

        if len(orders) == 1 and not state.focus_order_id:
            state.focus_order_id = str(orders[0]["id"])

        step_n = 1
        list_obs = await self.tool_executor.execute(db, state, "list_orders", {})
        step = AgentTraceStep(step_n, "确认订单列表", "list_orders", {}, observation=list_obs)
        state.trace.append(step)
        state.tool_calls.append({"name": "list_orders", "input": {}, "result": list_obs})
        if on_step:
            on_step(step, state)
        step_n += 1

        if state.focus_order_id:
            qo = await self.tool_executor.execute(
                db, state, "query_order", {"order_id": state.focus_order_id}
            )
            step = AgentTraceStep(step_n, "查询聚焦订单", "query_order", {"order_id": state.focus_order_id}, observation=qo)
            state.trace.append(step)
            state.tool_calls.append({"name": "query_order", "input": {"order_id": state.focus_order_id}, "result": qo})
            if on_step:
                on_step(step, state)
            step_n += 1

            qv = await self.tool_executor.execute(
                db, state, "query_voucher", {"order_id": state.focus_order_id}
            )
            step = AgentTraceStep(step_n, "查询关联券", "query_voucher", {"order_id": state.focus_order_id}, observation=qv)
            state.trace.append(step)
            state.tool_calls.append({"name": "query_voucher", "input": {"order_id": state.focus_order_id}, "result": qv})
            if on_step:
                on_step(step, state)
            step_n += 1

        diag_intent = intent.route_intent if intent.route_intent in ACTIONABLE_INTENTS else "QueryOrder"
        if any(k in msg for k in ("核销", "扫不出", "用不了", "老板不给", "不让我核销")):
            diag_intent = "VoucherUnavailable"
        elif any(k in msg for k in ("退款", "退掉")):
            diag_intent = "RefundRequest"

        if state.focus_order_id and diag_intent not in ("clarify", "chitchat", "HumanTransfer", "QueryTicket"):
            dx = await self.tool_executor.execute(
                db,
                state,
                "run_diagnosis",
                {"intent": diag_intent, "order_id": state.focus_order_id},
            )
            step = AgentTraceStep(
                step_n,
                "运行诊断树供参考",
                "run_diagnosis",
                {"intent": diag_intent, "order_id": state.focus_order_id},
                observation=dx,
            )
            state.trace.append(step)
            state.tool_calls.append(
                {
                    "name": "run_diagnosis",
                    "input": {"intent": diag_intent, "order_id": state.focus_order_id},
                    "result": dx,
                }
            )
            if on_step:
                on_step(step, state)

        if intent.needs_clarify or intent.route_intent == "clarify":
            finish = AgentFinishDecision(
                mode="clarify",
                draft_message="",
                safe_to_send=True,
                reasoning="意图需澄清",
            )
            return self._build_result(state, finish)

        latest = state.diagnosis_advisories[-1] if state.diagnosis_advisories else {}
        suggested = [
            {"action_id": a.get("action_id"), "title": a.get("title")}
            for a in (latest.get("solution") or [])[:3]
            if a.get("action_id") and a.get("title")
        ]
        finish = AgentFinishDecision(
            mode="reply",
            draft_message="",
            safe_to_send=True,
            reasoning="mock 模式基于工具与诊断参考回复",
            suggested_actions=suggested,
            approved_case_id=latest.get("case_id"),
            approved_case_name=latest.get("case_name"),
        )
        return self._build_result(state, finish)

    @staticmethod
    def _build_result(
        state: AgentState,
        finish: AgentFinishDecision,
        focus_override: str | None | object = ...,
    ) -> AgentRunResult:
        focus = state.focus_order_id if focus_override is ... else focus_override
        return AgentRunResult(
            intent_result=state.intent_result,
            focus_order_id=focus,
            finish=finish,
            trace=state.trace,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            knowledge_titles=[a.title for a in state.knowledge_articles],
            pending_confirmations=list(state.pending_confirmations),
        )

    @staticmethod
    def _fallback_finish(state: AgentState, reason: str) -> AgentFinishDecision:
        if len(state.service_context.get("orders") or []) > 1 and not state.focus_order_id:
            return AgentFinishDecision(
                mode="clarify",
                draft_message="我需要先确认您要处理哪一笔订单，可以告诉我商品名或在列表中点选。",
                safe_to_send=True,
                reasoning=reason,
            )
        return AgentFinishDecision(
            mode="reply",
            draft_message="",
            safe_to_send=bool(state.tool_calls),
            reasoning=reason,
        )

    @staticmethod
    def _intent_meta(intent_result: IntentResult) -> dict:
        return {
            "raw_intent": intent_result.raw_intent,
            "route_intent": intent_result.route_intent,
            "route_category": intent_result.route_category,
            "confidence": intent_result.confidence,
            "needs_clarify": intent_result.needs_clarify,
            "source": intent_result.source,
            "reasoning": intent_result.reasoning,
            "alternatives": intent_result.alternatives,
        }
