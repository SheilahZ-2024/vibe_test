import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ConversationEvent
from app.repositories.life_service import KnowledgeRepository, OperationLogRepository
from app.schemas.api import ChatRequest, EdgeContextPacket
from app.services.context import ServiceContextBuilder, context_summary
from app.services.llm import LLMService
from app.services.sessions import SessionStore
from app.services.tools import LifeServiceTools


def detect_intent(message: str) -> str:
    if any(k in message for k in ("核销失败", "扫不出来", "无法核销", "核销不了", "券用不了")):
        return "voucher_verification_failed"
    if any(k in message for k in ("人工", "投诉", "客服")):
        return "human_handoff"
    if any(k in message for k in ("券码", "团购券", "核销", "还能用", "怎么用")):
        return "voucher_usage"
    if any(k in message for k in ("优惠券", "不能用", "用不了", "满减")):
        return "coupon_explain"
    if any(k in message for k in ("退款", "退掉", "售后", "退票")):
        return "refund"
    if any(k in message for k in ("营业", "几点", "地址", "电话", "预约", "改约", "门店")):
        return "store_fulfillment"
    if any(k in message for k in ("订单", "套餐", "买的", "查")):
        return "order_query"
    return "general"


class ChatOrchestrator:
    def __init__(self):
        self.context_builder = ServiceContextBuilder()
        self.knowledge = KnowledgeRepository()
        self.operation_logs = OperationLogRepository()
        self.tools = LifeServiceTools()
        self.llm = LLMService()

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

        intent = detect_intent(body.message)
        pipeline: dict = {"steps": []}
        tool_calls: list[dict] = []

        def step(name: str, detail: str = "", status: str = "done") -> None:
            pipeline["steps"].append({"name": name, "status": status, "detail": detail})

        step("intent_detect", intent)
        service_context = await self.context_builder.build(db, edge, user_id)
        step("service_context", f"{len(service_context['orders'])} orders, {len(service_context['vouchers'])} vouchers")

        knowledge_hits = await self.knowledge.search(db, body.message)
        step("knowledge_search", f"{len(knowledge_hits)} articles")

        workflow_summary = ""
        workflow_payload: dict | None = None
        if intent == "voucher_verification_failed":
            result = await self.tools.diagnose_voucher_issue(db, user_id)
            tool_calls.append({"name": "query_order", "result": {"order": result.get("order")}})
            tool_calls.append({"name": "query_voucher", "result": {"voucher": result.get("voucher")}})
            tool_calls.append({"name": "query_store", "result": {"store": result.get("store")}})
            tool_calls.append({"name": "diagnose_voucher_issue", "result": result})
            workflow_payload = result
            workflow_summary = (
                f"根因：{result.get('root_cause')}；置信度：{result.get('confidence')}；"
                f"推荐动作：{', '.join(s['title'] for s in result.get('solution', []))}"
            )
            step("workflow_match", workflow_summary)
            await self._operation_log(
                db,
                session_id,
                user_id,
                "diagnose",
                "agent",
                f"核销失败诊断：{result.get('root_cause')}",
                {"diagnosis": result.get("diagnosis"), "solution": result.get("solution")},
            )
        elif intent == "order_query":
            result = await self.tools.query_order(db, user_id)
            tool_calls.append({"name": "query_order", "result": result})
        elif intent == "store_fulfillment":
            result = await self.tools.query_store(db, user_id)
            tool_calls.append({"name": "query_store", "result": result})
        elif intent == "voucher_usage":
            result = await self.tools.query_voucher(db, user_id)
            tool_calls.append({"name": "query_voucher", "result": result})
        elif intent == "coupon_explain":
            result = await self.tools.query_coupon(db, user_id)
            tool_calls.append({"name": "query_coupon", "result": result})
        elif intent == "refund":
            result = await self.tools.query_refund(db, user_id)
            tool_calls.append({"name": "query_refund", "result": result})
        elif intent == "human_handoff":
            ticket = await self.tools.transfer_to_human(
                db,
                session_id,
                user_id,
                None,
                {"reason": body.message, "context": service_context},
            )
            tool_calls.append({"name": "create_service_ticket", "result": {"ticket_id": ticket.id, "priority": ticket.priority}})
            tool_calls.append({"name": "transfer_to_human", "result": {"ticket_id": ticket.id, "priority": ticket.priority}})

        step("tool_action", f"{len(tool_calls)} calls")
        system = self._build_system_prompt(service_context, knowledge_hits, intent, tool_calls, workflow_summary)
        step("prompt_build", f"{len(system)} chars")

        history = await store.get_messages(session_id)
        await store.append_message(session_id, "user", body.message)
        await self._log(db, session_id, user_id, "user", body.message, intent, [], {"edge": edge.model_dump()})
        await self._operation_log(db, session_id, user_id, "message", "user", body.message, {"intent": intent})

        yield "pipeline", {"session_id": session_id, "intent": intent, "pipeline": pipeline, "service_cards": self._cards(service_context)}

        full = []
        async for chunk in self.llm.stream_reply(system, history, body.message):
            full.append(chunk)
            yield "token", {"text": chunk}

        reply = "".join(full)
        latency = round(time.perf_counter() - started, 2)
        pipeline["model"] = {"mode": self.llm.mode, "latency_s": latency}
        step("model_response", f"{self.llm.mode} {latency}s")
        await store.append_message(session_id, "assistant", reply)
        await self._log(db, session_id, user_id, "assistant", reply, intent, tool_calls, {"pipeline": pipeline})
        await self._operation_log(
            db,
            session_id,
            user_id,
            "reply",
            "agent",
            reply[:120],
            {"intent": intent, "tool_calls": [t["name"] for t in tool_calls]},
        )

        yield "done", {
            "session_id": session_id,
            "reply": reply,
            "intent": intent,
            "pipeline": pipeline,
            "service_cards": self._cards(service_context),
            "tool_calls": tool_calls,
            "workflow": workflow_payload,
        }

    async def run_once(self, db: AsyncSession, store: SessionStore, body: ChatRequest) -> dict:
        result = None
        async for event, payload in self.run_stream(db, store, body):
            if event == "done":
                result = payload
        return result or {}

    def _build_system_prompt(
        self,
        ctx: dict,
        articles: list,
        intent: str,
        tool_calls: list[dict],
        workflow_summary: str = "",
    ) -> str:
        article_text = "\n".join(f"- {a.title}: {a.content}" for a in articles)
        tools_text = "\n".join(f"- {t['name']}: {t['result']}" for t in tool_calls)
        return f"""你是抖音生活服务 C 端智能服务助手。
产品定位：你不是智能客服，也不是 FAQ 机器人，而是 AI 履约服务管家。
核心目标：帮助用户成功完成一次生活服务消费履约。
回答要求：中文、简洁、面向履约结果；不要只回答文本，每次尽量给出可执行下一步。
当用户反馈券码无法核销时，必须先说明诊断出的根因，再给出 1-2 个可立即执行的处置方案。

当前意图：{intent}

用户服务上下文：
{context_summary(ctx)}

知识库参考：
{article_text or "无"}

服务体系处置：
{workflow_summary or "无"}

工具调用结果：
{tools_text or "无"}
"""

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

    async def _log(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        intent: str,
        tool_calls: list,
        metadata: dict,
    ) -> None:
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

    async def _operation_log(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        operation_type: str,
        actor: str,
        summary: str,
        payload: dict | None = None,
    ) -> None:
        await self.operation_logs.create(
            db,
            session_id=session_id,
            user_id=user_id,
            operation_type=operation_type,
            actor=actor,
            summary=summary,
            payload=payload,
        )
