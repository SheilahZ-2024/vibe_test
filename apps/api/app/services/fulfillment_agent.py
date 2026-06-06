"""Fulfillment ReAct Agent — 大模型主导的多步推理与工具调用。"""

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
    AgentTraceStep,
)
from app.services.agent_tools import AgentToolExecutor
from app.services.conversation_memory import format_memory_block
from app.services.fact_sheet import (
    build_fact_sheet,
    format_fact_sheet_block,
    reservation_reply_constraints,
)
from app.services.context import ServiceContextBuilder
from app.services.intent import ACTIONABLE_INTENTS, IntentClassifier, IntentResult
from app.services.llm import LLMService
from app.services.prompts import (
    build_final_reply_prompt,
    build_react_system_prompt,
    should_use_draft_directly,
)
from app.services.reply_polisher import ReplyPolisher
from app.services.sessions import SessionStore
from app.services.thinking_narrative import (
    build_finish_thought_lines,
    build_knowledge_thought_lines,
    build_post_action_thought_lines,
    build_pre_action_thought_lines,
    build_pre_reply_thought_lines,
    build_react_continue_lines,
    build_react_loop_bridge_lines,
    build_react_reconsider_lines,
    build_fast_turn_thought_lines,
    build_session_opening_lines,
)
from app.services.react_json import accumulate_stream_json, try_parse_react_json
from app.services.tool_catalog import TOOL_CATALOG

logger = logging.getLogger(__name__)

FAST_TURN_SYSTEM = """你是抖音生活服务 AI 履约管家。当前是**同一会话里的接话**。

你会收到会话记忆（上一轮已查到的订单/券/门店事实）和最近对话。
要求：
- 理解省略、指代（「那」「这个」「然后呢」），直接回答追问
- 优先用会话记忆与已核实事实；怎么预约时若有门店电话须告知，禁止编造
- 不要重复完整排查，不要重新长篇寒暄
- 口语化，一般 2-5 句话"""

ACK_TURN_SYSTEM = """你是抖音生活服务 AI 履约管家。用户在致谢或表示收到（谢谢、好的、明白了等）。

要求：
- 1-2 句自然承接，温暖简练
- 可轻问是否还有核销/退款/订单问题
- 不要重复上一段长回复"""


_PROCEDURAL_CONT_MARKERS = (
    "怎么预约",
    "如何预约",
    "预约方式",
    "在哪约",
    "怎么约",
    "电话",
    "地址",
    "营业时间",
    "几点开",
    "怎么退",
    "如何退",
    "退款呢",
)


def _is_procedural_continuation(message: str) -> bool:
    text = (message or "").strip()
    return any(m in text for m in _PROCEDURAL_CONT_MARKERS)


def _parse_json(raw: str) -> dict | None:
    return try_parse_react_json(raw)


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


async def _stream_thinking_lines(lines: list[str]) -> AsyncIterator[tuple[str, dict]]:
    """逐字推送思考叙述；前端再做节奏揭示，此处单字粒度避免整段蹦出。"""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        async for ch in LLMService.stream_text(text):
            yield "thinking_token", {"text": ch}
        yield "thinking_token", {"text": "\n"}


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
        agent_ctx = await store.get_agent_context(session_id) or {}
        knowledge_hits: list = []

        intent_result = await self.intent_classifier.classify(
            message,
            trimmed_history,
            agent_ctx if agent_ctx else None,
        )

        focus_order_id = edge.focus_order_id
        if intent_result.turn_mode in ("continuation", "acknowledgment") and agent_ctx.get("focus_order_id"):
            focus_order_id = str(agent_ctx["focus_order_id"])

        state = AgentState(
            session_id=session_id,
            user_id=user_id,
            message=message,
            service_context=service_context,
            intent_result=intent_result,
            knowledge_articles=knowledge_hits,
            focus_order_id=focus_order_id,
            prior_agent_ctx=agent_ctx if agent_ctx else None,
        )

        yield "context_ready", {
            "intent": intent_result.route_intent,
            "intent_meta": self._intent_meta(intent_result),
            "focus_order_id": state.focus_order_id,
            "knowledge_titles": [a.title for a in knowledge_hits],
        }

        use_fast_turn = (
            settings.agent_fast_turn_enabled
            and bool(agent_ctx)
            and bool(trimmed_history)
            and (
                intent_result.turn_mode == "acknowledgment"
                or (
                    intent_result.turn_mode == "continuation"
                    and _is_procedural_continuation(message)
                )
            )
        )

        agent_result: AgentRunResult | None = None
        if use_fast_turn:
            async for kind, payload in self._fast_turn_stream(state, trimmed_history, agent_ctx):
                if kind == "complete":
                    agent_result = payload
                else:
                    yield kind, payload
        else:
            if intent_result.turn_mode == "continuation":
                async for kind, payload in _stream_thinking_lines(
                    build_fast_turn_thought_lines("continuation")
                ):
                    yield kind, payload
            else:
                async for kind, payload in _stream_thinking_lines(
                    build_session_opening_lines(intent_result, message, service_context)
                ):
                    yield kind, payload
            async for kind, payload in _stream_thinking_lines(
                build_knowledge_thought_lines([a.title for a in knowledge_hits])
            ):
                yield kind, payload

            async for kind, payload in self._react_loop_stream(db, state, trimmed_history, on_step):
                if kind == "react_step":
                    yield "react_step", payload
                elif kind in ("thinking", "thinking_token"):
                    yield kind, payload
                elif kind == "complete":
                    agent_result = payload

        if agent_result is None:
            raise RuntimeError("Agent 未返回结果")

        finish_dict = agent_result.finish.to_dict()
        fact_sheet = build_fact_sheet(
            service_context=state.service_context,
            tool_calls=agent_result.tool_calls,
            diagnosis_advisories=agent_result.diagnosis_advisories,
            focus_order_id=agent_result.focus_order_id,
        )
        fact_block = format_fact_sheet_block(fact_sheet)
        fact_constraints = reservation_reply_constraints(fact_sheet)

        if use_fast_turn:
            raw_text = (finish_dict.get("draft_message") or "").strip()
            raw_source = "fast_turn"
        else:
            raw_source = "draft_direct" if should_use_draft_directly(finish_dict) else "llm_generate"
            async for kind, payload in _stream_thinking_lines(
                ["查得差不多了，正在整理成正式回复…"]
            ):
                yield kind, payload
            raw_text = await self._resolve_raw_reply(
                state,
                finish_dict,
                trimmed_history,
                message,
                use_draft=(raw_source == "draft_direct"),
                fact_block=fact_block,
            )

        tone_polished = self.polisher.should_polish(raw_text, mode=str(finish_dict.get("mode") or "reply"))
        if use_fast_turn:
            agent_result.reply_source = "fast_turn+tone" if tone_polished else "fast_turn"
        else:
            agent_result.reply_source = f"{raw_source}+tone" if tone_polished else raw_source

        async for kind, payload in _stream_thinking_lines(
            build_pre_reply_thought_lines(tone_polish=tone_polished)
        ):
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
            "fact_sheet": fact_sheet,
        }

        full: list[str] = []
        stream = (
            self.polisher.polish_stream(
                raw_text,
                user_message=message,
                mode=str(finish_dict.get("mode") or "reply"),
                fact_constraints=fact_constraints,
            )
            if tone_polished
            else self.llm.stream_text(raw_text)
        )
        async for chunk in stream:
            full.append(chunk)
            yield "token", {"text": chunk}

        agent_result.finish.draft_message = "".join(full)
        yield "result", agent_result

    async def _fast_turn_stream(
        self,
        state: AgentState,
        history: list[dict],
        agent_ctx: dict,
    ) -> AsyncIterator[tuple[str, Any]]:
        """接话/致谢快捷路径：复用会话记忆 + 单轮 LLM，跳过 ReAct。"""
        turn_mode = state.intent_result.turn_mode
        async for kind, payload in _stream_thinking_lines(build_fast_turn_thought_lines(turn_mode)):
            yield kind, payload

        system = ACK_TURN_SYSTEM if turn_mode == "acknowledgment" else FAST_TURN_SYSTEM
        facts = build_fact_sheet(
            service_context=state.service_context,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            focus_order_id=state.focus_order_id,
        )
        fact_block = format_fact_sheet_block(facts)
        user_block = f"{format_memory_block(agent_ctx)}\n\n── 已核实事实 ──\n{fact_block}\n\n用户最新：{state.message}"

        parts: list[str] = []
        if self.llm.use_mock:
            parts.append("不客气～还有什么订单或券的问题，随时跟我说。" if turn_mode == "acknowledgment" else "接着刚才的说，您问的我这边基于已查到的信息补充如下。")
        else:
            async for chunk in self.llm.stream_reply(
                system,
                history,
                user_block,
                temperature=settings.llm_temperature,
                max_tokens=min(settings.llm_max_tokens, 480),
            ):
                parts.append(chunk)

        raw_text = "".join(parts).strip() or "好的，有需要随时告诉我。"
        trace = AgentTraceStep(
            1,
            "接话轮次：复用会话记忆",
            "fast_turn",
            {"turn_mode": turn_mode},
            observation={"mode": turn_mode, "reused_context": True},
        )
        state.trace.append(trace)
        finish = AgentFinishDecision(
            mode="reply",
            draft_message=raw_text,
            safe_to_send=True,
            reasoning=f"接话快捷回复 ({turn_mode})",
        )
        yield "complete", self._build_result(state, finish)

    async def _resolve_raw_reply(
        self,
        state: AgentState,
        finish: dict,
        history: list[dict],
        message: str,
        *,
        use_draft: bool,
        fact_block: str = "",
    ) -> str:
        if use_draft:
            return (finish.get("draft_message") or "").strip()

        final_prompt = build_final_reply_prompt(state, finish, fact_block=fact_block)
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

        await self._prefetch_focus_bundle(db, state, on_step)
        if state.prefetch_done and state.trace:
            prefetch = state.trace[0]
            async for kind, payload in _stream_thinking_lines(
                ["先把聚焦这笔订单的详情、团购券和门店信息并行拉齐。"]
            ):
                yield kind, payload
            yield "react_step", self._react_step_payload(
                prefetch,
                state,
                tool_latency_ms=0,
                step_latency_ms=0,
                prefetch=True,
            )

        finish: AgentFinishDecision | None = None
        for step_idx in range(1, settings.agent_max_steps + 1):
            step_started = time.perf_counter()
            if step_idx == 1:
                async for kind, payload in _stream_thinking_lines(
                    ["进入分步推理：先从系统里拉真实订单和券数据，再决定怎么帮您。"]
                ):
                    yield kind, payload
            system = build_react_system_prompt(state, history, step_idx=step_idx)
            user_block = f"用户最新：{state.message}\n\n请输出下一步 JSON。"
            raw, data, llm_latency_ms, parse_ms = await self._react_llm_step(
                system,
                history if step_idx == 1 else [],
                user_block,
            )
            if not raw:
                finish = self._fallback_finish(state, "LLM 无响应，进入澄清")
                break

            if data is None:
                data = _parse_json(raw)
            if not data:
                finish = self._fallback_finish(state, "JSON 解析失败")
                break

            thought = str(data.get("thought") or "")
            action = str(data.get("action") or "finish").strip()
            action_input = data.get("action_input") if isinstance(data.get("action_input"), dict) else {}
            if data.get("focus_order_id"):
                state.focus_order_id = str(data["focus_order_id"])

            if step_idx > 1 and state.trace:
                async for kind, payload in _stream_thinking_lines(
                    build_react_loop_bridge_lines(
                        step_idx=step_idx,
                        prev_trace=state.trace[-1].to_dict(),
                        thought=thought,
                    )
                ):
                    yield kind, payload

            if action == "finish":
                finish = _normalize_finish(data)
                trace = AgentTraceStep(step_idx, thought, action, action_input, observation="finish")
                state.trace.append(trace)
                if on_step:
                    on_step(trace, state)
                yield "react_step", self._react_step_payload(
                    trace,
                    state,
                    llm_latency_ms=llm_latency_ms,
                    json_parse_ms=parse_ms,
                    step_latency_ms=int((time.perf_counter() - step_started) * 1000),
                )
                async for kind, payload in _stream_thinking_lines(
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
                yield "react_step", self._react_step_payload(
                    trace,
                    state,
                    llm_latency_ms=llm_latency_ms,
                    json_parse_ms=parse_ms,
                    step_latency_ms=int((time.perf_counter() - step_started) * 1000),
                )
                async for kind, payload in _stream_thinking_lines(
                    build_react_reconsider_lines(reason="刚才那一步的动作名我这边识别不了")
                ):
                    yield kind, payload
                continue

            tool_started = time.perf_counter()
            async for kind, payload in _stream_thinking_lines(
                build_pre_action_thought_lines(
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    step_idx=step_idx,
                )
            ):
                yield kind, payload

            result = await self.tool_executor.execute(db, state, action, action_input)
            state.executed_tools.add(action)
            state.tool_calls.append({"name": action, "input": action_input, "result": result})
            trace = AgentTraceStep(step_idx, thought, action, action_input, observation=result)
            state.trace.append(trace)
            if on_step:
                on_step(trace, state)
            tool_latency_ms = int((time.perf_counter() - tool_started) * 1000)
            yield "react_step", self._react_step_payload(
                trace,
                state,
                llm_latency_ms=llm_latency_ms,
                json_parse_ms=parse_ms,
                tool_latency_ms=tool_latency_ms,
                step_latency_ms=int((time.perf_counter() - step_started) * 1000),
            )
            async for kind, payload in _stream_thinking_lines(
                build_post_action_thought_lines(
                    thought=thought,
                    action=action,
                    observation=result,
                    service_context=state.service_context,
                    step_idx=step_idx,
                )
            ):
                yield kind, payload
            async for kind, payload in _stream_thinking_lines(
                build_react_continue_lines(
                    thought=thought,
                    step_idx=step_idx,
                    max_steps=settings.agent_max_steps,
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

    async def _react_llm_step(
        self,
        system: str,
        history: list[dict],
        user_block: str,
    ) -> tuple[str | None, dict | None, int, int | None]:
        """ReAct 单步 LLM：可选流式 JSON 解析。"""
        started = time.perf_counter()
        if settings.agent_react_stream_json:
            stream = self.llm.stream_reply(
                system,
                history,
                user_block,
                temperature=settings.agent_react_temperature,
                max_tokens=settings.agent_react_max_tokens,
            )
            raw, parsed, stream_parse_ms = await accumulate_stream_json(stream)
            llm_ms = int((time.perf_counter() - started) * 1000)
            return (raw or None), parsed, llm_ms, stream_parse_ms

        raw = await self.llm.complete_with_history(
            system,
            history,
            user_block,
            temperature=settings.agent_react_temperature,
            max_tokens=settings.agent_react_max_tokens,
        )
        llm_ms = int((time.perf_counter() - started) * 1000)
        return raw, _parse_json(raw) if raw else None, llm_ms, None

    async def _prefetch_focus_bundle(
        self,
        db: AsyncSession,
        state: AgentState,
        on_step: Callable | None,
    ) -> None:
        """工程层预取：有聚焦订单且意图可办时，ReAct 前先并行拉 order+voucher+store。"""
        if not settings.agent_prefetch_focus_bundle or state.prefetch_done:
            return
        intent = state.intent_result
        if intent.route_category in ("chitchat", "unconfigured"):
            return
        orders = state.service_context.get("orders") or []
        if len(orders) > 1 and not state.focus_order_id:
            return
        if len(orders) == 1 and not state.focus_order_id:
            state.focus_order_id = str(orders[0]["id"])
        if not state.focus_order_id:
            return

        result = await self.tool_executor.execute(
            db,
            state,
            "query_focus_bundle",
            {"order_id": state.focus_order_id},
        )
        state.prefetch_done = True
        state.executed_tools.add("query_focus_bundle")
        state.tool_calls.append(
            {
                "name": "query_focus_bundle",
                "input": {"order_id": state.focus_order_id},
                "result": result,
                "prefetch": True,
            }
        )
        trace = AgentTraceStep(
            0,
            "预取聚焦订单/券/门店（并行）",
            "query_focus_bundle",
            {"order_id": state.focus_order_id, "prefetch": True},
            observation=result,
        )
        state.trace.append(trace)
        if on_step:
            on_step(trace, state)

        await self._auto_diagnosis_for_reservation(db, state, on_step)

    async def _auto_diagnosis_for_reservation(
        self,
        db: AsyncSession,
        state: AgentState,
        on_step: Callable | None,
    ) -> None:
        """预约/核销类问题：预取后自动跑诊断树，避免 LLM 跳过 run_diagnosis。"""
        if "run_diagnosis" in state.executed_tools or state.diagnosis_advisories:
            return
        msg = state.message or ""
        if not any(k in msg for k in ("预约", "核销", "没约", "未约", "能不能用", "用不了")):
            return
        facts = build_fact_sheet(
            service_context=state.service_context,
            tool_calls=state.tool_calls,
            diagnosis_advisories=state.diagnosis_advisories,
            focus_order_id=state.focus_order_id,
        )
        if not facts.get("needs_reservation") and not any(k in msg for k in ("预约", "没约", "未约")):
            return
        if not state.focus_order_id:
            return
        intent = state.intent_result.route_intent
        if intent in ("clarify", "chitchat", "unconfigured"):
            diag_intent = "VoucherUnavailable"
        elif intent not in ACTIONABLE_INTENTS:
            diag_intent = "VoucherUnavailable"
        else:
            diag_intent = intent
        dx = await self.tool_executor.execute(
            db,
            state,
            "run_diagnosis",
            {"intent": diag_intent, "order_id": state.focus_order_id},
        )
        step_n = len(state.trace)
        trace = AgentTraceStep(
            step_n,
            "预约/核销问题，自动对照诊断规则",
            "run_diagnosis",
            {"intent": diag_intent, "order_id": state.focus_order_id, "auto": True},
            observation=dx,
        )
        state.trace.append(trace)
        state.tool_calls.append(
            {
                "name": "run_diagnosis",
                "input": {"intent": diag_intent, "order_id": state.focus_order_id, "auto": True},
                "result": dx,
            }
        )
        if on_step:
            on_step(trace, state)

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
            async for kind, payload in _stream_thinking_lines(lines):
                yield kind, payload
        yield "complete", result

    @staticmethod
    def _react_step_payload(trace: AgentTraceStep, state: AgentState, **timing: int | bool) -> dict:
        payload = {
            "step": trace.to_dict(),
            "focus_order_id": state.focus_order_id,
            "trace_length": len(state.trace),
            "diagnosis_script_count": len(state.diagnosis_advisories),
            "pending_confirmations": [p.to_dict() for p in state.pending_confirmations],
        }
        timing_ms = {k: v for k, v in timing.items() if isinstance(v, int)}
        if timing.get("prefetch"):
            payload["prefetch"] = True
        if timing_ms:
            payload["timing_ms"] = timing_ms
        return payload

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
        state.executed_tools.add("list_orders")
        step = AgentTraceStep(step_n, "确认订单列表", "list_orders", {}, observation=list_obs)
        state.trace.append(step)
        state.tool_calls.append({"name": "list_orders", "input": {}, "result": list_obs})
        if on_step:
            on_step(step, state)
        step_n += 1

        if state.focus_order_id:
            bundle = await self.tool_executor.execute(
                db, state, "query_focus_bundle", {"order_id": state.focus_order_id}
            )
            step = AgentTraceStep(
                step_n,
                "并行查询订单/券/门店",
                "query_focus_bundle",
                {"order_id": state.focus_order_id},
                observation=bundle,
            )
            state.trace.append(step)
            state.tool_calls.append(
                {"name": "query_focus_bundle", "input": {"order_id": state.focus_order_id}, "result": bundle}
            )
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
            "turn_mode": intent_result.turn_mode,
        }
