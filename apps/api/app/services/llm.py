import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings


class LLMService:
    def __init__(self):
        self.use_mock = not settings.openai_api_key.strip()
        self.last_error: str | None = None

    @property
    def mode(self) -> str:
        return "mock" if self.use_mock else "openai"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.openai_api_key.strip()}",
            "Content-Type": "application/json",
        }

    def _chat_payload(self, system: str, history: list[dict], user_message: str, *, stream: bool) -> dict:
        payload: dict = {
            "model": settings.openai_model.strip(),
            "messages": [{"role": "system", "content": system}, *history, {"role": "user", "content": user_message}],
            "temperature": settings.openai_temperature,
            "top_p": settings.openai_top_p,
            "max_tokens": settings.openai_max_tokens,
            "stream": stream,
        }
        return payload

    async def ping(self) -> dict:
        if self.use_mock:
            return {
                "ok": False,
                "mode": "mock",
                "reason": "OPENAI_API_KEY is empty",
                "model": settings.openai_model,
                "base_url": settings.openai_base_url,
            }

        payload = self._chat_payload(
            "你是连通性测试助手，只回复：连通成功",
            [],
            "请回复：连通成功",
            stream=False,
        )
        try:
            async with httpx.AsyncClient(
                base_url=settings.openai_base_url.strip().rstrip("/"),
                timeout=settings.openai_timeout_seconds,
            ) as client:
                resp = await client.post("/chat/completions", json=payload, headers=self._headers())
                if resp.status_code >= 400:
                    detail = resp.text[:500]
                    self.last_error = f"HTTP {resp.status_code}: {detail}"
                    hint = None
                    if "InvalidEndpointOrModel" in detail:
                        hint = (
                            "火山方舟需使用推理接入点 ID（形如 ep-xxxx）作为 OPENAI_MODEL，"
                            "请在方舟控制台「推理接入点」复制 Endpoint ID 并更新 .env"
                        )
                    return {
                        "ok": False,
                        "mode": "openai",
                        "reason": self.last_error,
                        "hint": hint,
                        "model": settings.openai_model,
                        "base_url": settings.openai_base_url,
                    }
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                self.last_error = None
                return {
                    "ok": True,
                    "mode": "openai",
                    "model": settings.openai_model,
                    "base_url": settings.openai_base_url,
                    "sample_reply": content[:120],
                    "usage": data.get("usage"),
                }
        except Exception as exc:
            self.last_error = str(exc)
            return {
                "ok": False,
                "mode": "openai",
                "reason": self.last_error,
                "model": settings.openai_model,
                "base_url": settings.openai_base_url,
            }

    async def stream_reply(self, system: str, history: list[dict], user_message: str) -> AsyncIterator[str]:
        if self.use_mock:
            async for chunk in self._mock_stream(user_message, system):
                yield chunk
            return

        payload = self._chat_payload(system, history, user_message, stream=True)
        try:
            async with httpx.AsyncClient(
                base_url=settings.openai_base_url.strip().rstrip("/"),
                timeout=settings.openai_timeout_seconds,
            ) as client:
                async with client.stream("POST", "/chat/completions", json=payload, headers=self._headers()) as resp:
                    if resp.status_code >= 400:
                        detail = await resp.aread()
                        self.last_error = f"HTTP {resp.status_code}: {detail.decode()[:500]}"
                        if settings.openai_fallback_to_mock:
                            async for chunk in self._mock_stream(user_message, system):
                                yield chunk
                            return
                        raise httpx.HTTPStatusError(
                            self.last_error,
                            request=resp.request,
                            response=resp,
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            delta = json.loads(raw)["choices"][0]["delta"].get("content")
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as exc:
            self.last_error = str(exc)
            if settings.openai_fallback_to_mock:
                async for chunk in self._mock_stream(user_message, system):
                    yield chunk
                return
            raise

    async def _mock_stream(self, user_message: str, system: str) -> AsyncIterator[str]:
        text = self._mock_reply(user_message, system)
        for i, ch in enumerate(text):
            yield ch
            if i % 4 == 0:
                import asyncio

                await asyncio.sleep(0.015)

    def _mock_reply(self, user_message: str, system: str) -> str:
        if any(k in user_message for k in ("核销失败", "扫不出来", "无法核销", "核销不了", "券用不了")):
            return (
                "我已帮你自动诊断：这张火锅双人餐券仍未使用、未过期，且适用于当前门店。"
                "问题更可能是门店扫码设备未同步券状态。你可以先点击「重新生成核销码」，"
                "如果仍失败，再让商家手动输入券码 DY8821-2468；我也可以一键联系商家或转人工。"
            )
        if any(k in user_message for k in ("券码", "团购券", "核销", "还能用", "怎么用")):
            return (
                "可以帮你看。你最近的「川巷子火锅双人餐」团购券仍未使用，券码在订单详情页可查看。"
                "该券需提前 2 小时预约，当前距到期还有约 12 天，周末可用。"
            )
        if any(k in user_message for k in ("优惠券", "不能用", "用不了", "满减")):
            return (
                "这张「电影票满 80 减 15」当前不可用，原因是电影票订单实付 78 元，未达到 80 元门槛。"
                "你可以换一笔满足门槛的电影演出订单，或查看其他可用券。"
            )
        if any(k in user_message for k in ("退款", "退掉", "售后", "退票")):
            return (
                "我已核对售后规则：未核销且未过期的团购套餐通常支持退款；电影票开场后不可退改。"
                "如果你要退「川巷子火锅双人餐」，预计可退实付 168 元。"
            )
        if any(k in user_message for k in ("营业", "几点", "地址", "电话", "预约", "改约")):
            return (
                "川巷子火锅·望京店营业时间为 10:30-22:30，地址是北京市朝阳区望京街 88 号 3 层。"
                "该套餐支持预约，建议提前 2 小时联系门店确认座位。"
            )
        if any(k in user_message for k in ("人工", "投诉", "客服")):
            return "我已为你转接人工客服，并同步订单、券和售后上下文，客服会优先处理。"
        return (
            "我可以帮你查询生活服务订单、团购券、优惠券、退款售后和门店履约信息。"
            "你可以直接问：我买的套餐还能用吗、优惠券为什么不能用、我要退款。"
        )
