"""对话入口 — 将 HTTP/SSE 请求委托给 FulfillmentAgent（ReAct），不再维护固定流水线。"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ConversationEvent
from app.repositories.life_service import OperationLogRepository
from app.schemas.api import ChatRequest, EdgeContextPacket
from app.services.context import ServiceContextBuilder
from app.services.error_recovery import ErrorRecoveryService
from app.services.fulfillment_agent import FulfillmentAgent
from app.services.llm import LLMService
from app.services.sessions import SessionStore


class ChatOrchestrator:
    """命名保留以兼容 chat 路由；职责仅为会话 I/O + 日志，业务决策全部由 FulfillmentAgent 完成。"""

    def __init__(self):
        self.agent = FulfillmentAgent()
        self.context_builder = ServiceContextBuilder()
        self.operation_logs = OperationLogRepository()
        self.llm = LLMService()
        self.recovery = ErrorRecoveryService(self.llm)

    async def run_stream(
        self,
        db: AsyncSession,
        store: SessionStore,
        body: ChatRequest,
    ) -> AsyncIterator[tuple[str, dict]]:
        started = time.perf_counter()
        edge = body.edge_context or EdgeContextPacket()
        user_id = edge.user_id
        if not await self.context_builder.users.get(db, user_id):
            raise ValueError(f"用户不存在: {user_id}")

        session_id = body.session_id or await store.create(user_id)
        await store.refresh(session_id, user_id)
        history = await store.get_messages(session_id)

        pipeline: dict = {"steps": []}

        def step(name: str, detail: str = "", status: str = "done") -> None:
            pipeline["steps"].append({"name": name, "status": status, "detail": detail})

        service_context = await self.context_builder.build(db, edge, user_id)
        step("service_context", f"{len(service_context['orders'])} orders, focus={edge.focus_order_id or 'none'}")

        agent_trace: list[dict] = []
        intent = "clarify"
        intent_meta: dict = {}
        focus_order_id = edge.focus_order_id
        tool_calls: list[dict] = []
        workflow_payload: dict | None = None
        agent_finish: dict = {}

        def on_react_step(trace_step, state) -> None:
            agent_trace.append(trace_step.to_dict())

        def pipeline_payload(case: dict | None = None) -> dict:
            return {
                "session_id": session_id,
                "intent": intent,
                "intent_meta": intent_meta,
                "pipeline": pipeline,
                "service_cards": self._cards(service_context),
                "case": case,
                "focus_order_id": focus_order_id,
                "agent_trace": agent_trace,
            }

        yield "pipeline", pipeline_payload()

        agent_result = None
        try:
            async for event, payload in self.agent.run_stream(
                db,
                store,
                session_id=session_id,
                user_id=user_id,
                message=body.message,
                edge=edge,
                history=history,
                service_context=service_context,
                on_step=on_react_step,
            ):
                if event == "context_ready":
                    intent = payload.get("intent", intent)
                    intent_meta = payload.get("intent_meta") or {}
                    focus_order_id = payload.get("focus_order_id") or focus_order_id
                    step(
                        "intent_detect",
                        f"[{intent_meta.get('route_category', '?')}] {intent} "
                        f"({int((intent_meta.get('confidence') or 0) * 100)}%, agent)",
                    )
                    titles = payload.get("knowledge_titles") or []
                    step("knowledge_search", ", ".join(titles[:3]) if titles else "按需 search_knowledge")
                    yield "pipeline", pipeline_payload()
                elif event == "react_step":
                    trace_step = payload.get("step") or {}
                    focus_order_id = payload.get("focus_order_id") or focus_order_id
                    action = trace_step.get("action", "?")
                    thought = str(trace_step.get("thought") or "")[:80]
                    step("agent_react", f"#{trace_step.get('step', '?')} {action}: {thought}")
                    yield "pipeline", pipeline_payload()
                elif event == "thinking":
                    yield "thinking", payload
                elif event == "agent":
                    intent = payload.get("intent", intent)
                    intent_meta = payload.get("intent_meta") or {}
                    focus_order_id = payload.get("focus_order_id") or focus_order_id
                    agent_finish = payload.get("finish") or {}
                    if agent_finish.get("mode") == "clarify":
                        step("agent_decision", "clarify — 大模型判断需先澄清")
                    else:
                        step("agent_decision", f"reply — safe={agent_finish.get('safe_to_send', True)}")
                    step("tool_action", f"{payload.get('tool_count', 0)} calls via ReAct")
                    yield "pipeline", pipeline_payload()
                elif event == "token":
                    yield "token", payload
                elif event == "result":
                    agent_result = payload
                    agent_finish = agent_result.finish.to_dict()
        except Exception as exc:
            step("error_recovery", str(exc)[:120], status="warning")
            yield "pipeline", pipeline_payload()
            async for event, payload in self.recovery.recover_stream(
                exc,
                message=body.message,
                service_context=service_context,
                history=history,
                session_id=session_id,
                partial_trace=agent_trace,
            ):
                if event == "thinking":
                    yield "thinking", payload
                elif event == "pipeline":
                    yield "pipeline", payload
                elif event == "token":
                    yield "token", payload
                elif event == "done":
                    reply = payload.get("reply", "")
                    step("model_response", f"recovery {round(time.perf_counter() - started, 2)}s")
                    pipeline["model"] = {"mode": self.llm.mode, "latency_s": round(time.perf_counter() - started, 2)}
                    await self._persist_turn(
                        db,
                        store,
                        session_id=session_id,
                        user_id=user_id,
                        body=body,
                        edge=edge,
                        reply=reply,
                        intent=payload.get("intent", "clarify"),
                        intent_meta=payload.get("intent_meta") or {},
                        focus_order_id=payload.get("focus_order_id"),
                        agent_trace=[],
                        agent_finish=payload.get("agent_finish") or {},
                        tool_calls=[],
                        pipeline=pipeline,
                    )
                    yield "done", payload
            return

        if agent_result is None:
            raise RuntimeError("Agent 未返回结果")

        tool_calls = agent_result.tool_calls
        focus_order_id = agent_result.focus_order_id or focus_order_id
        workflow_payload = agent_result.workflow_payload

        step("model_response", f"{self.llm.mode} {agent_result.reply_source} {round(time.perf_counter() - started, 2)}s")

        reply = agent_result.finish.draft_message
        pipeline["model"] = {"mode": self.llm.mode, "latency_s": round(time.perf_counter() - started, 2)}

        await self._persist_turn(
            db,
            store,
            session_id=session_id,
            user_id=user_id,
            body=body,
            edge=edge,
            reply=reply,
            intent=intent,
            intent_meta=intent_meta,
            focus_order_id=focus_order_id,
            agent_trace=agent_trace,
            agent_finish=agent_finish,
            tool_calls=tool_calls,
            pipeline=pipeline,
            workflow_payload=workflow_payload,
        )

        yield "done", {
            "session_id": session_id,
            "reply": reply,
            "intent": intent,
            "intent_meta": intent_meta,
            "pipeline": pipeline,
            "service_cards": self._cards(service_context),
            "tool_calls": tool_calls,
            "workflow": workflow_payload,
            "case": workflow_payload,
            "focus_order_id": focus_order_id,
            "agent_trace": agent_trace,
            "agent_finish": agent_finish,
            "pending_confirmations": [p.to_dict() for p in agent_result.pending_confirmations],
        }

    async def _persist_turn(
        self,
        db: AsyncSession,
        store: SessionStore,
        *,
        session_id: str,
        user_id: str,
        body: ChatRequest,
        edge: EdgeContextPacket,
        reply: str,
        intent: str,
        intent_meta: dict,
        focus_order_id: str | None,
        agent_trace: list,
        agent_finish: dict,
        tool_calls: list,
        pipeline: dict,
        workflow_payload: dict | None = None,
    ) -> None:
        await store.append_message(session_id, "user", body.message)
        await self._log(
            db,
            session_id,
            user_id,
            "user",
            body.message,
            intent,
            [],
            {
                "edge": edge.model_dump(),
                "intent_meta": intent_meta,
                "focus_order_id": focus_order_id,
                "agent_trace": agent_trace,
                "agent_finish": agent_finish,
            },
        )

        await store.append_message(session_id, "assistant", reply)
        await self._log(
            db,
            session_id,
            user_id,
            "assistant",
            reply,
            intent,
            tool_calls,
            {"pipeline": pipeline, "intent_meta": intent_meta, "agent_finish": agent_finish},
        )

        if workflow_payload:
            await self._operation_log(
                db,
                session_id,
                user_id,
                "diagnose",
                "agent",
                f"Agent 采纳 Case {workflow_payload.get('case_id')}",
                workflow_payload,
            )

        await self._operation_log(
            db,
            session_id,
            user_id,
            "reply",
            "agent",
            reply[:120],
            {"intent": intent, "case_id": workflow_payload.get("case_id") if workflow_payload else None},
        )

    async def run_once(self, db: AsyncSession, store: SessionStore, body: ChatRequest) -> dict:
        result = None
        async for event, payload in self.run_stream(db, store, body):
            if event == "done":
                result = payload
        return result or {}

    def _cards(self, ctx: dict) -> list[dict]:
        cards: list[dict] = []
        for order in ctx.get("orders", []):
            cards.append({"type": "order", "title": order["title"], "status": order["status"], "payload": order})
        for voucher in ctx.get("vouchers", [])[:3]:
            cards.append({"type": "voucher", "title": voucher["title"], "status": voucher["status"], "payload": voucher})
        for coupon in ctx.get("coupons", [])[:2]:
            cards.append({"type": "coupon", "title": coupon["title"], "status": coupon["status"], "payload": coupon})
        for refund in ctx.get("refunds", [])[:1]:
            cards.append({"type": "refund", "title": f"售后 {refund['id']}", "status": refund["status"], "payload": refund})
        return cards

    async def _log(self, db, session_id, user_id, role, content, intent, tool_calls, metadata) -> None:
        db.add(
            ConversationEvent(
                session_id=session_id,
                user_id=user_id,
                role=role,
                content=content,
                intent=intent,
                tool_calls=tool_calls,
                metadata_=metadata,
            )
        )
        await db.commit()

    async def _operation_log(self, db, session_id, user_id, operation_type, actor, summary, payload=None) -> None:
        try:
            await self.operation_logs.create(
                db,
                session_id=session_id,
                user_id=user_id,
                operation_type=operation_type,
                actor=actor,
                summary=summary,
                payload=payload,
            )
        except Exception:
            await db.rollback()
