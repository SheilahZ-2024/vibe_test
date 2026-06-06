"""Apply idempotent schema patches for existing databases."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.bulk_bootstrap import ensure_bulk_seed
from app.db.knowledge_bootstrap import ensure_knowledge_seed
from app.db.mock_time_shift import shift_mock_timestamps

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

# 移除 Storybook 个案知识（id 6–10 为历史预埋，已废弃）
STORY_DATA_CLEANUP = [
    "DELETE FROM agent_operation_logs WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM service_tickets WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM fulfillment_events WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM refund_cases WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM vouchers WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM coupons WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM life_orders WHERE user_id IN ('user_demo','user_story_a','user_story_b');",
    "DELETE FROM knowledge_articles WHERE id BETWEEN 6 AND 10 OR id IN (20, 21, 22);",
    "DELETE FROM users WHERE id IN ('user_demo','user_story_a','user_story_b');",
    """
    DELETE FROM merchant_stores WHERE id IN (
      'store_hotpot_001','store_cinema_001','store_massage_001',
      'store_closed_001','store_reject_001','store_reloc_001','store_nophone_001',
      'store_busy_001'
    );
    """,
]


async def apply_migrations(db: AsyncSession) -> None:
    for sql in MIGRATIONS:
        await db.execute(text(sql))
    for sql in STORY_DATA_CLEANUP:
        await db.execute(text(sql))
    await ensure_knowledge_seed(db)
    await ensure_bulk_seed(db)
    await shift_mock_timestamps(db)
    await db.commit()
