"""用户服务记录 — 操作日志 + 退款/售后，按时间倒序。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AgentOperationLog, LifeOrder, RefundCase

_REFUND_STATUS = {
    "submitted": ("退款审核中", "尚未到账，请耐心等待"),
    "processing": ("退款处理中", "银行处理中，预计原路退回"),
    "approved": ("退款成功", "款项已原路返回"),
    "rejected": ("退款未通过", "可联系客服申诉"),
}

_OP_TYPE_TITLE = {
    "query": "查询服务",
    "diagnose": "问题诊断",
    "execute": "办理操作",
    "notify": "进度通知",
    "handoff": "转接人工",
    "reply": "管家回复",
}


async def list_service_records(db: AsyncSession, user_id: str, *, limit: int = 50) -> list[dict]:
    logs_q = (
        select(AgentOperationLog)
        .where(AgentOperationLog.user_id == user_id)
        .order_by(AgentOperationLog.created_at.desc())
        .limit(limit)
    )
    logs = list((await db.execute(logs_q)).scalars().all())

    refunds_q = (
        select(RefundCase)
        .where(RefundCase.user_id == user_id)
        .order_by(RefundCase.created_at.desc())
        .limit(limit)
    )
    refunds = list((await db.execute(refunds_q)).scalars().all())

    order_ids = {r.order_id for r in refunds} | {
        str((log.payload or {}).get("order_id") or "") for log in logs if log.payload
    }
    order_ids.discard("")
    orders: dict[str, LifeOrder] = {}
    if order_ids:
        oq = select(LifeOrder).where(LifeOrder.id.in_(order_ids))
        orders = {o.id: o for o in (await db.execute(oq)).scalars().all()}

    records: list[dict] = []

    for r in refunds:
        title, money_hint = _REFUND_STATUS.get(r.status, (r.status, ""))
        order_title = orders.get(r.order_id).title if r.order_id in orders else r.order_id
        records.append(
            {
                "id": f"refund:{r.id}",
                "kind": "refund",
                "title": f"退款 · {order_title}",
                "summary": r.reason,
                "status": r.status,
                "status_label": title,
                "money_amount": float(r.refundable_amount),
                "money_status": money_hint,
                "order_id": r.order_id,
                "actor": "用户",
                "occurred_at": r.created_at.isoformat() if r.created_at else None,
                "estimated_finish_time": r.estimated_finish_time.isoformat() if r.estimated_finish_time else None,
            }
        )

    for log in logs:
        payload = log.payload or {}
        order_id = payload.get("order_id")
        order_title = orders.get(str(order_id)).title if order_id and str(order_id) in orders else None
        records.append(
            {
                "id": f"log:{log.id}",
                "kind": "operation",
                "title": _OP_TYPE_TITLE.get(log.operation_type, log.operation_type),
                "summary": log.summary,
                "status": payload.get("status") or "done",
                "status_label": payload.get("status_label") or _resolve_log_status(payload),
                "money_amount": payload.get("amount"),
                "money_status": payload.get("money_status"),
                "order_id": order_id,
                "order_title": order_title,
                "actor": _actor_label(log.actor),
                "occurred_at": log.created_at.isoformat() if log.created_at else None,
                "operation_type": log.operation_type,
            }
        )

    records.sort(key=lambda x: x.get("occurred_at") or "", reverse=True)
    return records[:limit]


def _actor_label(actor: str) -> str:
    return {"user": "用户", "agent": "AI 管家", "tool": "系统", "system": "平台"}.get(actor, actor)


def _resolve_log_status(payload: dict) -> str:
    if payload.get("money_status"):
        return str(payload["money_status"])
    if payload.get("result") == "success":
        return "已完成"
    return "已记录"
