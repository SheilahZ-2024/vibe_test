from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    AgentOperationLog,
    Coupon,
    KnowledgeArticle,
    LifeOrder,
    MerchantStore,
    RefundCase,
    ServiceTicket,
    User,
    Voucher,
)


class UserRepository:
    async def get(self, db: AsyncSession, user_id: str) -> User | None:
        return await db.get(User, user_id)


class LifeOrderRepository:
    async def list_for_user(self, db: AsyncSession, user_id: str, limit: int = 10) -> list[LifeOrder]:
        q = (
            select(LifeOrder)
            .where(LifeOrder.user_id == user_id)
            .order_by(LifeOrder.purchase_time.desc())
            .limit(limit)
        )
        return list((await db.execute(q)).scalars().all())

    async def get(self, db: AsyncSession, order_id: str) -> LifeOrder | None:
        return await db.get(LifeOrder, order_id)


class VoucherRepository:
    async def list_for_user(self, db: AsyncSession, user_id: str) -> list[Voucher]:
        q = select(Voucher).where(Voucher.user_id == user_id).order_by(Voucher.valid_to.asc())
        return list((await db.execute(q)).scalars().all())

    async def get(self, db: AsyncSession, voucher_id: str) -> Voucher | None:
        return await db.get(Voucher, voucher_id)


class CouponRepository:
    async def list_for_user(self, db: AsyncSession, user_id: str) -> list[Coupon]:
        q = select(Coupon).where(Coupon.user_id == user_id).order_by(Coupon.valid_to.asc())
        return list((await db.execute(q)).scalars().all())


class RefundRepository:
    async def list_for_user(self, db: AsyncSession, user_id: str) -> list[RefundCase]:
        q = select(RefundCase).where(RefundCase.user_id == user_id).order_by(RefundCase.created_at.desc())
        return list((await db.execute(q)).scalars().all())

    async def create(self, db: AsyncSession, case: RefundCase) -> RefundCase:
        db.add(case)
        await db.commit()
        await db.refresh(case)
        return case


class StoreRepository:
    async def get_many(self, db: AsyncSession, store_ids: set[str]) -> list[MerchantStore]:
        if not store_ids:
            return []
        q = select(MerchantStore).where(MerchantStore.id.in_(store_ids))
        return list((await db.execute(q)).scalars().all())

    async def get(self, db: AsyncSession, store_id: str) -> MerchantStore | None:
        return await db.get(MerchantStore, store_id)


class KnowledgeRepository:
    async def search(self, db: AsyncSession, query: str, limit: int = 4) -> list[KnowledgeArticle]:
        pattern = f"%{query}%"
        q = (
            select(KnowledgeArticle)
            .where(
                or_(
                    KnowledgeArticle.title.ilike(pattern),
                    KnowledgeArticle.content.ilike(pattern),
                    KnowledgeArticle.category.ilike(pattern),
                )
            )
            .limit(limit)
        )
        return list((await db.execute(q)).scalars().all())


class TicketRepository:
    async def create(self, db: AsyncSession, ticket: ServiceTicket) -> ServiceTicket:
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)
        return ticket


class OperationLogRepository:
    async def create(
        self,
        db: AsyncSession,
        *,
        session_id: str | None,
        user_id: str,
        operation_type: str,
        actor: str,
        summary: str,
        payload: dict | None = None,
    ) -> AgentOperationLog:
        row = AgentOperationLog(
            session_id=session_id,
            user_id=user_id,
            operation_type=operation_type,
            actor=actor,
            summary=summary,
            payload=payload or {},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row
