"""思考区 SSE — 将真实推理文本以 thinking_token 流式推出（带轻节奏）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


async def stream_thinking_line(line: str) -> AsyncIterator[tuple[str, dict]]:
    """整句流式输出，段末双换行。"""
    text = (line or "").strip()
    if not text:
        return
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        # 中文等宽字符一次 1~2 字，英文可略快
        if ord(ch) > 127:
            step = 2 if i + 1 < length and ord(text[i + 1]) > 127 else 1
        else:
            step = 1
        chunk = text[i : i + step]
        yield "thinking_token", {"text": chunk}
        i += step
        if chunk[-1] in "。！？；":
            await asyncio.sleep(0.06)
        elif chunk[-1] in "，、：:":
            await asyncio.sleep(0.035)
        else:
            await asyncio.sleep(0.016)
    yield "thinking_token", {"text": "\n\n"}


async def stream_thinking_lines(lines: list[str]) -> AsyncIterator[tuple[str, dict]]:
    for line in lines:
        async for ev, payload in stream_thinking_line(line):
            yield ev, payload
