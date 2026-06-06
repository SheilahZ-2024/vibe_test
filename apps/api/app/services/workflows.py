"""服务体系建模：问题下探 → 流程匹配 → 工具执行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DiagnosisCheck:
    check: str
    status: str
    detail: str
    root_cause: str | None = None


@dataclass
class WorkflowAction:
    action_id: str
    title: str
    description: str
    tool_name: str
    auto_executable: bool = True


@dataclass
class ServiceWorkflowResult:
    issue: str
    root_cause: str
    confidence: str
    diagnosis: list[DiagnosisCheck] = field(default_factory=list)
    solutions: list[WorkflowAction] = field(default_factory=list)
    executed_actions: list[dict] = field(default_factory=list)


VOUCHER_FAILURE_CHECKS = [
    {
        "id": "voucher_status",
        "label": "券状态",
        "pass_when": lambda v, o, s: v and v.get("status") in ("unused", "scheduled"),
        "fail_detail": lambda v, o, s: f"券状态为 {v.get('status') if v else '未找到'}，不可核销",
        "root_cause": "voucher_already_used_or_invalid",
    },
    {
        "id": "validity",
        "label": "有效期",
        "pass_when": lambda v, o, s: _is_valid(v),
        "fail_detail": lambda v, o, s: f"券已于 {v.get('valid_to') if v else '-'} 过期",
        "root_cause": "voucher_expired",
    },
    {
        "id": "store_match",
        "label": "适用门店",
        "pass_when": lambda v, o, s: bool(s),
        "fail_detail": lambda v, o, s: "当前门店不在券适用范围内",
        "root_cause": "store_not_applicable",
    },
    {
        "id": "reservation",
        "label": "预约要求",
        "pass_when": lambda v, o, s: not _needs_reservation(o) or _has_reservation(o),
        "fail_detail": lambda v, o, s: "套餐需提前预约，当前未检测到有效预约",
        "root_cause": "reservation_missing",
    },
    {
        "id": "merchant_scanner",
        "label": "商家扫码设备",
        "pass_when": lambda v, o, s: _scanner_synced(s),
        "fail_detail": lambda v, o, s: "门店收银设备可能未同步最新券包状态",
        "root_cause": "merchant_scanner_out_of_sync",
    },
]

VOUCHER_SOLUTIONS: dict[str, list[WorkflowAction]] = {
    "voucher_expired": [
        WorkflowAction("apply_refund", "申请退款", "券已过期且未使用，可发起退款", "create_refund_case"),
        WorkflowAction("human_handoff", "转人工处理", "复杂售后由人工跟进", "transfer_to_human", auto_executable=False),
    ],
    "store_not_applicable": [
        WorkflowAction("show_applicable_stores", "查看适用门店", "列出该券可核销门店", "query_store"),
        WorkflowAction("human_handoff", "转人工协助", "门店争议由人工核实", "transfer_to_human", auto_executable=False),
    ],
    "reservation_missing": [
        WorkflowAction("create_reservation", "立即预约", "为当前订单创建预约记录", "create_reservation"),
        WorkflowAction("contact_merchant", "联系商家确认", "通知商家协助预约", "contact_merchant"),
    ],
    "merchant_scanner_out_of_sync": [
        WorkflowAction("regenerate_qr", "重新生成核销码", "刷新二维码并推送门店", "regenerate_voucher_qr"),
        WorkflowAction("manual_code", "展示券码手动核销", "向商家展示券码供手动输入", "show_voucher_code"),
        WorkflowAction("contact_merchant", "联系商家确认", "同步券状态到门店收银系统", "contact_merchant"),
        WorkflowAction("human_handoff", "转人工并同步诊断", "仍失败则升级人工", "transfer_to_human", auto_executable=False),
    ],
    "voucher_already_used_or_invalid": [
        WorkflowAction("query_voucher", "核对券使用记录", "查询券码历史状态", "query_voucher"),
        WorkflowAction("human_handoff", "转人工核实", "疑似重复核销需人工介入", "transfer_to_human", auto_executable=False),
    ],
}


def _is_valid(voucher: dict | None) -> bool:
    if not voucher or not voucher.get("valid_to"):
        return False
    try:
        valid_to = datetime.fromisoformat(str(voucher["valid_to"]).replace("Z", "+00:00"))
        return valid_to > datetime.now(timezone.utc)
    except ValueError:
        return True


def _meta(value: object | None) -> dict:
    return value if isinstance(value, dict) else {}


def _needs_reservation(order: dict | None) -> bool:
    if not order:
        return False
    meta = _meta(order.get("metadata"))
    return bool(meta.get("reservation_required"))


def _has_reservation(order: dict | None) -> bool:
    if not order:
        return False
    meta = _meta(order.get("metadata"))
    return bool(meta.get("reservation_confirmed") or meta.get("appointment"))


def _scanner_synced(store: dict | None) -> bool:
    if not store:
        return False
    meta = _meta(store.get("metadata"))
    return meta.get("scanner_synced", True) is not False


def analyze_voucher_verification_failure(
    voucher: dict | None,
    order: dict | None,
    store: dict | None,
) -> ServiceWorkflowResult:
    diagnosis: list[DiagnosisCheck] = []
    root_cause = "merchant_scanner_out_of_sync"
    confidence = "medium"

    for rule in VOUCHER_FAILURE_CHECKS:
        passed = rule["pass_when"](voucher, order, store)
        diagnosis.append(
            DiagnosisCheck(
                check=rule["label"],
                status="pass" if passed else ("fail" if rule["id"] in ("voucher_status", "validity", "store_match") else "warning"),
                detail="正常" if passed else rule["fail_detail"](voucher, order, store),
                root_cause=None if passed else rule["root_cause"],
            )
        )
        if not passed and rule["id"] in ("voucher_status", "validity", "store_match", "reservation"):
            root_cause = rule["root_cause"]
            confidence = "high"
            break
        if not passed and rule["id"] == "merchant_scanner":
            root_cause = rule["root_cause"]
            confidence = "medium"

    solutions = VOUCHER_SOLUTIONS.get(root_cause, VOUCHER_SOLUTIONS["merchant_scanner_out_of_sync"])
    return ServiceWorkflowResult(
        issue="voucher_verification_failed",
        root_cause=root_cause,
        confidence=confidence,
        diagnosis=diagnosis,
        solutions=solutions,
    )


def workflow_to_prompt(result: ServiceWorkflowResult) -> str:
    checks = "\n".join(f"- {d.check}: {d.status} ({d.detail})" for d in result.diagnosis)
    actions = "\n".join(f"- {a.title}: {a.description}" for a in result.solutions)
    return (
        f"问题类型：{result.issue}\n"
        f"根因判断：{result.root_cause}（置信度 {result.confidence}）\n"
        f"诊断结果：\n{checks}\n"
        f"推荐处置：\n{actions}"
    )
