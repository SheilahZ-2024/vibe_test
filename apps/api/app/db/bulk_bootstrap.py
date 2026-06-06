"""Bulk mock 数据幂等补全（数据源自 deploy/init-db/03-bulk-seed.sql）。

启动 migrate 时若检测到旧版 seed（用户不足、版本号落后、或历史「每单一条退款+大量操作记录」），
会先清空 user_* 业务数据再重灌 SQL，**不会**写入诊断结论或预填 agent_operation_logs。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AgentOperationLog, RefundCase, User

BULK_SEED_MIN_USERS = 100
# v4：seed 仅含应答流程事实字段，无 diagnosis_case / demo_scenario / hint
BULK_SEED_VERSION = 4
MAX_REFUNDS_BEFORE_RESEED = 20


def _bulk_seed_path() -> Path | None:
    candidates = [Path("/seed/03-bulk-seed.sql")]
    repo_root = Path(__file__).resolve()
    for depth in (4, 3, 5):
        try:
            candidates.append(repo_root.parents[depth] / "deploy" / "init-db" / "03-bulk-seed.sql")
        except IndexError:
            continue
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _split_sql(script: str) -> list[str]:
    parts: list[str] = []
    for chunk in script.split(";"):
        lines = [ln for ln in chunk.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            parts.append(stmt)
    return parts


async def _seed_version(db: AsyncSession) -> int:
    row = await db.scalar(
        text(
            """
            SELECT COALESCE(
              (SELECT (metadata->>'bulk_seed_version')::int
               FROM life_orders WHERE id = 'order_001' LIMIT 1),
              0
            )
            """
        )
    )
    return int(row or 0)


async def _needs_reseed(db: AsyncSession) -> bool:
    users = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    if users < BULK_SEED_MIN_USERS:
        return True
    version = await _seed_version(db)
    if version >= BULK_SEED_VERSION:
        return False
    refunds = int(await db.scalar(select(func.count()).select_from(RefundCase)) or 0)
    logs = int(await db.scalar(select(func.count()).select_from(AgentOperationLog)) or 0)
    # 旧版 seed：每单一条退款 + 大量操作记录
    if refunds > MAX_REFUNDS_BEFORE_RESEED or logs > 80:
        return True
    return version < BULK_SEED_VERSION


async def _truncate_bulk_data(db: AsyncSession) -> None:
    """清除 bulk 用户数据，保留 knowledge 等全局表。"""
    stmts = [
        "DELETE FROM conversation_events WHERE user_id LIKE 'user_%'",
        "DELETE FROM agent_operation_logs WHERE user_id LIKE 'user_%'",
        "DELETE FROM fulfillment_events WHERE user_id LIKE 'user_%'",
        "DELETE FROM refund_cases WHERE user_id LIKE 'user_%'",
        "DELETE FROM service_tickets WHERE user_id LIKE 'user_%'",
        "DELETE FROM vouchers WHERE user_id LIKE 'user_%'",
        "DELETE FROM coupons WHERE user_id LIKE 'user_%'",
        "DELETE FROM life_orders WHERE user_id LIKE 'user_%'",
        "DELETE FROM merchant_stores WHERE id LIKE 'store_%'",
        "DELETE FROM users WHERE id LIKE 'user_%'",
    ]
    for sql in stmts:
        await db.execute(text(sql))


async def _stamp_seed_version(db: AsyncSession) -> None:
    ver = BULK_SEED_VERSION
    await db.execute(
        text(
            f"""
            UPDATE life_orders
            SET metadata = COALESCE(metadata, '{{}}'::jsonb)
              || jsonb_build_object('bulk_seed_version', {ver})
            WHERE id = 'order_001'
            """
        )
    )


async def ensure_bulk_seed(db: AsyncSession) -> None:
    if not await _needs_reseed(db):
        return

    path = _bulk_seed_path()
    if path is None:
        return

    users = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    if users >= BULK_SEED_MIN_USERS:
        await _truncate_bulk_data(db)

    script = path.read_text(encoding="utf-8")
    for stmt in _split_sql(script):
        await db.execute(text(stmt))

    await _stamp_seed_version(db)
