"""Turn 规划 — 轻量路由：意图 + 接话模式；Gather 工具由 ReAct 主导。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.api import EdgeContextPacket
from app.services.intent import IntentClassifier, IntentResult

_ELIGIBILITY_INTENTS = frozenset(
    {
        "CheckVoucherAvailability",
        "CheckRefundEligibility",
        "CheckReservationEligibility",
        "VoucherUnavailable",
        "ReservationFailure",
        "MerchantReject",
    }
)
_LOOKUP_INTENTS = frozenset(
    {
        "QueryOrder",
        "QueryVoucher",
        "QueryStore",
        "QueryReservation",
        "QueryRefund",
        "QueryTicket",
        "QueryCoupon",
    }
)
_POLICY_INTENTS = frozenset(
    {
        "MerchantComplaint",
        "ServiceComplaint",
        "SafetyComplaint",
        "AppealRequest",
        "CompensationRequest",
        "HumanTransfer",
    }
)


@dataclass
class TurnPlan:
    """单轮用户消息的路由计划（不硬编码 gather 工具清单）。"""

    message: str
    route_intent: str
    route_category: str
    turn_mode: str
    task_type: str  # acknowledgment | follow_up | eligibility | lookup | policy | complaint | clarify | chitchat
    focus_order_id: str | None
    reuse_prior_facts: bool = False
    skip_gather_react: bool = False
    skip_compose_llm: bool = False
    confidence: float = 0.0
    source: str = "keyword"
    reasoning: str = ""
    intent_result: IntentResult | None = None
    # 兼容字段，不再由 Planner 填充
    gather_tools: list[str] = field(default_factory=list)

    def to_intent_meta(self) -> dict:
        ir = self.intent_result
        return {
            "raw_intent": ir.raw_intent if ir else self.route_intent,
            "route_intent": self.route_intent,
            "route_category": self.route_category,
            "confidence": self.confidence,
            "needs_clarify": ir.needs_clarify if ir else self.task_type == "clarify",
            "source": self.source,
            "reasoning": self.reasoning,
            "alternatives": ir.alternatives if ir else [],
            "turn_mode": self.turn_mode,
            "task_type": self.task_type,
            "gather_mode": "react" if not self.skip_gather_react else "skip",
        }


def _task_type_from_intent(intent: IntentResult, message: str) -> str:
    if intent.turn_mode == "acknowledgment" or intent.route_category == "chitchat":
        return "acknowledgment" if intent.turn_mode == "acknowledgment" else "chitchat"
    if intent.route_intent == "clarify" or intent.needs_clarify:
        return "clarify"
    if intent.turn_mode == "continuation":
        return "follow_up"
    if intent.route_intent in _ELIGIBILITY_INTENTS:
        return "eligibility"
    if intent.route_intent in _POLICY_INTENTS:
        return "policy"
    if intent.route_intent in _LOOKUP_INTENTS:
        return "lookup"
    if intent.route_category == "unconfigured":
        return "clarify"
    if any(k in message for k in ("投诉", "举报", "人工", "客服")):
        return "complaint"
    return "lookup"


class TurnPlanner:
    def __init__(self, classifier: IntentClassifier | None = None):
        self.classifier = classifier or IntentClassifier()

    async def plan(
        self,
        message: str,
        history: list[dict],
        agent_ctx: dict | None,
        edge: EdgeContextPacket | None,
    ) -> TurnPlan:
        intent = await self.classifier.classify(message, history, agent_ctx)
        task_type = _task_type_from_intent(intent, message)

        focus = edge.focus_order_id if edge else None
        if intent.turn_mode in ("continuation", "acknowledgment") and agent_ctx and agent_ctx.get("focus_order_id"):
            focus = str(agent_ctx["focus_order_id"])

        reuse = bool(
            agent_ctx
            and (agent_ctx.get("digest") or agent_ctx.get("fact_sheet"))
            and intent.turn_mode in ("continuation", "acknowledgment")
        )

        skip_gather = task_type == "acknowledgment"
        skip_compose = task_type == "acknowledgment"

        return TurnPlan(
            message=message,
            route_intent=intent.route_intent,
            route_category=intent.route_category,
            turn_mode=intent.turn_mode,
            task_type=task_type,
            focus_order_id=focus,
            reuse_prior_facts=reuse,
            skip_gather_react=skip_gather,
            skip_compose_llm=skip_compose,
            confidence=intent.confidence,
            source=intent.source,
            reasoning=intent.reasoning,
            intent_result=intent,
        )
