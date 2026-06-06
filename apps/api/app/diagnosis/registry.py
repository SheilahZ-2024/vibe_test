"""SDS v1 Case 注册表 — 70 Case 全量元数据。"""

from __future__ import annotations

from dataclasses import dataclass

from app.diagnosis.case_specs import FULL_CASE_SPECS


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    name: str
    problem_space: str
    intents: tuple[str, ...]
    escalation: str
    user_goal: str
    rules: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()


def _build_registry() -> dict[str, CaseDefinition]:
    registry: dict[str, CaseDefinition] = {}
    for spec in FULL_CASE_SPECS:
        case_id, name, ps, intents_csv, esc, goal, rules_csv = spec
        registry[case_id] = CaseDefinition(
            case_id=case_id,
            name=name,
            problem_space=ps,
            intents=tuple(i.strip() for i in intents_csv.split(",") if i.strip()),
            escalation=esc,
            user_goal=goal,
            rules=tuple(r.strip() for r in rules_csv.split(",") if r.strip()),
        )
    return registry


CASE_REGISTRY: dict[str, CaseDefinition] = _build_registry()

INTENT_TO_DEFAULT_CASE: dict[str, str] = {
    "QueryOrder": "IC-001",
    "QueryVoucher": "IC-004",
    "QueryCoupon": "IC-007",
    "QueryStore": "IC-008",
    "QueryReservation": "IC-009",
    "QueryRefund": "IC-010",
    "QueryTicket": "AC-008",
    "CheckVoucherAvailability": "IC-004",
    "CheckRefundEligibility": "AC-001",
    "CheckReservationEligibility": "IC-009",
    "VoucherUnavailable": "FC-008",
    "ReservationFailure": "FC-009",
    "MerchantReject": "FC-006",
    "StoreUnavailable": "FC-001",
    "ServiceMismatch": "FC-011",
    "RefundRequest": "AC-001",
    "CompensationRequest": "AC-007",
    "AppealRequest": "AC-009",
    "MerchantComplaint": "CC-001",
    "ServiceComplaint": "CC-003",
    "SafetyComplaint": "CC-009",
    "PriceDispute": "CC-012",
    "HumanTransfer": "HUMAN",
    "clarify": "CLARIFY",
    "chitchat": "CHITCHAT",
}

ALL_CASE_IDS: tuple[str, ...] = tuple(CASE_REGISTRY.keys())
