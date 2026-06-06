from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.migrate import apply_migrations
from app.db.session import SessionLocal, get_db
from app.routers import chat, diagnosis, life_service
from app.schemas.api import HealthOut, LLMSettingsOut
from app.services.llm import LLMService

llm = LLMService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as db:
        await apply_migrations(db)
    yield


app = FastAPI(
    title="Douyin Life Service Assistant API",
    description="抖音生活服务 C 端智能服务助手：订单、团购券、优惠券、售后、门店履约与业务办理",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(life_service.router)
app.include_router(diagnosis.router)


@app.get("/health", response_model=HealthOut)
async def health(db: AsyncSession = Depends(get_db)):
    postgres_ok = False
    redis_ok = False
    try:
        await db.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        postgres_ok = False

    redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    finally:
        await redis.aclose()

    llm_ping = {"ok": None, "mode": llm.mode}

    return HealthOut(
        status="ok" if postgres_ok and redis_ok else "degraded",
        postgres="up" if postgres_ok else "down",
        redis="up" if redis_ok else "down",
        llm_mode=llm.mode,
        llm_ok=llm_ping.get("ok"),
        llm_model=settings.llm_model,
    )


@app.get("/health/llm", response_model=LLMSettingsOut)
async def health_llm():
    ping = await llm.ping()
    return LLMSettingsOut(
        mode=ping.get("mode", llm.mode),
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        fallback_to_mock=settings.llm_fallback_to_mock,
    )


@app.get("/health/llm/ping")
async def health_llm_ping():
    return await llm.ping()
