"""Service Diagnosis System v1 — 核心类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiagnosisStep:
    step: int
    label: str
    status: str  # pass | fail | warning | skip
    detail: str
    rule: str | None = None
    case_id: str | None = None


@dataclass
class RecommendedAction:
    action_id: str
    title: str
    description: str
    tool_name: str
    auto_executable: bool = True


@dataclass
class CaseDiagnosisResult:
    """诊断树执行结果 = 最终 Case + 推荐动作。"""

    intent: str
    case_id: str
    case_name: str
    problem_space: str
    user_goal: str
    confidence: str
    escalation: str  # P0 | P1 | P2 | P3
    triggered_rules: list[str] = field(default_factory=list)
    steps: list[DiagnosisStep] = field(default_factory=list)
    actions: list[RecommendedAction] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "case_id": self.case_id,
            "case_name": self.case_name,
            "problem_space": self.problem_space,
            "user_goal": self.user_goal,
            "confidence": self.confidence,
            "escalation": self.escalation,
            "triggered_rules": self.triggered_rules,
            "diagnosis": [
                {"step": s.step, "check": s.label, "status": s.status, "detail": s.detail, "rule": s.rule, "case_id": s.case_id}
                for s in self.steps
            ],
            "solution": [
                {
                    "action_id": a.action_id,
                    "title": a.title,
                    "description": a.description,
                    "tool": a.tool_name,
                    "auto_executable": a.auto_executable,
                }
                for a in self.actions
            ],
            "root_cause": self.case_id,
        }

    def to_prompt_block(self) -> str:
        steps = "\n".join(f"  {s.step}. {s.label}: {s.status} — {s.detail}" for s in self.steps)
        actions = "\n".join(f"  - {a.title}（{a.tool_name}）: {a.description}" for a in self.actions)
        rules = "、".join(self.triggered_rules) if self.triggered_rules else "无"
        return (
            f"Case: {self.case_id} {self.case_name}\n"
            f"问题空间: {self.problem_space} | 升级等级: {self.escalation} | 置信度: {self.confidence}\n"
            f"用户目标: {self.user_goal}\n"
            f"触发规则: {rules}\n"
            f"诊断树:\n{steps}\n"
            f"推荐动作:\n{actions}"
        )


@dataclass
class DiagnosisContext:
    message: str
    user: dict | None = None
    order: dict | None = None
    voucher: dict | None = None
    store: dict | None = None
    coupon: dict | None = None
    refund: dict | None = None
    orders: list[dict] = field(default_factory=list)
    vouchers: list[dict] = field(default_factory=list)
