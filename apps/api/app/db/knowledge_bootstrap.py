"""平台知识库幂等同步（数据源自 deploy/init-db/02-knowledge-seed.sql）。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.bulk_bootstrap import _split_sql


def _knowledge_seed_path() -> Path | None:
    candidates = [Path("/seed/02-knowledge-seed.sql")]
    repo_root = Path(__file__).resolve()
    for depth in (4, 3, 5):
        try:
            candidates.append(repo_root.parents[depth] / "deploy" / "init-db" / "02-knowledge-seed.sql")
        except IndexError:
            continue
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


async def ensure_knowledge_seed(db: AsyncSession) -> None:
    path = _knowledge_seed_path()
    if path is None:
        return
    script = path.read_text(encoding="utf-8")
    for stmt in _split_sql(script):
        await db.execute(text(stmt))
