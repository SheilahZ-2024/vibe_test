import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.diagnosis import DiagnosisContext, DiagnosisEngine
from app.models.entities import ConversationEvent
from app.repositories.life_service import KnowledgeRepository, OperationLogRepository
from app.schemas.api import ChatRequest, EdgeContextPacket
from app.services.context import ServiceContextBuilder
from app.services.intent import ACTIONABLE_INTENTS, IntentClassifier, IntentResult
from app.services.llm import LLMService
from app.services.prompts import build_system_prompt
from app.services.sessions import SessionStore
from app.services.tools import LifeServiceTools


class ChatOrchestrator:
    def __init__(self):
        self.context_builder = ServiceContextBuilder()
        self.knowledge = KnowledgeRepository()
        self.operation_logs = OperationLogRepository()
        self.tools = LifeServiceTools()
        self.llm = LLMService()
        self.intent_classifier = IntentClassifier(self.llm)
        self.diagnosis_engine = DiagnosisEngine()

    async def run_stream(
        self,
        db: AsyncSession,
        store: SessionStore,
        body: ChatRequest,
    ) -> AsyncIterator[tuple[str, dict]]:
        started = time.perf_counter()
        edge = body.edge_context or EdgeContextPacket()
        user_id = edge.user_id
        session_id = body.session_id or await store.create(user_id)
        await store.refresh(session_id, user_id)

        pipeline: dict = {"steps": []}
        tool_calls: list[dict] = []

        def step(name: str, detail: str = "", status: str = "done") -> None:
            pipeline["steps"].append({"name": name, "status": status, "detail": detail})

        history = await store.get_messages(session_id)
        intent_result = await self.intent_classifier.classify(body.message, history)
        intent = intent_result.route_intent
        step("intent_detect", intent_result.to_pipeline_detail())

        service_context = await self.context_builder.build(db, edge, user_id)
        step("service_context", f"{len(service_context['orders'])} orders, {len(service_context['vouchers'])} vouchers")

        knowledge_hits: list = []
        if intent not in ("chitchat",):
            knowledge_hits = await self.knowledge.search(db, body.message)
            step("knowledge_search", f"{len(knowledge_hits)} articles")
        else:
            step("knowledge_search", "skipped (chitchat)")

        diagnosis_result = None
        workflow_payload: dict | None = None

        if intent in ACTIONABLE_INTENTS or intent in ("clarify", "chitchat"):
            dx_ctx = await self.tools.build_diagnosis_context(db, user_id, body.message, service_context)
            diagnosis_result = self.diagnosis_engine.diagnose(intent, dx_ctx)
            step(
                "diagnosis_tree",
                f"{diagnosis_result.case_id} {diagnosis_result.case_name} ({diagnosis_result.escalation})",
            )
            workflow_payload = diagnosis_result.to_dict()
            step("case_generate", f"{diagnosis_result.case_id} — {diagnosis_result.user_goal}")

            if intent in ACTIONABLE_INTENTS:
                tool_calls = await self.tools.run_diagnosis_tools(db, session_id, user_id, intent, diagnosis_result, dx_ctx)
                step("tool_action", f"{len(tool_calls)} calls")
            else:
                step("tool_action", "skipped (clarify/chitchat)")
        else:
            step("diagnosis_tree", "skipped")
            step("case_generate", "skipped")
            step("tool_action", "0 calls")

        system = build_system_prompt(service_context, intent_result, diagnosis_result, knowledge_hits, tool_calls)
        step("prompt_build", f"{len(system)} chars")

        await store.append_message(session_id, "user", body.message)
        await self._log(db, session_id, user_id, "user", body.message, intent, [], {"edge": edge.model_dump(), "intent_meta": self._intent_meta(intent_result), "case_id": (diagnosis_result.case_id if diagnosis_result else None)})
        if diagnosis_result:
            await self._operation_log(db, session_id, user_id, "diagnose", "agent", f"Case {diagnosis_result.case_id}: {diagnosis_result.case_name}", workflow_payload)

        yield "pipeline", {
            "session_id": session_id,
            "intent": intent,
            "intent_meta": self._intent_meta(intent_result),
            "pipeline": pipeline,
            "service_cards": self._cards(service_context),
            "case": workflow_payload,
        }

        full = []
        async for chunk in self.llm.stream_reply(system, history, body.message):
            full.append(chunk)
            yield "token", {"text": chunk}

        reply = "".join(full)
        latency = round(time.perf_counter() - started, 2)
        pipeline["model"] = {"mode": self.llm.mode, "latency_s": latency}
        step("model_response", f"{self.llm.mode} {latency}s")
        await store.append_message(session_id, "assistant", reply)
        await self._log(db, session_id, user_id, "assistant", reply, intent, tool_calls, {"pipeline": pipeline, "intent_meta": self._intent_meta(intent_result)})
        await self._operation_log(db, session_id, user_id, "reply", "agent", reply[:120], {"intent": intent, "case_id": diagnosis_result.case_id if diagnosis_result else None})

        yield "done", {
            "session_id": session_id,
            "reply": reply,
            "intent": intent,
            "intent_meta": self._intent_meta(intent_result),
            "pipeline": pipeline,
            "service_cards": self._cards(service_context),
            "tool_calls": tool_calls,
            "workflow": workflow_payload,
            "case": workflow_payload,
        }

    async def run_once(self, db: AsyncSession, store: SessionStore, body: ChatRequest) -> dict:
        result = None
        async for event, payload in self.run_stream(db, store, body):
            if event == "done":
                result = payload
        return result or {}

    def _intent_meta(self, intent_result: IntentResult) -> dict:
        return {
            "raw_intent": intent_result.raw_intent,
            "route_intent": intent_result.route_intent,
            "confidence": intent_result.confidence,
            "needs_clarify": intent_result.needs_clarify,
            "source": intent_result.source,
            "reasoning": intent_result.reasoning,
            "alternatives": intent_result.alternatives,
        }

    def _cards(self, ctx: dict) -> list[dict]:
        cards: list[dict] = []
        for order in ctx.get("orders", [])[:3]:
            cards.append({"type": "order", "title": order["title"], "status": order["status"], "payload": order})
        for voucher in ctx.get("vouchers", [])[:2]:
            cards.append({"type": "voucher", "title": voucher["title"], "status": voucher["status"], "payload": voucher})
        for coupon in ctx.get("coupons", [])[:2]:
            cards.append({"type": "coupon", "title": coupon["title"], "status": coupon["status"], "payload": coupon})
        for refund in ctx.get("refunds", [])[:1]:
            cards.append({"type": "refund", "title": f"售后 {refund['id']}", "status": refund["status"], "payload": refund})
        return cards

    async def _log(self, db, session_id, user_id, role, content, intent, tool_calls, metadata) -> None:
        db.add(ConversationEvent(session_id=session_id, user_id=user_id, role=role, content=content, intent=intent, tool_calls=tool_calls, metadata_=metadata))
        await db.commit()

    async def _operation_log(self, db, session_id, user_id, operation_type, actor, summary, payload=None) -> None:
        try:
            await self.operation_logs.create(db, session_id=session_id, user_id=user_id, operation_type=operation_type, actor=actor, summary=summary, payload=payload)
        except Exception:
            await db.rollback()

