"""Agent 运行时状态 — ReAct 循环共享上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.diagnosis.types import DiagnosisContext
from app.services.intent import IntentResult


@dataclass
class AgentTraceStep:
    step: int
    thought: str
    action: str
    action_input: dict[str, Any]
    observation: str | dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation,
            "error": self.error,
        }


@dataclass
class AgentFinishDecision:
    mode: str  # reply | clarify
    draft_message: str = ""
    safe_to_send: bool = True
    reasoning: str = ""
    suggested_actions: list[dict[str, str]] = field(default_factory=list)
    approved_case_id: str | None = None
    approved_case_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "draft_message": self.draft_message,
            "safe_to_send": self.safe_to_send,
            "reasoning": self.reasoning,
            "suggested_actions": self.suggested_actions,
            "approved_case_id": self.approved_case_id,
            "approved_case_name": self.approved_case_name,
        }


@dataclass
class PendingWriteAction:
    tool: str
    action_id: str
    title: str
    description: str
    order_id: str | None = None
    voucher_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "action_id": self.action_id,
            "title": self.title,
            "description": self.description,
            "order_id": self.order_id,
            "voucher_id": self.voucher_id,
            "payload": self.payload,
        }


@dataclass
class AgentRunResult:
    intent_result: IntentResult
    focus_order_id: str | None
    finish: AgentFinishDecision
    trace: list[AgentTraceStep] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    diagnosis_advisories: list[dict] = field(default_factory=list)
    knowledge_titles: list[str] = field(default_factory=list)
    pending_confirmations: list[PendingWriteAction] = field(default_factory=list)
    reply_source: str = "llm_polish"  # draft_direct | llm_polish

    @property
    def workflow_payload(self) -> dict | None:
        """仅当 Agent 明确批准 Case 且给出建议动作时，才下发 workflow（供前端 chips）。"""
        if self.finish.mode == "clarify" or not self.finish.safe_to_send:
            return None
        if not self.finish.approved_case_id and not self.finish.suggested_actions:
            return None
        latest = self.diagnosis_advisories[-1] if self.diagnosis_advisories else {}
        payload = dict(latest) if latest else {}
        if self.finish.approved_case_id:
            payload["case_id"] = self.finish.approved_case_id
            payload["case_name"] = self.finish.approved_case_name or payload.get("case_name")
        if self.finish.suggested_actions:
            payload["solution"] = self.finish.suggested_actions
        return payload or None


@dataclass
class AgentState:
    session_id: str
    user_id: str
    message: str
    service_context: dict
    intent_result: IntentResult
    knowledge_articles: list
    focus_order_id: str | None
    dx_ctx: DiagnosisContext | None = None
    trace: list[AgentTraceStep] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    diagnosis_advisories: list[dict] = field(default_factory=list)
    pending_confirmations: list[PendingWriteAction] = field(default_factory=list)
    focus_bundle_cache: dict[str, Any] | None = None
    executed_tools: set[str] = field(default_factory=set)
    prefetch_done: bool = False
