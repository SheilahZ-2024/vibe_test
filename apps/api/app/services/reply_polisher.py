"""终稿语气润色 — 仅处理已确认的正文，不改事实。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import settings
from app.services.llm import LLMService

POLISH_SYSTEM = """你是抖音生活服务 AI 履约管家的语气润色器。只做轻量口语化，不重写结构：
- 更自然亲切；可酌情加 1-2 个 emoji，勿堆砌
- 金额、订单号、券码、时间、门店名、能否退款等事实必须原样保留，禁止增删改
- 禁止新增政策、承诺或步骤；不用 markdown 列表
- clarify 场景：语气温和、问题清楚

只输出润色后正文，无前缀无引号。"""


class ReplyPolisher:
    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    def should_polish(self, raw: str, *, mode: str) -> bool:
        if not settings.agent_tone_polish_enabled:
            return False
        text = raw.strip()
        if len(text) < settings.agent_tone_polish_min_chars:
            return False
        return True

    async def polish_stream(
        self,
        raw: str,
        *,
        user_message: str,
        mode: str = "reply",
        fact_constraints: str | None = None,
    ) -> AsyncIterator[str]:
        """流式润色；失败或无输出时由调用方回退原文。"""
        text = raw.strip()
        if not self.should_polish(text, mode=mode):
            async for chunk in LLMService.stream_text(text):
                yield chunk
            return

        mode_hint = "澄清场景，语气柔和。" if mode == "clarify" else "回复场景，语气专业亲切。"
        constraint_block = ""
        if fact_constraints and fact_constraints.strip():
            constraint_block = f"\n事实约束：{fact_constraints.strip()[:400]}\n"
        user_block = (
            f"{mode_hint}\n"
            f"用户：{user_message[:120]}\n"
            f"{constraint_block}"
            f"正文：\n{text[:1200]}"
        )

        got_any = False
        try:
            async for chunk in self.llm.stream_reply(
                POLISH_SYSTEM,
                [],
                user_block,
                temperature=settings.agent_tone_polish_temperature,
                max_tokens=settings.agent_tone_polish_max_tokens,
            ):
                got_any = True
                yield chunk
        except Exception:
            got_any = False

        if not got_any:
            async for chunk in LLMService.stream_text(text):
                yield chunk
