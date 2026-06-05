import json
from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.session import get_db
from app.schemas.api import ChatRequest, ChatResponse, EdgeContextPacket, SessionCreateResponse, TicketCreate, TicketOut
from app.services.orchestrator import ChatOrchestrator
from app.services.sessions import SessionStore
from app.services.tools import LifeServiceTools

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
orchestrator = ChatOrchestrator()
tools = LifeServiceTools()


def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=False)


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(
    edge: EdgeContextPacket | None = Body(default=None),
    redis: aioredis.Redis = Depends(get_redis),
):
    user_id = (edge.user_id if edge else None) or "user_demo"
    store = SessionStore(redis)
    sid = await store.create(user_id)
    await redis.aclose()
    return SessionCreateResponse(session_id=sid, user_id=user_id)


@router.post("", response_model=ChatResponse)
async def chat_once(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    store = SessionStore(redis)
    result = await orchestrator.run_once(db, store, body)
    await redis.aclose()
    return ChatResponse(**result)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    async def events() -> AsyncIterator[dict]:
        store = SessionStore(redis)
        try:
            async for event, payload in orchestrator.run_stream(db, store, body):
                yield {"event": event, "data": json.dumps(payload, ensure_ascii=False)}
        finally:
            await redis.aclose()

    return EventSourceResponse(events())


@router.post("/tickets", response_model=TicketOut)
async def create_ticket(
    body: TicketCreate,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    store = SessionStore(redis)
    user_id = await store.get_user(body.session_id) or "user_demo"
    ticket = await tools.transfer_to_human(db, body.session_id, user_id, body.order_id, body.payload)
    await redis.aclose()
    return TicketOut(
        id=ticket.id,
        session_id=ticket.session_id,
        type=ticket.type,
        status=ticket.status,
        priority=ticket.priority,
        queue_position=3,
    )
