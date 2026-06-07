"""Fulfillment Agent — 统一 Turn Pipeline 对外入口。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.api import EdgeContextPacket
from app.services.sessions import SessionStore
from app.services.unified_turn_pipeline import UnifiedTurnPipeline


class FulfillmentAgent:
    """兼容旧类名；内部仅委托 UnifiedTurnPipeline（Plan → Gather → Compose → Emit）。"""

    def __init__(self):
        self.pipeline = UnifiedTurnPipeline()

    async def run_stream(
        self,
        db: AsyncSession,
        store: SessionStore,
        *,
        session_id: str,
        user_id: str,
        message: str,
        edge: EdgeContextPacket,
        history: list[dict],
        service_context: dict | None = None,
        on_step: Callable | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        async for event, payload in self.pipeline.run_stream(
            db,
            store,
            session_id=session_id,
            user_id=user_id,
            message=message,
            edge=edge,
            history=history,
            service_context=service_context,
            on_step=on_step,
        ):
            yield event, payload
