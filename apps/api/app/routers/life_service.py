from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.entities import AgentOperationLog, FulfillmentEvent, User
from app.repositories.life_service import LifeOrderRepository, UserRepository, VoucherRepository
from app.schemas.api import RefundCreate, RefundOut, UserListItemOut, UserSampleOut, UserServiceContextOut, WorkflowActionRequest
from app.services.context import ServiceContextBuilder
from app.services.fulfillment_timeline import build_order_timeline
from app.services.service_records import list_service_records
from app.services.tools import LifeServiceTools

router = APIRouter(prefix="/api/v1", tags=["life-service"])
context_builder = ServiceContextBuilder()
users_repo = UserRepository()
orders = LifeOrderRepository()
vouchers = VoucherRepository()
tools = LifeServiceTools()


@router.get("/users", response_model=list[UserListItemOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = await users_repo.list_summaries(db, limit=limit, offset=offset)
    return [UserListItemOut(**row) for row in rows]


@router.get("/meta/users/count")
async def user_count(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(User))
    return {"total": int(total or 0)}


@router.get("/users/sample", response_model=UserSampleOut)
async def sample_users(
    db: AsyncSession = Depends(get_db),
    count: int = Query(10, ge=1, le=50),
    include_user_id: str | None = Query(None, description="保证出现在样本中的用户 ID"),
):
    total = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    rows = await users_repo.list_random_summaries(db, count=count, include_user_id=include_user_id)
    return UserSampleOut(
        total=total,
        sample_size=len(rows),
        users=[UserListItemOut(**row) for row in rows],
    )


@router.get("/users/{user_id}/service-context", response_model=UserServiceContextOut)
async def user_service_context(user_id: str, db: AsyncSession = Depends(get_db)):
    user = await users_repo.get(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
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
    user = await users_repo.get(db, body.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    case = await tools.create_refund_case(db, body.user_id, body.order_id, body.reason)
    await tools.operation_logs.create(
        db,
        session_id=body.session_id,
        user_id=body.user_id,
        operation_type="execute",
        actor="user",
        summary=f"用户发起退款申请 · ¥{float(case.refundable_amount)}",
        payload={
            "order_id": body.order_id,
            "amount": float(case.refundable_amount),
            "money_status": "审核中，尚未到账",
            "status": case.status,
            "refund_id": case.id,
        },
    )
    return RefundOut(
        id=case.id,
        order_id=case.order_id,
        status=case.status,
        refundable_amount=float(case.refundable_amount),
        estimated_finish_time=case.estimated_finish_time.isoformat() if case.estimated_finish_time else None,
    )


@router.get("/users/{user_id}/orders/{order_id}/fulfillment-timeline")
async def order_fulfillment_timeline(user_id: str, order_id: str, db: AsyncSession = Depends(get_db)):
    user = await users_repo.get(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return await build_order_timeline(db, user_id, order_id)


@router.get("/users/{user_id}/service-records")
async def user_service_records(user_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    user = await users_repo.get(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    records = await list_service_records(db, user_id, limit=limit)
    return {"count": len(records), "records": records}


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
    user = await users_repo.get(db, body.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return await tools.execute_workflow_action(
        db,
        body.session_id,
        body.user_id,
        body.action_id,
        body.order_id,
        body.voucher_id,
        body.payload,
    )
