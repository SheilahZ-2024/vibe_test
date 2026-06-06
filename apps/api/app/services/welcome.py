"""基于用户真实业务上下文生成会话欢迎语。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.context import ServiceContextBuilder
from app.services.llm import LLMService

WELCOME_SYSTEM = """你是抖音生活服务 AI 履约服务管家。用户刚进入会话，请用 1-2 句自然口语打招呼：
- 用 display_name 称呼用户（若提供）
- 只做亲切开场，不要点具体订单、券码、商品名或金额
- 邀请用户直接说需求，或在前方订单列表中点选要处理的订单
禁止编造数据；不要用列表或 markdown；语气亲切，可用少量 emoji。"""


def mock_welcome_from_context(ctx: dict) -> str:
    user = ctx.get("user") or {}
    name = str(user.get("display_name") or "你好")
    order_count = len(ctx.get("orders") or [])
    if order_count > 0:
        return f"你好 {name}～我是你的 AI 履约服务管家。你可以先点选要处理的订单，或直接告诉我遇到的问题。"
    return f"你好 {name}～我是你的 AI 履约服务管家，查订单、核销、退款、门店问题都可以问我。"


class WelcomeService:
    def __init__(self, llm: LLMService | None = None):
        self.context_builder = ServiceContextBuilder()
        self.llm = llm or LLMService()

    async def generate(self, db: AsyncSession, user_id: str) -> str:
        ctx = await self.context_builder.build(db, None, user_id)
        if not ctx.get("user"):
            raise ValueError(f"user not found: {user_id}")

        user = ctx.get("user") or {}
        name = user.get("display_name") or "用户"
        order_count = len(ctx.get("orders") or [])
        user_block = f"用户称呼：{name}\n订单数量：{order_count}（欢迎语中不要引用具体订单内容）"

        raw = await self.llm.complete(WELCOME_SYSTEM, user_block, temperature=0.65, max_tokens=160)
        if raw and raw.strip():
            return raw.strip()
        return mock_welcome_from_context(ctx)
