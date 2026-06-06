"""订单履约时间线 — 购买→预约→到店→核销（核销即完成使用）→售后。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import FulfillmentEvent, LifeOrder, MerchantStore, RefundCase, Voucher
from app.services.usage_rules import reservation_context

# 核销即视为套餐已使用，不再单独展示「消费」节点
TIMELINE_STAGE_DEFS: list[dict[str, Any]] = [
    {"key": "purchase", "title": "购买支付", "event_types": ["purchase"]},
    {"key": "reservation", "title": "预约到店", "event_types": ["reservation", "reschedule"], "optional": True},
    {"key": "arrive", "title": "到店", "event_types": ["arrive"], "optional": True},
    {"key": "verify", "title": "核销使用", "event_types": ["verify"], "desc": "核销成功后套餐视为已使用"},
    {"key": "refund", "title": "售后退款", "event_types": ["refund"], "optional": True},
]

_STATUS_LABEL = {
    "success": "已完成",
    "failed": "失败",
    "pending": "进行中",
    "cancelled": "已取消",
    "processing": "处理中",
    "submitted": "已提交",
    "approved": "已到账",
    "rejected": "未通过",
}

_REFUND_MONEY = {
    "submitted": "退款审核中，尚未到账",
    "processing": "退款处理中，预计原路退回",
    "approved": "退款已原路返回",
    "rejected": "退款未通过",
}


async def build_order_timeline(db: AsyncSession, user_id: str, order_id: str) -> dict:
    order = await db.get(LifeOrder, order_id)
    if not order or order.user_id != user_id:
        return {"order_id": order_id, "stages": [], "events": []}

    q = (
        select(FulfillmentEvent)
        .where(FulfillmentEvent.order_id == order_id, FulfillmentEvent.user_id == user_id)
        .order_by(FulfillmentEvent.created_at.asc())
    )
    events = list((await db.execute(q)).scalars().all())

    rq = select(RefundCase).where(RefundCase.order_id == order_id, RefundCase.user_id == user_id)
    refunds = list((await db.execute(rq)).scalars().all())

    vq = select(Voucher).where(Voucher.order_id == order_id, Voucher.user_id == user_id).limit(1)
    voucher = (await db.execute(vq)).scalar_one_or_none()
    store = await db.get(MerchantStore, order.store_id)
    res_ctx = reservation_context(
        usage_rule=str(voucher.usage_rule if voucher else ""),
        service_type=str(order.service_type or ""),
        supports_reservation=bool(store.supports_reservation if store else False),
        order_metadata=order.metadata_ or {},
    )

    synthesized = _synthesize_events(order, events, refunds, res_ctx)
    stages = _build_stages(order, synthesized, refunds, res_ctx)

    return {
        "order_id": order_id,
        "order_title": order.title,
        "order_status": order.status,
        "stages": stages,
        "reservation": {
            "needs_reservation": res_ctx["needs_reservation"],
            "has_reservation": res_ctx["has_reservation"],
            "label": res_ctx["label"],
            "usage_rule": res_ctx.get("usage_rule"),
        },
        "events": [
            {
                "event_type": e.event_type,
                "status": e.status,
                "detail": e.detail,
                "created_at": e.created_at.isoformat(),
            }
            for e in synthesized
        ],
    }


def _build_stages(
    order: LifeOrder,
    events: list[FulfillmentEvent],
    refunds: list[RefundCase],
    res_ctx: dict,
) -> list[dict]:
    needs_reservation = bool(res_ctx.get("needs_reservation"))
    by_type: dict[str, FulfillmentEvent] = {}
    for ev in events:
        by_type[ev.event_type] = ev

    stages: list[dict] = []
    for spec in TIMELINE_STAGE_DEFS:
        key = spec["key"]
        if key == "reservation" and not needs_reservation:
            stages.append(
                {
                    "key": key,
                    "title": spec["title"],
                    "state": "skipped",
                    "label": "无需预约",
                    "occurred_at": None,
                    "detail": res_ctx.get("detail") or "营业时间内凭券码直接到店核销",
                }
            )
            continue

        if key == "refund" and not refunds and order.status not in ("refunding", "refunded"):
            continue

        ev = _pick_event(by_type, spec["event_types"])
        if ev:
            stages.append(_stage_from_event(spec, ev))
            continue

        inferred = _infer_stage(order, key, refunds, res_ctx)
        if inferred:
            stages.append({**spec, **inferred})
        elif spec.get("optional"):
            stages.append(
                {
                    "key": key,
                    "title": spec["title"],
                    "state": "pending",
                    "label": "尚未发生",
                    "occurred_at": None,
                    "detail": _pending_hint(key, order, res_ctx),
                }
            )

    return stages


def _pick_event(by_type: dict[str, FulfillmentEvent], types: list[str]) -> FulfillmentEvent | None:
    for t in types:
        if t in by_type:
            return by_type[t]
    return None


def _stage_from_event(spec: dict, ev: FulfillmentEvent) -> dict:
    detail = ev.detail or {}
    label = _STATUS_LABEL.get(ev.status, ev.status)
    desc = detail.get("summary") or detail.get("note") or spec.get("desc")
    return {
        "key": spec["key"],
        "title": spec["title"],
        "state": "done" if ev.status in ("success", "approved") else ev.status,
        "label": label,
        "occurred_at": ev.created_at.isoformat(),
        "detail": desc,
        "extra": {k: v for k, v in detail.items() if k not in ("summary", "note")},
    }


def _infer_stage(order: LifeOrder, key: str, refunds: list[RefundCase], res_ctx: dict) -> dict | None:
    if key == "purchase":
        return {
            "key": key,
            "title": "购买支付",
            "state": "done",
            "label": "已完成",
            "occurred_at": order.purchase_time.isoformat() if order.purchase_time else None,
            "detail": f"实付 ¥{order.paid_amount}",
            "extra": {},
        }

    if key == "refund" and refunds:
        r = refunds[-1]
        return {
            "key": key,
            "title": "售后退款",
            "state": r.status,
            "label": _REFUND_MONEY.get(r.status, r.status),
            "occurred_at": r.created_at.isoformat() if r.created_at else None,
            "detail": f"退款 ¥{r.refundable_amount} · {r.reason}",
            "extra": {
                "refund_id": r.id,
                "money_status": _REFUND_MONEY.get(r.status, r.status),
                "estimated_finish_time": r.estimated_finish_time.isoformat() if r.estimated_finish_time else None,
            },
        }

    if key == "verify" and order.status in ("used", "refunding", "refunded") and order.service_time:
        return {
            "key": key,
            "title": "核销使用",
            "state": "done",
            "label": "已核销",
            "occurred_at": order.service_time.isoformat(),
            "detail": "到店核销完成，套餐已使用",
            "extra": {},
        }

    if key == "reservation" and res_ctx.get("needs_reservation"):
        if res_ctx.get("has_reservation") or order.status in ("scheduled", "used"):
            return {
                "key": key,
                "title": "预约到店",
                "state": "done",
                "label": "已预约",
                "occurred_at": (order.service_time - timedelta(hours=2)).isoformat() if order.service_time else None,
                "detail": f"预约到店时间 {order.service_time.strftime('%m-%d %H:%M') if order.service_time else '-'}",
                "extra": {},
            }
        return {
            "key": key,
            "title": "预约到店",
            "state": "pending",
            "label": "待预约",
            "occurred_at": None,
            "detail": str(res_ctx.get("detail") or "须提前预约成功后方可到店核销"),
            "extra": {},
        }

    return None


def _pending_hint(key: str, order: LifeOrder, res_ctx: dict) -> str:
    hints = {
        "arrive": "等待您到店",
        "verify": "待到店出示券码核销",
        "reservation": (
            "须提前预约，可在对话中说「帮我预约」"
            if res_ctx.get("needs_reservation")
            else "本套餐无需预约"
        ),
        "refund": "暂无售后",
    }
    return hints.get(key, "等待下一步")


def _synthesize_events(
    order: LifeOrder,
    existing: list[FulfillmentEvent],
    refunds: list[RefundCase],
    res_ctx: dict,
) -> list[FulfillmentEvent]:
    """若 seed 数据不完整，按订单状态补全关键节点（带合理时间）。"""
    if existing and not _looks_like_placeholder(existing):
        return existing

    meta = order.metadata_ or {}
    purchase = order.purchase_time or datetime.now(timezone.utc)
    service = order.service_time or purchase + timedelta(days=1)
    events: list[FulfillmentEvent] = []

    def _ev(etype: str, status: str, detail: dict, at: datetime) -> FulfillmentEvent:
        return FulfillmentEvent(
            order_id=order.id,
            user_id=order.user_id,
            store_id=order.store_id,
            event_type=etype,
            status=status,
            detail=detail,
            created_at=at,
        )

    events.append(
        _ev(
            "purchase",
            "success",
            {"summary": f"支付成功 ¥{order.paid_amount}", "channel": "抖音 App"},
            purchase,
        )
    )

    if res_ctx.get("needs_reservation") and res_ctx.get("has_reservation") and order.status in (
        "scheduled",
        "used",
        "refunding",
        "refunded",
    ):
        events.append(
            _ev(
                "reservation",
                "success",
                {"summary": "预约成功", "slot": service.isoformat()},
                service - timedelta(hours=24),
            )
        )

    if order.status in ("used", "refunding", "refunded"):
        events.append(_ev("arrive", "success", {"summary": "用户到店"}, service - timedelta(minutes=15)))
        events.append(
            _ev(
                "verify",
                "success",
                {"summary": "门店核销成功，套餐已使用"},
                service,
            )
        )

    if order.status in ("refunding", "refunded") and refunds:
        r = refunds[0]
        events.append(
            _ev(
                "refund",
                r.status if r.status in ("submitted", "processing", "approved", "rejected") else "processing",
                {
                    "summary": f"退款申请 {r.reason}",
                    "amount": float(r.refundable_amount),
                    "money_status": _REFUND_MONEY.get(r.status, r.status),
                },
                r.created_at or service + timedelta(hours=2),
            )
        )

    return events


def _looks_like_placeholder(events: list[FulfillmentEvent]) -> bool:
    if len(events) < 2:
        return True
    return all((ev.detail or {}).get("note", "").startswith("履约事件") for ev in events[:1])
