"""异常兜底 — 仅向 LLM / ReAct 智能体提供结构化线索，用户可见文案一律由模型生成。"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.services.context import context_summary
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

# 仅 LLM 不可用时使用的唯一兜底句，不含业务剧本
GENERIC_FALLBACK = "抱歉，刚才系统处理时出了点状况。请再描述一下您遇到的问题，或说「转人工」由专员帮您处理。"

RECOVERY_SYSTEM = """你是抖音生活服务 AI 履约管家。主流程在处理用户问题时发生内部异常，你需要**自行推理**原因并给出回复。

你会收到：用户原话、订单/券/门店等业务上下文、异常类型与消息、结构化线索（category 等）。
请像正常对话一样分析，例如营业时间不符、券过期、商家拒核销、门店暂停营业等——**根据上下文判断**，不要编造未提供的事实。

要求：
- 口语化中文，像真人客服；禁止暴露 Python 堆栈、字段名、HTTP 状态码、「诊断降级」等内部术语
- 给出可操作建议；信息不足时温和追问 1 个关键问题
- 不要用 markdown 标题；长度 80~240 字；可酌情 1 个 emoji
- 只输出回复正文"""


def _store_hours_text(ctx: dict | None) -> str:
    if not isinstance(ctx, dict):
        return ""
    stores = ctx.get("stores")
    if isinstance(stores, list) and stores:
        store = stores[0] if isinstance(stores[0], dict) else {}
        return str(store.get("business_hours") or "")
    store = ctx.get("store") if isinstance(ctx.get("store"), dict) else {}
    meta = store.get("metadata") if isinstance(store.get("metadata"), dict) else {}
    return str(store.get("business_hours") or meta.get("business_hours") or "")


def build_recovery_clues(
    exc: BaseException,
    *,
    message: str = "",
    service_context: dict | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """结构化线索，供 ReAct 观察或兜底 LLM 推理；不含写死的用户话术。"""
    text = f"{type(exc).__name__}: {exc}".lower()
    msg = message or ""
    clues: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc)[:400],
        "user_message": msg[:400],
        "tool_name": tool_name,
        "store_business_hours": _store_hours_text(service_context) or None,
    }

    if "hour must be in" in text or "24:00" in text:
        clues["category"] = "business_hours_parse"
        clues["suggested_intent"] = "VoucherUnavailable"
    elif "valid_to" in text or "expired" in text:
        clues["category"] = "voucher_validity"
        clues["suggested_intent"] = "VoucherUnavailable"
    elif tool_name == "run_diagnosis" or "diagnos" in text:
        clues["category"] = "diagnosis_engine_exception"
        clues["suggested_intent"] = (
            "MerchantReject"
            if any(k in msg for k in ("老板不给", "不让核销", "不让我核销", "拒绝核销"))
            else "VoucherUnavailable"
        )
    elif "用户不存在" in str(exc) or "not found" in text:
        clues["category"] = "user_context_missing"
    elif "llm" in text or "api_key" in text or "timeout" in text:
        clues["category"] = "llm_service"
    else:
        clues["category"] = "internal_error"

    return clues


def tool_error_payload(
    tool_name: str,
    exc: BaseException,
    *,
    message: str = "",
    service_context: dict | None = None,
) -> dict[str, Any]:
    """工具异常 → 结构化 observation，由 ReAct 智能体读完后自行 finish。"""
    clues = build_recovery_clues(exc, message=message, service_context=service_context, tool_name=tool_name)
    return {
        "ok": False,
        "reference_channel": "tool_exception",
        "tool": tool_name,
        "clues": clues,
        "note": (
            "工具执行异常。请结合用户表述、service_context 与上述 clues 自行分析原因，"
            "在 finish.draft_message 中给出用户可读回复；勿向用户暴露 exception_message 原文。"
        ),
    }


def _build_llm_context(
    exc: BaseException,
    *,
    message: str,
    service_context: dict | None,
    history: list[dict] | None,
    partial_trace: list[dict] | None = None,
) -> str:
    clues = build_recovery_clues(exc, message=message, service_context=service_context)
    recent = "\n".join(f"{m['role']}: {m['content'][:120]}" for m in (history or [])[-4:]) or "无"
    biz = context_summary(service_context or {}) if service_context else "（无业务上下文）"
    trace_block = ""
    if partial_trace:
        lines = []
        for t in partial_trace[-3:]:
            action = t.get("action", "?")
            obs = t.get("observation")
            obs_preview = str(obs)[:200] if obs else ""
            lines.append(f"  step {t.get('step')}: {action} → {obs_preview}")
        trace_block = "已完成的 Agent 步骤：\n" + "\n".join(lines)

    return (
        f"用户说：{message[:400]}\n\n"
        f"业务上下文：\n{biz}\n\n"
        f"异常：{clues['exception_type']}: {clues['exception_message']}\n"
        f"结构化线索：{clues}\n"
        f"{trace_block}\n"
        f"最近对话：\n{recent}"
    )


class ErrorRecoveryService:
    """主链路崩溃时的最后一道兜底——仍由 LLM 生成回复，不用业务剧本。"""

    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    async def compose_reply(
        self,
        exc: BaseException,
        *,
        message: str,
        service_context: dict | None = None,
        history: list[dict] | None = None,
        partial_trace: list[dict] | None = None,
    ) -> str:
        if not settings.error_recovery_use_llm or self.llm.use_mock:
            return GENERIC_FALLBACK

        ctx_block = _build_llm_context(
            exc,
            message=message,
            service_context=service_context,
            history=history,
            partial_trace=partial_trace,
        )
        try:
            raw = await self.llm.complete(
                RECOVERY_SYSTEM,
                ctx_block,
                temperature=settings.llm_temperature,
                max_tokens=settings.error_recovery_max_tokens,
            )
            if raw and raw.strip():
                cleaned = re.sub(r"^[\"'「」]+|[\"'「」]+$", "", raw.strip())
                if len(cleaned) >= 16:
                    return cleaned
        except Exception as llm_exc:
            logger.warning("error recovery LLM failed: %s", llm_exc)
        return GENERIC_FALLBACK

    async def recover_stream(
        self,
        exc: BaseException,
        *,
        message: str,
        service_context: dict | None = None,
        history: list[dict] | None = None,
        session_id: str = "",
        partial_trace: list[dict] | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        clues = build_recovery_clues(exc, message=message, service_context=service_context)
        yield "thinking", {"line": "主流程异常，正在根据您的订单与描述重新整理回复…"}
        yield "pipeline", {
            "session_id": session_id,
            "intent": clues.get("suggested_intent") or "clarify",
            "pipeline": {
                "steps": [
                    {"name": "error_recovery", "status": "done", "detail": f"llm_fallback ({clues.get('category')})"},
                ]
            },
            "service_cards": [],
        }

        ctx_block = _build_llm_context(
            exc,
            message=message,
            service_context=service_context,
            history=history,
            partial_trace=partial_trace,
        )

        full: list[str] = []
        if settings.error_recovery_use_llm and not self.llm.use_mock:
            got_any = False
            try:
                async for chunk in self.llm.stream_reply(
                    RECOVERY_SYSTEM,
                    history or [],
                    ctx_block,
                    temperature=settings.llm_temperature,
                    max_tokens=settings.error_recovery_max_tokens,
                ):
                    got_any = True
                    full.append(chunk)
                    yield "token", {"text": chunk}
            except Exception:
                got_any = False
            if not got_any:
                async for chunk in LLMService.stream_text(GENERIC_FALLBACK):
                    full.append(chunk)
                    yield "token", {"text": chunk}
        else:
            async for chunk in LLMService.stream_text(GENERIC_FALLBACK):
                full.append(chunk)
                yield "token", {"text": chunk}

        final = "".join(full) or GENERIC_FALLBACK
        yield "done", {
            "session_id": session_id,
            "reply": final,
            "intent": clues.get("suggested_intent") or "clarify",
            "intent_meta": {"source": "error_recovery_llm", "category": clues.get("category")},
            "pipeline": {"steps": [{"name": "error_recovery", "status": "done", "detail": "llm_fallback"}]},
            "service_cards": [],
            "tool_calls": [],
            "workflow": None,
            "case": None,
            "focus_order_id": None,
            "agent_trace": partial_trace or [],
            "agent_finish": {"mode": "reply", "draft_message": final, "safe_to_send": True},
            "pending_confirmations": [],
            "recovered_from_error": True,
        }
