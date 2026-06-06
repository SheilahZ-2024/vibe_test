import json
import re
from collections.abc import AsyncIterator

import httpx

from app.config import settings


class LLMService:
    """OpenAI-compatible LLM 客户端；复用 HTTP 连接以降低多轮 ReAct 时延。"""

    def __init__(self):
        self.use_mock = not settings.llm_api_key.strip()
        self.last_error: str | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def mode(self) -> str:
        return "mock" if self.use_mock else "live"

    def ensure_live(self) -> None:
        """对话主链路禁止静默降级 Mock。"""
        if self.use_mock and settings.llm_require_live:
            raise RuntimeError(
                "未配置 LLM_API_KEY，已禁用 Mock 降级。"
                "请在 .env 设置 LLM_API_KEY 与 LLM_MODEL（或推理接入点 ep-xxx）。"
            )

    def _base_url(self) -> str:
        return settings.llm_base_url.strip().rstrip("/")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url(),
                timeout=httpx.Timeout(settings.llm_timeout_seconds),
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.llm_api_key.strip()}",
            "Content-Type": "application/json",
        }

    def _chat_payload(self, system: str, history: list[dict], user_message: str, *, stream: bool) -> dict:
        payload: dict = {
            "model": settings.llm_model.strip(),
            "messages": [{"role": "system", "content": system}, *history, {"role": "user", "content": user_message}],
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "max_tokens": settings.llm_max_tokens,
            "stream": stream,
        }
        return payload

    async def ping(self) -> dict:
        if self.use_mock:
            return {
                "ok": False,
                "mode": "mock",
                "reason": "LLM_API_KEY is empty",
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
            }

        payload = self._chat_payload(
            "你是连通性测试助手，只回复：连通成功",
            [],
            "请回复：连通成功",
            stream=False,
        )
        try:
            resp = await self._get_client().post("/chat/completions", json=payload, headers=self._headers())
            if resp.status_code >= 400:
                detail = resp.text[:500]
                self.last_error = f"HTTP {resp.status_code}: {detail}"
                hint = None
                if "InvalidEndpointOrModel" in detail:
                    hint = (
                        "火山方舟需使用推理接入点 ID（形如 ep-xxxx）作为 LLM_MODEL，"
                        "请在方舟控制台「推理接入点」复制 Endpoint ID 并更新 .env"
                    )
                return {
                    "ok": False,
                    "mode": "live",
                    "reason": self.last_error,
                    "hint": hint,
                    "model": settings.llm_model,
                    "base_url": settings.llm_base_url,
                }
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            self.last_error = None
            return {
                "ok": True,
                "mode": "live",
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
                "sample_reply": content[:120],
                "usage": data.get("usage"),
            }
        except Exception as exc:
            self.last_error = str(exc)
            return {
                "ok": False,
                "mode": "live",
                "reason": self.last_error,
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
            }

    async def complete(
        self,
        system: str,
        user_message: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str | None:
        return await self.complete_with_history(system, [], user_message, temperature=temperature, max_tokens=max_tokens)

    async def complete_with_history(
        self,
        system: str,
        history: list[dict],
        user_message: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str | None:
        """非流式多轮调用，供 ReAct Agent 使用。"""
        self.ensure_live()

        payload = self._chat_payload(system, history, user_message, stream=False)
        payload["temperature"] = temperature if temperature is not None else 0.1
        payload["max_tokens"] = max_tokens if max_tokens is not None else 512

        try:
            resp = await self._get_client().post("/chat/completions", json=payload, headers=self._headers())
            if resp.status_code >= 400:
                self.last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
                return None
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            self.last_error = None
            return content
        except Exception as exc:
            self.last_error = str(exc)
            return None

    async def stream_reply(
        self,
        system: str,
        history: list[dict],
        user_message: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        self.ensure_live()

        payload = self._chat_payload(system, history, user_message, stream=True)
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            client = self._get_client()
            async with client.stream("POST", "/chat/completions", json=payload, headers=self._headers()) as resp:
                if resp.status_code >= 400:
                    detail = await resp.aread()
                    self.last_error = f"HTTP {resp.status_code}: {detail.decode()[:500]}"
                    if settings.llm_fallback_to_mock and not settings.llm_require_live:
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
            if settings.llm_fallback_to_mock and not settings.llm_require_live:
                async for chunk in self._mock_stream(user_message, system):
                    yield chunk
                return
            raise

    @staticmethod
    async def stream_text(text: str) -> AsyncIterator[str]:
        """直接流式输出已有文本（跳过终轮 LLM）。"""
        for ch in text:
            yield ch

    async def _mock_stream(self, user_message: str, system: str) -> AsyncIterator[str]:
        text = self._mock_reply(user_message, system)
        async for ch in self.stream_text(text):
            yield ch

    def _mock_reply(self, user_message: str, system: str) -> str:
        if "── 你的草稿" in system:
            draft = _parse_draft_block(system)
            if draft:
                return draft

        if "本轮你必须向用户澄清" in system or "尚不安全" in system:
            if "未聚焦" in system or "多订单" in system:
                return "我需要先确认您要处理哪一笔订单～可以在上方列表点选，或直接告诉我商品名称。"
            return "我理解您遇到的问题了，能再具体说说吗？比如是核销、查券、退款还是门店相关？"

        ctx = _parse_context_block(system)
        case_id = _parse_case_id(system)
        case_name = _parse_case_name(system)
        title = ctx.get("order_title") or "当前订单"
        paid = ctx.get("paid_amount")
        voucher_code = ctx.get("voucher_code")
        store = ctx.get("store_name") or "适用门店"
        hours = ctx.get("business_hours")
        coupon_title = ctx.get("coupon_title")
        coupon_rule = ctx.get("coupon_rule")

        if case_id == "CLARIFY" or "当前路由意图：clarify" in system:
            return (
                "我理解你遇到了问题，但还需要确认一下："
                "你是到店核销遇到问题、想查团购券/订单，还是要申请退款？告诉我最接近的一项，我马上按诊断流程帮你处理。"
            )
        if case_id == "CHITCHAT" or "当前路由意图：chitchat" in system:
            return "你好～我是你的 AI 履约服务管家。遇到核销、查券、退款或门店问题，直接跟我说就行。"

        if case_id:
            headline = f"【诊断 {case_id} {case_name or ''}】".strip()
            if case_id.startswith("FC-008"):
                code_hint = f"可让商家手动输入券码 {voucher_code}" if voucher_code else "可展示券码请商家手动核销"
                return (
                    f"{headline}「{title}」在平台侧仍有效，更可能是门店扫码设备未同步。"
                    f"建议先点「重新生成核销码」；仍失败则{code_hint}，或让我联系商家/转人工。"
                )
            if case_id.startswith("FC-006") or case_id.startswith("FC-007"):
                return (
                    f"{headline}平台侧显示「{title}」仍有效，但商家可能拒绝接待。"
                    "我会帮你联系商家核实，也可发起投诉或转人工优先处理。"
                )
            if case_id.startswith("PC-010"):
                return (
                    f"{headline}「{title}」需提前预约，当前还没有有效预约记录。"
                    "你可以点「立即预约」创建预约，或联系商家确认是否可直接接待。"
                )
            if case_id.startswith("AC-001"):
                amount = f"¥{paid}" if paid else "实付金额"
                return f"{headline}「{title}」未核销且在退款规则内，预计可退 {amount}。确认后我可以帮你提交退款申请。"

        if any(k in user_message for k in ("核销失败", "扫不出来", "无法核销", "刷不出来", "券用不了", "老板不给")):
            code_hint = f"，券码 {voucher_code}" if voucher_code else ""
            return (
                f"我已按诊断流程核对：「{title}」{code_hint}。"
                "若仍无法核销，可先重新生成核销码，或联系商家/转人工继续处理。"
            )
        if any(k in user_message for k in ("券码", "团购券", "核销", "还能用", "怎么用")):
            return (
                f"可以帮你看。「{title}」当前状态：{ctx.get('voucher_status') or '请查订单详情'}。"
                f"{(' 规则：' + ctx.get('usage_rule')) if ctx.get('usage_rule') else ''}"
            )
        if any(k in user_message for k in ("优惠券", "不能用", "用不了", "满减")) and coupon_title:
            rule = coupon_rule or "请查看优惠券使用规则"
            return f"「{coupon_title}」当前不可用。原因：{rule}。你可以换满足条件的订单或查看其他可用券。"
        if any(k in user_message for k in ("退款", "退掉", "售后", "退票")):
            amount = f"¥{paid}" if paid else "按规则核算"
            return f"我已核对售后规则。「{title}」若符合未核销/未过期等条件，预计可退 {amount}。需要的话我可以帮你提交申请。"
        if any(k in user_message for k in ("营业", "几点", "地址", "电话", "预约", "改约")):
            detail = f"{store}"
            if hours:
                detail += f" 营业时间 {hours}"
            if ctx.get("address"):
                detail += f"，地址 {ctx['address']}"
            return f"{detail}。如需预约或改约，我可以帮你查规则或联系门店。"
        if any(k in user_message for k in ("人工", "投诉", "客服")):
            return "我已为你转接人工客服，并同步订单、券和售后上下文，客服会优先处理。"
        return (
            "我可以帮你查询生活服务订单、团购券、优惠券、退款售后和门店履约信息。"
            "你可以直接描述遇到的问题，例如券用不了、想退款、查门店营业信息。"
        )


def _parse_draft_block(system: str) -> str | None:
    if "── 你的草稿" not in system:
        return None
    block = system.split("── 你的草稿", 1)[1]
    block = block.split("──", 1)[0]
    text = block.replace("（可改写润色，勿Contradict 工具事实）", "").strip()
    return text if text else None


def _parse_case_id(system: str) -> str | None:
    match = re.search(r"Case:\s*([\w-]+)", system)
    return match.group(1) if match else None


def _parse_case_name(system: str) -> str | None:
    match = re.search(r"Case:\s*[\w-]+\s+(.+?)(?:\n|$)", system)
    return match.group(1).strip() if match else None


def _parse_context_block(system: str) -> dict[str, str]:
    if "── 用户服务上下文 ──" not in system:
        return {}
    block = system.split("── 用户服务上下文 ──", 1)[1].split("── 知识库参考 ──", 1)[0]
    ctx: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("订单 ") and "：" in line:
            parts = line.split("：", 1)[1]
            title = parts.split("，状态", 1)[0].strip()
            ctx.setdefault("order_title", title)
            if "实付 " in parts:
                ctx.setdefault("paid_amount", parts.split("实付 ", 1)[1].split("，", 1)[0].strip())
        elif line.startswith("券 ") and "：" in line:
            body = line.split("：", 1)[1]
            if "，状态 " in body:
                title, rest = body.split("，状态 ", 1)
                ctx.setdefault("voucher_title", title.strip())
                status_part = rest.split("，规则：", 1)
                ctx.setdefault("voucher_status", status_part[0].strip())
                if len(status_part) > 1:
                    ctx.setdefault("usage_rule", status_part[1].strip())
            code_match = re.search(r"券码\s*([\w-]+)", line)
            if code_match:
                ctx.setdefault("voucher_code", code_match.group(1))
        elif line.startswith("门店 ") and "：" in line:
            body = line.split("：", 1)[1]
            if "，营业 " in body:
                name, rest = body.split("，营业 ", 1)
                ctx.setdefault("store_name", name.strip())
                hours_part = rest.split("，地址 ", 1)
                ctx.setdefault("business_hours", hours_part[0].strip())
                if len(hours_part) > 1:
                    ctx.setdefault("address", hours_part[1].strip())
        elif line.startswith("优惠券 ") and "：" in line:
            body = line.split("：", 1)[1]
            if "，状态 " in body:
                title, rest = body.split("，状态 ", 1)
                ctx.setdefault("coupon_title", title.strip())
                if "，规则：" in rest:
                    ctx.setdefault("coupon_rule", rest.split("，规则：", 1)[1].strip())
    return ctx
