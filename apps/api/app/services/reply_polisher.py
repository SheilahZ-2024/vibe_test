"""终稿语气润色 — 仅处理已确认的正文，不改事实。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import settings
from app.services.llm import LLMService

POLISH_SYSTEM = """你是抖音生活服务 AI 履约管家的表达润色器。
你会收到助手已核对事实后的回复正文，只做语气与表达优化：
- 更自然、亲切、像真人客服；可酌情加 1-3 个 emoji（勿堆砌、勿每句都加）
- 事实必须原样保留：金额、订单号、券码、时间、门店名、能否退款、操作按钮名称等禁止改动或删除
- 禁止新增政策、承诺、步骤、工具调用结果
- 不要用 markdown 列表或标题；长度与原文接近，略长一点可以
- clarify（澄清）场景：语气温和，问题清楚，不要施压

只输出润色后的正文，不要引号包裹，不要「润色后：」等前缀。"""


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
    ) -> AsyncIterator[str]:
        """流式润色；失败或无输出时由调用方回退原文。"""
        text = raw.strip()
        if not self.should_polish(text, mode=mode):
            async for chunk in LLMService.stream_text(text):
                yield chunk
            return

        mode_hint = "用户在等澄清，语气柔和、问题具体。" if mode == "clarify" else "用户在等解决方案，语气专业但有人情味。"
        user_block = (
            f"{mode_hint}\n"
            f"用户刚说：{user_message[:200]}\n\n"
            f"待润色正文：\n{text}"
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
