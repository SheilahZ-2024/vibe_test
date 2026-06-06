"""ReAct 流式 JSON 解析 — 边收 token 边尝试闭合 JSON，减少非流式整段等待。"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable


def try_parse_react_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group())
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


async def accumulate_stream_json(
    chunks: AsyncIterator[str],
    *,
    on_chunk: Callable[[str], None] | None = None,
) -> tuple[str, dict | None, int | None]:
    """消费流式 chunk，返回 (全文, 首次解析成功的 dict, 首次解析耗时 ms)。"""
    import time

    buffer = ""
    parsed: dict | None = None
    first_parse_ms: int | None = None
    started = time.perf_counter()

    async for chunk in chunks:
        buffer += chunk
        if on_chunk:
            on_chunk(chunk)
        if parsed is None and "}" in buffer:
            candidate = try_parse_react_json(buffer)
            if candidate and candidate.get("action"):
                parsed = candidate
                first_parse_ms = int((time.perf_counter() - started) * 1000)

    if parsed is None and buffer:
        parsed = try_parse_react_json(buffer)
        if parsed and first_parse_ms is None:
            first_parse_ms = int((time.perf_counter() - started) * 1000)

    return buffer, parsed, first_parse_ms
