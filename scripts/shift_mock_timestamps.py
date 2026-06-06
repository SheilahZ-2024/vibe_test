#!/usr/bin/env python3
"""CLI：将 mock 业务时间平移到当前时刻（与 API 启动时 mock_time_shift 相同逻辑）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db.mock_time_shift import shift_mock_timestamps  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


async def main() -> None:
    async with SessionLocal() as db:
        await shift_mock_timestamps(db)
        await db.commit()
    print("mock timestamps shifted to now")


if __name__ == "__main__":
    asyncio.run(main())
