#!/usr/bin/env python3
"""SDS v1 Storybook 批测：诊断引擎 + 可选 Chat API。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 批测走关键词意图，避免逐条打 LLM
os.environ.setdefault("INTENT_USE_LLM", "false")

from app.diagnosis.engine import DiagnosisEngine
from app.diagnosis.registry import CASE_REGISTRY
from app.diagnosis.storybook import STORYBOOK
from app.diagnosis.types import DiagnosisContext
from app.services.intent import IntentClassifier

DEMO_ORDER = {
    "id": "order_hotpot_8821",
    "status": "unused",
    "can_refund": True,
    "paid_amount": 168.0,
    "title": "川巷子火锅双人餐",
}
DEMO_ORDERS = [DEMO_ORDER]


def ctx_for(message: str, *, with_order: bool = False) -> DiagnosisContext:
    if with_order:
        return DiagnosisContext(message=message, order=DEMO_ORDER, orders=DEMO_ORDERS)
    return DiagnosisContext(message=message, orders=DEMO_ORDERS)


@dataclass
class CaseResult:
    message: str
    expected_case: str | None
    intent: str
    case_id: str
    ok: bool
    note: str = ""


async def classify_all(classifier: IntentClassifier, messages: list[str]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        r = await classifier.classify(msg, [])
        out.append(r.route_intent)
    return out


async def run_engine_tests_async() -> list[CaseResult]:
    engine = DiagnosisEngine()
    classifier = IntentClassifier()
    results: list[CaseResult] = []

    samples: list[tuple[str, str | None, str, bool]] = [
        ("扫不出来", "FC-008", "VoucherUnavailable", True),
        ("老板不给用", "FC-006", "MerchantReject", True),
        ("店关门了", "FC-001", "StoreUnavailable", True),
        ("我要退款", "AC-001", "RefundRequest", True),
        ("吃坏肚子", "CC-008", "SafetyComplaint", False),
        ("那个有点问题", "CLARIFY", "clarify", False),
        ("付了钱没券", "PC-001", "QueryOrder", True),
        ("券过期了", "PC-005", "VoucherUnavailable", True),
        ("态度太差", "CC-003", "ServiceComplaint", False),
        ("帮我看看订单", "IC-001", "QueryOrder", False),
    ]

    intents = await classify_all(classifier, [s[0] for s in samples])
    for (message, expected_case, _, need_order), intent in zip(samples, intents):
        diag = engine.diagnose(intent, ctx_for(message, with_order=need_order))
        ok = expected_case is None or diag.case_id == expected_case or diag.case_id in (expected_case,)
        results.append(
            CaseResult(message=message, expected_case=expected_case, intent=intent, case_id=diag.case_id, ok=ok)
        )

    sb_items = [(sb_id, sb) for sb_id, sb in STORYBOOK.items()]
    sb_messages = [sb["expressions"][0] for _, sb in sb_items]
    sb_intents = await classify_all(classifier, sb_messages)

    for (sb_id, sb), expr, intent in zip(sb_items, sb_messages, sb_intents):
        expected = sb["cases"][0]
        diag = engine.diagnose(intent, ctx_for(expr, with_order=intent in ("RefundRequest", "QueryRefund", "AppealRequest")))
        ok = diag.case_id == expected or diag.case_id in sb["cases"]
        results.append(
            CaseResult(
                message=f"[{sb_id}] {expr}",
                expected_case=expected,
                intent=intent,
                case_id=diag.case_id,
                ok=ok,
                note="" if ok else f"allowed={sb['cases']}",
            )
        )

    return results


async def run_api_smoke(base_url: str) -> dict:
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
        stats = (await client.get("/api/v1/diagnosis/stats")).json()
        health = (await client.get("/health")).json()
        session = (await client.post("/api/v1/chat/sessions", json={"user_id": "user_demo"})).json()
        chat = (
            await client.post(
                "/api/v1/chat",
                json={"session_id": session["session_id"], "message": "扫不出来", "stream": False},
            )
        ).json()
        case_id = (chat.get("case") or chat.get("workflow") or {}).get("case_id")
        return {
            "health": health.get("status"),
            "total_cases": stats.get("total_cases"),
            "chat_case": case_id,
            "chat_intent": chat.get("intent"),
            "reply_len": len(chat.get("reply") or ""),
        }


async def main_async(api: str) -> int:
    print(f"Case registry: {len(CASE_REGISTRY)} cases")
    results = await run_engine_tests_async()
    passed = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]

    print(f"\nEngine + intent (keyword): {passed}/{len(results)} passed")
    for r in failed:
        print(f"  FAIL {r.message!r} -> {r.case_id} (expected {r.expected_case}) intent={r.intent} {r.note}")

    if api:
        print(f"\nAPI smoke @ {api}")
        try:
            smoke = await run_api_smoke(api.rstrip("/"))
            print(json.dumps(smoke, ensure_ascii=False, indent=2))
            if smoke.get("chat_case") != "FC-008":
                print("  WARN: chat smoke expected FC-008 for 扫不出来")
                return 1 if failed else 1
        except Exception as exc:
            print(f"  API smoke failed: {exc}")
            return 1

    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="SDS Storybook batch test")
    parser.add_argument("--api", default="", help="API base URL, e.g. http://localhost:8000")
    args = parser.parse_args()
    return asyncio.run(main_async(args.api))


if __name__ == "__main__":
    raise SystemExit(main())
