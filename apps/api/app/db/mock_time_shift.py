"""启动时将 mock 业务时间平移到当前时刻附近（seed 用 SEED_ANCHOR，启动时 mock_time_shift 对齐）。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ISO_META_KEYS = ("appointment", "pos_last_sync_at")


async def _read_anchor(db: AsyncSession) -> datetime | None:
    row = await db.scalar(
        text(
            """
            SELECT metadata->>'seed_time_anchor'
            FROM life_orders
            WHERE id = 'order_001'
            LIMIT 1
            """
        )
    )
    if not row:
        return None
    try:
        dt = datetime.fromisoformat(str(row).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


async def _ensure_anchor_from_data(db: AsyncSession) -> datetime | None:
    row = await db.scalar(
        text(
            """
            SELECT MIN(purchase_time)
            FROM life_orders
            WHERE user_id LIKE 'user_%'
            """
        )
    )
    if not row:
        return None
    anchor = row if row.tzinfo else row.replace(tzinfo=timezone.utc)
    await db.execute(
        text(
            """
            UPDATE life_orders
            SET metadata = COALESCE(metadata, '{}'::jsonb)
              || jsonb_build_object('seed_time_anchor', CAST(:anchor AS text))
            WHERE id = 'order_001'
            """
        ),
        {"anchor": anchor.isoformat()},
    )
    return anchor


async def shift_mock_timestamps(db: AsyncSession) -> None:
    users = await db.scalar(text("SELECT COUNT(*) FROM users WHERE id LIKE 'user_%'"))
    if not int(users or 0):
        return

    anchor = await _read_anchor(db) or await _ensure_anchor_from_data(db)
    if not anchor:
        return

    now = datetime.now(timezone.utc)
    jitter = timedelta(minutes=random.randint(-15, 15))
    delta = now - anchor + jitter
    seconds = delta.total_seconds()
    if abs(seconds) < 1:
        return

    interval = f"{seconds} seconds"

    await db.execute(
        text(
            f"""
            UPDATE life_orders
            SET purchase_time = purchase_time + INTERVAL '{interval}',
                service_time = CASE WHEN service_time IS NULL THEN NULL
                                    ELSE service_time + INTERVAL '{interval}' END,
                expire_time = expire_time + INTERVAL '{interval}'
            WHERE user_id LIKE 'user_%'
            """
        )
    )

    await db.execute(
        text(
            f"""
            UPDATE vouchers
            SET valid_from = valid_from + INTERVAL '{interval}',
                valid_to = valid_to + INTERVAL '{interval}'
            WHERE user_id LIKE 'user_%'
            """
        )
    )

    await db.execute(
        text(
            f"""
            UPDATE coupons
            SET valid_to = valid_to + INTERVAL '{interval}'
            WHERE user_id LIKE 'user_%'
            """
        )
    )

    await db.execute(
        text(
            f"""
            UPDATE refund_cases
            SET estimated_finish_time = CASE WHEN estimated_finish_time IS NULL THEN NULL
                                             ELSE estimated_finish_time + INTERVAL '{interval}' END,
                created_at = created_at + INTERVAL '{interval}'
            WHERE user_id LIKE 'user_%'
            """
        )
    )

    await db.execute(
        text(
            f"""
            UPDATE fulfillment_events
            SET created_at = created_at + INTERVAL '{interval}'
            WHERE user_id LIKE 'user_%'
            """
        )
    )

    for key in ISO_META_KEYS:
        await db.execute(
            text(
                f"""
                UPDATE life_orders
                SET metadata = jsonb_set(
                  metadata,
                  '{{{key}}}',
                  to_jsonb(((metadata->>'{key}')::timestamptz + INTERVAL '{interval}')::text)
                )
                WHERE user_id LIKE 'user_%'
                  AND metadata ? '{key}'
                  AND (metadata->>'{key}') ~ '^[0-9]{{4}}-'
                """
            )
        )
        await db.execute(
            text(
                f"""
                UPDATE merchant_stores
                SET metadata = jsonb_set(
                  metadata,
                  '{{{key}}}',
                  to_jsonb(((metadata->>'{key}')::timestamptz + INTERVAL '{interval}')::text)
                )
                WHERE id LIKE 'store_%'
                  AND metadata ? '{key}'
                  AND (metadata->>'{key}') ~ '^[0-9]{{4}}-'
                """
            )
        )

    await db.execute(
        text(
            """
            UPDATE life_orders
            SET metadata = COALESCE(metadata, '{}'::jsonb)
              || jsonb_build_object('seed_time_anchor', CAST(:anchor AS text))
            WHERE id = 'order_001'
            """
        ),
        {"anchor": now.isoformat()},
    )
