"""服务体系建模 — 兼容层，委托 SDS v1 诊断引擎。"""

from __future__ import annotations

from app.diagnosis.engine import DiagnosisEngine
from app.diagnosis.types import DiagnosisContext
from app.services.workflows import (  # noqa: F401 — re-export legacy types
    DiagnosisCheck,
    ServiceWorkflowResult,
    WorkflowAction,
    analyze_voucher_verification_failure,
    workflow_to_prompt,
)

_engine = DiagnosisEngine()


def diagnose_from_context(message: str, order: dict | None, voucher: dict | None, store: dict | None, intent: str = "VoucherUnavailable"):
    ctx = DiagnosisContext(message=message, order=order, voucher=voucher, store=store)
    return _engine.diagnose(intent, ctx)
