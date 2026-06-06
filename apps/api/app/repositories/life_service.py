from sqlalchemy import func, or_, select
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

    async def list_summaries(self, db: AsyncSession, *, limit: int = 500, offset: int = 0) -> list[dict]:
        order_counts = (
            select(LifeOrder.user_id.label("user_id"), func.count(LifeOrder.id).label("order_count"))
            .group_by(LifeOrder.user_id)
            .subquery()
        )
        voucher_counts = (
            select(Voucher.user_id.label("user_id"), func.count(Voucher.id).label("voucher_count"))
            .group_by(Voucher.user_id)
            .subquery()
        )
        q = (
            select(
                User,
                func.coalesce(order_counts.c.order_count, 0),
                func.coalesce(voucher_counts.c.voucher_count, 0),
            )
            .outerjoin(order_counts, User.id == order_counts.c.user_id)
            .outerjoin(voucher_counts, User.id == voucher_counts.c.user_id)
            .order_by(User.id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await db.execute(q)).all()
        return await self._summaries_from_rows(db, rows)

    async def list_random_summaries(
        self,
        db: AsyncSession,
        *,
        count: int = 10,
        include_user_id: str | None = None,
    ) -> list[dict]:
        order_counts = (
            select(LifeOrder.user_id.label("user_id"), func.count(LifeOrder.id).label("order_count"))
            .group_by(LifeOrder.user_id)
            .subquery()
        )
        voucher_counts = (
            select(Voucher.user_id.label("user_id"), func.count(Voucher.id).label("voucher_count"))
            .group_by(Voucher.user_id)
            .subquery()
        )
        base = (
            select(
                User,
                func.coalesce(order_counts.c.order_count, 0),
                func.coalesce(voucher_counts.c.voucher_count, 0),
            )
            .outerjoin(order_counts, User.id == order_counts.c.user_id)
            .outerjoin(voucher_counts, User.id == voucher_counts.c.user_id)
        )

        rows = (await db.execute(base.order_by(func.random()).limit(count))).all()
        summaries = await self._summaries_from_rows(db, rows)

        if include_user_id and not any(item["id"] == include_user_id for item in summaries):
            extra_rows = (await db.execute(base.where(User.id == include_user_id).limit(1))).all()
            if extra_rows:
                extra = (await self._summaries_from_rows(db, extra_rows))[0]
                if len(summaries) >= count:
                    summaries[-1] = extra
                else:
                    summaries.append(extra)

        return summaries

    async def _summaries_from_rows(self, db: AsyncSession, rows) -> list[dict]:
        summaries: list[dict] = []
        for user, order_count, voucher_count in rows:
            highlight = await self._highlight_order(db, user.id)
            summaries.append(
                {
                    "id": user.id,
                    "display_name": user.display_name,
                    "city": user.city,
                    "membership_level": user.membership_level,
                    "phone_mask": user.phone_mask,
                    "order_count": int(order_count),
                    "voucher_count": int(voucher_count),
                    "highlight_order": highlight,
                }
            )
        return summaries

    async def _highlight_order(self, db: AsyncSession, user_id: str) -> str | None:
        q = (
            select(LifeOrder.title, LifeOrder.status)
            .where(LifeOrder.user_id == user_id)
            .order_by(LifeOrder.purchase_time.desc())
            .limit(8)
        )
        rows = list((await db.execute(q)).all())
        if not rows:
            return None
        for title, status in rows:
            if status in ("unused", "scheduled", "paid_pending_voucher", "refunding"):
                return title
        return rows[0][0]


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
        return await self.search_contextual(db, query, limit=limit)

    async def search_contextual(
        self,
        db: AsyncSession,
        query: str,
        *,
        intent: str | None = None,
        order_titles: list[str] | None = None,
        limit: int = 4,
    ) -> list[KnowledgeArticle]:
        terms: list[str] = [query.strip()]
        if intent and intent not in ("clarify", "chitchat", "unconfigured"):
            terms.append(intent)
        for title in (order_titles or [])[:2]:
            if title:
                terms.append(title[:24])

        seen: set[str] = set()
        results: list[KnowledgeArticle] = []
        for term in terms:
            if not term or term in seen:
                continue
            seen.add(term)
            pattern = f"%{term}%"
            q = (
                select(KnowledgeArticle)
                .where(
                    or_(
                        KnowledgeArticle.title.ilike(pattern),
                        KnowledgeArticle.content.ilike(pattern),
                        KnowledgeArticle.category.ilike(pattern),
                        KnowledgeArticle.keywords.any(term),
                    )
                )
                .order_by(KnowledgeArticle.id.asc())
                .limit(limit)
            )
            for row in (await db.execute(q)).scalars().all():
                if row.id not in {r.id for r in results}:
                    results.append(row)
                if len(results) >= limit:
                    return results
        return results[:limit]


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
