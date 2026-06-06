"""动作 / 工具 / 升级矩阵 — 70 Case 全量 Action → Tool 映射。"""

from __future__ import annotations

from app.diagnosis.registry import CASE_REGISTRY
from app.diagnosis.types import RecommendedAction

ACTION_TEMPLATES: dict[str, RecommendedAction] = {
    "regenerate_qr": RecommendedAction("regenerate_qr", "重新生成核销码", "刷新二维码并推送门店", "regenerate_voucher_qr"),
    "manual_code": RecommendedAction("manual_code", "展示券码手动核销", "向商家展示券码供手动输入", "show_voucher_code"),
    "contact_merchant": RecommendedAction("contact_merchant", "联系商家", "通知商家协助核销或预约", "contact_merchant"),
    "create_reservation": RecommendedAction("create_reservation", "立即预约", "为订单创建预约记录", "modify_reservation"),
    "apply_refund": RecommendedAction("apply_refund", "申请退款", "发起退款申请", "create_refund"),
    "human_handoff": RecommendedAction("human_handoff", "转人工", "创建工单并转接人工客服", "transfer_human", auto_executable=False),
    "create_complaint": RecommendedAction("create_complaint", "发起投诉", "记录投诉并进入处理流程", "create_complaint"),
    "apply_compensation": RecommendedAction("apply_compensation", "申请补偿", "提交补偿审核", "apply_compensation", auto_executable=False),
    "create_ticket": RecommendedAction("create_ticket", "创建工单", "系统异常或复杂问题建单", "create_ticket", auto_executable=False),
    "query_order": RecommendedAction("query_order", "查看订单", "拉取订单详情", "query_order"),
    "query_voucher": RecommendedAction("query_voucher", "查看券码", "拉取券状态与规则", "query_voucher"),
    "query_store": RecommendedAction("query_store", "查看门店", "拉取门店营业信息", "query_store"),
    "query_refund": RecommendedAction("query_refund", "查看退款", "拉取退款规则与进度", "query_refund"),
    "query_ticket": RecommendedAction("query_ticket", "查看工单", "拉取工单进度", "query_ticket"),
    "recommend_store": RecommendedAction("recommend_store", "推荐替代门店", "查找同品牌可履约门店", "query_store"),
    "appeal": RecommendedAction("appeal", "提交申诉", "对处理结果发起申诉", "create_ticket", auto_executable=False),
}

# 按 Case 精确配置（覆盖默认策略）
CASE_ACTION_MATRIX: dict[str, list[str]] = {
    "IC-001": ["query_order"],
    "IC-002": ["query_order", "create_ticket"],
    "IC-003": ["query_order"],
    "IC-004": ["query_voucher"],
    "IC-005": ["query_voucher"],
    "IC-006": ["query_voucher"],
    "IC-007": ["query_voucher"],
    "IC-008": ["query_store"],
    "IC-009": ["query_order"],
    "IC-010": ["query_refund"],
    "PC-001": ["query_order", "create_ticket", "human_handoff"],
    "PC-002": ["query_order", "create_ticket", "human_handoff"],
    "PC-003": ["query_order", "human_handoff"],
    "PC-004": ["query_voucher", "create_ticket"],
    "PC-005": ["query_voucher", "apply_refund", "human_handoff"],
    "PC-006": ["query_voucher", "human_handoff"],
    "PC-007": ["query_voucher", "create_ticket", "human_handoff"],
    "PC-008": ["query_store", "query_voucher"],
    "PC-009": ["query_voucher"],
    "PC-010": ["create_reservation", "contact_merchant"],
    "PC-011": ["regenerate_qr", "manual_code", "contact_merchant"],
    "PC-012": ["query_voucher"],
    "PC-013": ["query_voucher"],
    "PC-014": ["query_voucher"],
    "PC-015": ["create_complaint", "apply_refund", "human_handoff"],
    "FC-001": ["recommend_store", "apply_refund", "contact_merchant"],
    "FC-002": ["apply_refund", "human_handoff"],
    "FC-003": ["query_store", "contact_merchant"],
    "FC-004": ["contact_merchant", "create_ticket"],
    "FC-005": ["create_reservation", "recommend_store", "apply_compensation"],
    "FC-006": ["contact_merchant", "create_complaint", "human_handoff"],
    "FC-007": ["create_complaint", "human_handoff", "apply_refund"],
    "FC-008": ["regenerate_qr", "manual_code", "contact_merchant", "human_handoff"],
    "FC-009": ["create_reservation", "recommend_store", "apply_refund"],
    "FC-010": ["contact_merchant", "create_complaint", "human_handoff"],
    "FC-011": ["create_complaint", "apply_compensation", "human_handoff"],
    "FC-012": ["contact_merchant", "create_complaint", "human_handoff"],
    "FC-013": ["recommend_store", "apply_refund", "contact_merchant"],
    "FC-014": ["apply_compensation", "create_complaint"],
    "FC-015": ["create_complaint", "human_handoff"],
    "FC-016": ["create_complaint", "human_handoff"],
    "FC-017": ["create_complaint", "human_handoff", "apply_refund"],
    "FC-018": ["create_reservation", "apply_refund"],
    "FC-019": ["apply_refund", "recommend_store"],
    "FC-020": ["apply_refund", "recommend_store", "human_handoff"],
    "AC-001": ["query_refund", "apply_refund"],
    "AC-002": ["query_refund", "appeal", "human_handoff"],
    "AC-003": ["query_refund", "apply_refund", "human_handoff"],
    "AC-004": ["query_refund"],
    "AC-005": ["query_refund", "create_ticket", "human_handoff"],
    "AC-006": ["query_refund", "appeal", "human_handoff"],
    "AC-007": ["apply_compensation", "human_handoff"],
    "AC-008": ["query_ticket"],
    "AC-009": ["appeal", "human_handoff"],
    "AC-010": ["human_handoff", "create_ticket"],
    "CC-001": ["create_complaint", "apply_compensation", "human_handoff"],
    "CC-002": ["create_complaint", "human_handoff"],
    "CC-003": ["create_complaint", "human_handoff"],
    "CC-004": ["create_complaint", "apply_compensation"],
    "CC-005": ["create_complaint", "human_handoff"],
    "CC-006": ["create_complaint", "human_handoff"],
    "CC-007": ["create_complaint", "contact_merchant", "human_handoff"],
    "CC-008": ["create_complaint", "human_handoff"],
    "CC-009": ["create_complaint", "human_handoff"],
    "CC-010": ["create_complaint", "human_handoff"],
    "CC-011": ["create_complaint", "apply_compensation", "human_handoff"],
    "CC-012": ["query_order", "create_complaint"],
    "CC-013": ["create_complaint", "human_handoff"],
    "CC-014": ["appeal", "human_handoff"],
    "CC-015": ["human_handoff", "create_ticket"],
    "HUMAN": ["human_handoff"],
}

# 按 escalation 的默认动作（Case 未单独配置时使用）
ESCALATION_DEFAULT_ACTIONS: dict[str, list[str]] = {
    "P0": ["create_complaint", "human_handoff", "create_ticket"],
    "P1": ["contact_merchant", "create_complaint", "human_handoff"],
    "P2": ["contact_merchant", "apply_refund", "human_handoff"],
    "P3": ["query_order"],
}


def resolve_actions(case_id: str, case_actions: tuple[str, ...] | None = None) -> list[RecommendedAction]:
    if case_actions:
        ids = list(case_actions)
    elif case_id in CASE_ACTION_MATRIX:
        ids = CASE_ACTION_MATRIX[case_id]
    else:
        case = CASE_REGISTRY.get(case_id)
        ids = ESCALATION_DEFAULT_ACTIONS.get(case.escalation if case else "P3", ["query_order"])

    seen: set[str] = set()
    out: list[RecommendedAction] = []
    for aid in ids:
        if aid in seen:
            continue
        seen.add(aid)
        tpl = ACTION_TEMPLATES.get(aid)
        if tpl:
            out.append(tpl)
    return out
