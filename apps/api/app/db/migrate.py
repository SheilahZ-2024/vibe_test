"""Apply idempotent schema patches for existing databases."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MIGRATIONS = [
    """
    ALTER TABLE merchant_stores
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
    """,
    """
    CREATE TABLE IF NOT EXISTS fulfillment_events (
        id BIGSERIAL PRIMARY KEY,
        order_id VARCHAR(64) NOT NULL REFERENCES life_orders(id),
        user_id VARCHAR(64) NOT NULL REFERENCES users(id),
        store_id VARCHAR(64) NOT NULL REFERENCES merchant_stores(id),
        event_type VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL,
        detail JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fulfillment_events_user ON fulfillment_events(user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fulfillment_events_order ON fulfillment_events(order_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_operation_logs (
        id BIGSERIAL PRIMARY KEY,
        session_id VARCHAR(64),
        user_id VARCHAR(64) NOT NULL REFERENCES users(id),
        operation_type VARCHAR(64) NOT NULL,
        actor VARCHAR(16) NOT NULL,
        summary TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_operation_logs_user ON agent_operation_logs(user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_operation_logs_session ON agent_operation_logs(session_id);
    """,
]


async def apply_migrations(db: AsyncSession) -> None:
    for sql in MIGRATIONS:
        await db.execute(text(sql))
    await db.commit()
