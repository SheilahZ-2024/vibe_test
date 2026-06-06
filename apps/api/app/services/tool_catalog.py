"""Agent 可用工具目录 — 供 ReAct 大模型选择与编排。"""

from __future__ import annotations

from app.config import settings

TOOL_CATALOG: dict[str, dict] = {
    "list_orders": {
        "description": "列出用户全部订单摘要（多订单未聚焦时优先调用）。",
        "parameters": {},
        "read_only": True,
    },
    "query_order": {
        "description": "查询指定订单详情、状态、是否可退。",
        "parameters": {"order_id": "string，必填"},
        "read_only": True,
    },
    "query_voucher": {
        "description": "查询团购券/券码/有效期/状态。",
        "parameters": {"voucher_id": "string 可选", "order_id": "string 可选，用于定位关联券"},
        "read_only": True,
    },
    "query_store": {
        "description": "查询门店地址、营业时间、电话。",
        "parameters": {"order_id": "string，必填"},
        "read_only": True,
    },
    "query_focus_bundle": {
        "description": (
            "【推荐】一次并行拉取聚焦订单+关联券+门店。"
            "已有 focus_order_id 时必须优先用此工具，禁止再分别 query_order/query_voucher/query_store。"
        ),
        "parameters": {"order_id": "string 可选，默认当前聚焦订单"},
        "read_only": True,
    },
    "query_coupon": {
        "description": "查询用户优惠券列表与可用性。",
        "parameters": {},
        "read_only": True,
    },
    "query_refund": {
        "description": "查询售后/退款进度与是否可退。",
        "parameters": {"order_id": "string，必填"},
        "read_only": True,
    },
    "query_ticket": {
        "description": "查询工单/投诉进度。",
        "parameters": {},
        "read_only": True,
    },
    "search_knowledge": {
        "description": (
            "检索平台知识库（政策/FAQ/核销规则）。按需调用，自行决定 query 与条数 limit(1~5)；"
            "复杂或政策相关问题建议先查再 finish。"
        ),
        "parameters": {
            "query": "string 可选，默认用户最新表述",
            "limit": "int 可选，1~5，默认 3",
            "intent": "string 可选，辅助检索的意图标签",
        },
        "read_only": True,
    },
    "run_diagnosis": {
        "description": (
            "【轨道 B · 异步】触发诊断引擎脚本，返回结构化 Case/步骤/推荐动作。"
            "与轨道 A 规则并行参考；你须在 thought 中与规则层、query 结果交叉验证后再决定是否采纳。"
        ),
        "parameters": {
            "intent": "string，必填，如 VoucherUnavailable / RefundRequest",
            "order_id": "string 可选，默认当前聚焦订单",
        },
        "read_only": True,
    },
    "regenerate_qr": {
        "description": "重新生成核销二维码。写操作，须 action_input.user_confirmed=true 或走 suggested_actions 由用户确认。",
        "parameters": {"voucher_id": "string，必填", "user_confirmed": "bool，用户已确认时为 true"},
        "read_only": False,
    },
    "contact_merchant": {
        "description": "联系商家协助核销或接待。写操作，须用户确认。",
        "parameters": {"order_id": "string，必填", "reason": "string 可选", "user_confirmed": "bool"},
        "read_only": False,
    },
    "create_reservation": {
        "description": "为订单创建预约。写操作，须用户确认。",
        "parameters": {"order_id": "string，必填", "slot": "string ISO 时间，可选", "user_confirmed": "bool"},
        "read_only": False,
    },
    "apply_refund": {
        "description": "提交退款申请。写操作，须先 query_refund 且 user_confirmed=true。",
        "parameters": {"order_id": "string，必填", "reason": "string 可选", "user_confirmed": "bool"},
        "read_only": False,
    },
    "human_handoff": {
        "description": "转人工并建工单。写操作，建议 user_confirmed=true 或 suggested_actions。",
        "parameters": {"order_id": "string 可选", "reason": "string 可选", "user_confirmed": "bool"},
        "read_only": False,
    },
}

WRITE_TOOLS = frozenset(name for name, meta in TOOL_CATALOG.items() if not meta.get("read_only", True))

TOOL_TO_ACTION_ID: dict[str, str] = {
    "regenerate_qr": "regenerate_qr",
    "contact_merchant": "contact_merchant",
    "create_reservation": "create_reservation",
    "apply_refund": "apply_refund",
    "human_handoff": "human_handoff",
}

WRITE_ACTION_TITLES: dict[str, str] = {
    "regenerate_qr": "重新生成核销码",
    "contact_merchant": "联系商家",
    "create_reservation": "创建预约",
    "apply_refund": "提交退款",
    "human_handoff": "转人工客服",
}

_ATOMIC_FOCUS_READS = frozenset({"query_order", "query_voucher", "query_store"})

# 按意图裁剪工具列表；有 bundle 时不再暴露原子 query_*（由 settings 控制）
_INTENT_TOOL_SETS: dict[str, tuple[str, ...]] = {
    "chitchat": ("human_handoff",),
    "unconfigured": ("list_orders", "human_handoff"),
    "clarify": ("list_orders", "query_focus_bundle", "search_knowledge", "human_handoff"),
    "QueryOrder": ("list_orders", "query_focus_bundle", "search_knowledge", "human_handoff"),
    "QueryVoucher": ("list_orders", "query_focus_bundle", "search_knowledge", "run_diagnosis", "human_handoff"),
    "QueryCoupon": ("list_orders", "query_coupon", "search_knowledge", "human_handoff"),
    "QueryStore": ("list_orders", "query_focus_bundle", "search_knowledge", "human_handoff"),
    "QueryReservation": (
        "list_orders",
        "query_focus_bundle",
        "search_knowledge",
        "create_reservation",
        "run_diagnosis",
        "human_handoff",
    ),
    "QueryRefund": ("list_orders", "query_order", "query_refund", "search_knowledge", "human_handoff"),
    "QueryTicket": ("list_orders", "query_ticket", "search_knowledge", "human_handoff"),
    "VoucherUnavailable": (
        "list_orders",
        "query_focus_bundle",
        "search_knowledge",
        "run_diagnosis",
        "regenerate_qr",
        "contact_merchant",
        "human_handoff",
    ),
    "MerchantReject": (
        "list_orders",
        "query_focus_bundle",
        "search_knowledge",
        "run_diagnosis",
        "contact_merchant",
        "human_handoff",
    ),
    "RefundRequest": (
        "list_orders",
        "query_order",
        "query_refund",
        "search_knowledge",
        "run_diagnosis",
        "apply_refund",
        "human_handoff",
    ),
    "StoreUnavailable": (
        "list_orders",
        "query_focus_bundle",
        "search_knowledge",
        "run_diagnosis",
        "human_handoff",
    ),
    "ReservationFailure": (
        "list_orders",
        "query_focus_bundle",
        "search_knowledge",
        "create_reservation",
        "run_diagnosis",
        "human_handoff",
    ),
    "HumanTransfer": ("list_orders", "query_order", "human_handoff"),
}

_DEFAULT_TOOLS: tuple[str, ...] = (
    "list_orders",
    "query_focus_bundle",
    "query_refund",
    "search_knowledge",
    "run_diagnosis",
    "human_handoff",
)

_ALWAYS_AVAILABLE = frozenset({"finish"})


def _base_tools(intent: str | None) -> list[str]:
    if not intent:
        names = list(_DEFAULT_TOOLS)
    elif intent in _INTENT_TOOL_SETS:
        names = list(_INTENT_TOOL_SETS[intent])
    elif intent.startswith("Query") or intent.startswith("Check"):
        names = list(_INTENT_TOOL_SETS.get("QueryOrder", _DEFAULT_TOOLS))
    elif "Complaint" in intent or intent in ("ServiceMismatch", "PriceDispute", "AppealRequest", "CompensationRequest"):
        names = list(
            dict.fromkeys(
                [
                    "list_orders",
                    "query_focus_bundle",
                    "search_knowledge",
                    "run_diagnosis",
                    "human_handoff",
                    "contact_merchant",
                ]
            )
        )
    else:
        names = list(_DEFAULT_TOOLS)

    if settings.agent_hide_atomic_focus_reads and "query_focus_bundle" in names:
        names = [n for n in names if n not in _ATOMIC_FOCUS_READS]
    return names


def tools_for_intent(intent: str | None, *, exclude: set[str] | None = None) -> list[str]:
    names = _base_tools(intent)
    if exclude:
        names = [n for n in names if n not in exclude]
    return names


def tools_for_continuation(intent: str | None, executed: set[str]) -> list[str]:
    """续步只展示尚未执行过的工具（写操作/诊断/知识检索仍可重复）。"""
    names = _base_tools(intent)
    repeatable = frozenset({"search_knowledge", "run_diagnosis", "finish"}) | WRITE_TOOLS
    return [n for n in names if n not in executed or n in repeatable]


def tool_catalog_block(
    *,
    intent: str | None = None,
    compact: bool = False,
    exclude: set[str] | None = None,
    executed: set[str] | None = None,
) -> str:
    if executed:
        names = tools_for_continuation(intent, executed)
    else:
        names = tools_for_intent(intent, exclude=exclude)
    lines = []
    for name in names:
        meta = TOOL_CATALOG.get(name)
        if not meta:
            continue
        if compact:
            ro = "只读" if meta.get("read_only", True) else "写·需确认"
            lines.append(f"{name}({ro}): {meta['description'][:48]}")
        else:
            params = meta.get("parameters") or {}
            param_text = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "无"
            ro = "只读" if meta.get("read_only", True) else "写操作·需确认"
            lines.append(f"- {name}（{ro}）: {meta['description']}\n  参数: {param_text}")
    return "\n".join(lines) if not compact else " | ".join(lines)
