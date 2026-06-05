from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.entities import AgentOperationLog, FulfillmentEvent
from app.repositories.life_service import LifeOrderRepository, VoucherRepository
from app.schemas.api import RefundCreate, RefundOut, UserServiceContextOut, WorkflowActionRequest
from app.services.context import ServiceContextBuilder
from app.services.tools import LifeServiceTools

router = APIRouter(prefix="/api/v1", tags=["life-service"])
context_builder = ServiceContextBuilder()
orders = LifeOrderRepository()
vouchers = VoucherRepository()
tools = LifeServiceTools()


@router.get("/users/{user_id}/service-context", response_model=UserServiceContextOut)
async def user_service_context(user_id: str, db: AsyncSession = Depends(get_db)):
    ctx = await context_builder.build(db, None, user_id)
    return UserServiceContextOut(
        user=ctx["user"],
        orders=ctx["orders"],
        vouchers=ctx["vouchers"],
        coupons=ctx["coupons"],
        refunds=ctx["refunds"],
        stores=ctx["stores"],
    )


@router.get("/orders/{order_id}")
async def order_detail(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await orders.get(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return await tools.query_order(db, order.user_id, order_id)


@router.get("/vouchers/{voucher_id}")
async def voucher_detail(voucher_id: str, db: AsyncSession = Depends(get_db)):
    voucher = await vouchers.get(db, voucher_id)
    if not voucher:
        raise HTTPException(404, "Voucher not found")
    return {
        "id": voucher.id,
        "order_id": voucher.order_id,
        "code": voucher.code,
        "title": voucher.title,
        "status": voucher.status,
        "valid_to": voucher.valid_to.isoformat(),
        "usage_rule": voucher.usage_rule,
    }


@router.post("/refunds", response_model=RefundOut)
async def create_refund(body: RefundCreate, db: AsyncSession = Depends(get_db)):
    case = await tools.create_refund_case(db, "user_demo", body.order_id, body.reason)
    return RefundOut(
        id=case.id,
        order_id=case.order_id,
        status=case.status,
        refundable_amount=float(case.refundable_amount),
        estimated_finish_time=case.estimated_finish_time.isoformat() if case.estimated_finish_time else None,
    )


@router.get("/users/{user_id}/fulfillment-events")
async def fulfillment_events(user_id: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    q = (
        select(FulfillmentEvent)
        .where(FulfillmentEvent.user_id == user_id)
        .order_by(FulfillmentEvent.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(q)).scalars().all())
    return {
        "count": len(rows),
        "events": [
            {
                "id": row.id,
                "order_id": row.order_id,
                "store_id": row.store_id,
                "event_type": row.event_type,
                "status": row.status,
                "detail": row.detail,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/users/{user_id}/operation-logs")
async def operation_logs(user_id: str, session_id: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)):
    q = select(AgentOperationLog).where(AgentOperationLog.user_id == user_id)
    if session_id:
        q = q.where(AgentOperationLog.session_id == session_id)
    q = q.order_by(AgentOperationLog.created_at.desc()).limit(limit)
    rows = list((await db.execute(q)).scalars().all())
    return {
        "count": len(rows),
        "logs": [
            {
                "id": row.id,
                "session_id": row.session_id,
                "operation_type": row.operation_type,
                "actor": row.actor,
                "summary": row.summary,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.post("/workflow/actions")
async def execute_workflow_action(body: WorkflowActionRequest, db: AsyncSession = Depends(get_db)):
    user_id = "user_demo"
    result = await tools.execute_workflow_action(
        db,
        body.session_id,
        user_id,
        body.action_id,
        body.order_id,
        body.voucher_id,
        body.payload,
    )
    return result
