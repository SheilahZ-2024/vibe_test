"""Agent ReAct 工具执行器 — 全量实现 tool_catalog 中声明的工具。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.diagnosis import DiagnosisEngine
from app.services.agent_state import AgentState, PendingWriteAction
from app.services.tool_catalog import TOOL_CATALOG, TOOL_TO_ACTION_ID, WRITE_ACTION_TITLES, WRITE_TOOLS
from app.services.tools import LifeServiceTools


def _compact(value: Any, limit: int = 1200) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return {"truncated": True, "preview": text[:limit]}


def _slim_diagnosis(payload: dict) -> dict:
    return {
        "case_id": payload.get("case_id"),
        "case_name": payload.get("case_name"),
        "confidence": payload.get("confidence"),
        "escalation": payload.get("escalation"),
        "diagnosis": (payload.get("diagnosis") or [])[:6],
        "solution": (payload.get("solution") or [])[:4],
    }


class AgentToolExecutor:
    def __init__(self, tools: LifeServiceTools | None = None):
        self.tools = tools or LifeServiceTools()
        self.engine = DiagnosisEngine()

    async def execute(
        self,
        db: AsyncSession,
        state: AgentState,
        tool_name: str,
        action_input: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in TOOL_CATALOG:
            return {"ok": False, "error": f"未知工具 {tool_name}"}

        args = action_input or {}
        user_id = state.user_id
        session_id = state.session_id

        if tool_name == "list_orders":
            orders = state.service_context.get("orders") or []
            return {
                "ok": True,
                "count": len(orders),
                "orders": [
                    {
                        "id": o.get("id"),
                        "title": o.get("title"),
                        "status": o.get("status"),
                        "paid_amount": o.get("paid_amount"),
                    }
                    for o in orders
                ],
            }

        focus = args.get("order_id") or state.focus_order_id
        if tool_name in ("query_order", "query_store", "query_refund", "contact_merchant", "create_reservation", "apply_refund"):
            if not focus and tool_name != "query_order":
                return {"ok": False, "error": "缺少 order_id：请先 list_orders 或让用户聚焦订单"}
            if tool_name == "query_order" and not focus:
                result = await self.tools.query_order(db, user_id, None)
                return _compact({"ok": True, **result})

        if tool_name == "query_order":
            result = await self.tools.query_order(db, user_id, str(focus) if focus else None)
            if result.get("found") and result.get("order"):
                state.focus_order_id = str(result["order"].get("id") or focus)
            return _compact({"ok": True, **result})

        if tool_name == "query_voucher":
            voucher_id = args.get("voucher_id")
            order_id = args.get("order_id") or state.focus_order_id
            if not voucher_id and order_id:
                vouchers = state.service_context.get("vouchers") or []
                match = next((v for v in vouchers if str(v.get("order_id")) == str(order_id)), None)
                voucher_id = match.get("id") if match else None
            result = await self.tools.query_voucher(db, user_id, str(voucher_id) if voucher_id else None)
            return _compact({"ok": True, **result})

        if tool_name == "query_store":
            result = await self.tools.query_store(db, user_id, str(focus))
            return _compact({"ok": result.get("found", False), **result})

        if tool_name == "query_coupon":
            result = await self.tools.query_coupon(db, user_id)
            return _compact({"ok": True, **result})

        if tool_name == "query_refund":
            result = await self.tools.query_refund(db, user_id, str(focus))
            return _compact({"ok": True, **result})

        if tool_name == "query_ticket":
            result = await self.tools.query_ticket(db, user_id, session_id)
            return _compact({"ok": True, **result})

        if tool_name == "run_diagnosis":
            intent = str(args.get("intent") or state.intent_result.route_intent or "").strip()
            if intent in ("clarify", "chitchat", "unconfigured"):
                return {"ok": False, "error": f"意图 {intent} 不适合跑诊断树"}
            order_id = str(args.get("order_id") or state.focus_order_id or "")
            if not order_id:
                return {"ok": False, "error": "run_diagnosis 需要聚焦 order_id"}
            state.focus_order_id = order_id
            dx_ctx = await self.tools.build_diagnosis_context(
                db,
                user_id,
                state.message,
                state.service_context,
                focus_order_id=order_id,
            )
            state.dx_ctx = dx_ctx
            diagnosis = self.engine.diagnose(intent, dx_ctx)
            payload = _slim_diagnosis(diagnosis.to_dict())
            payload["reference_channel"] = "diagnosis_script_async"
            payload["advisory"] = True
            state.diagnosis_advisories.append(payload)
            return _compact({"ok": True, **payload})

        if tool_name in WRITE_TOOLS:
            guard = self._write_guard(state, tool_name, args)
            if guard:
                return guard
            if not args.get("user_confirmed"):
                pending = self._pending_write(state, tool_name, args, focus)
                return pending

        if tool_name == "regenerate_qr":
            voucher_id = args.get("voucher_id")
            if not voucher_id:
                return {"ok": False, "error": "regenerate_qr 需要 voucher_id"}
            result = await self.tools.regenerate_voucher_qr(db, user_id, str(voucher_id))
            await self._log_tool(db, session_id, user_id, tool_name, result)
            return _compact(result)

        if tool_name == "contact_merchant":
            result = await self.tools.contact_merchant(
                db, user_id, str(focus), str(args.get("reason") or state.message)
            )
            await self._log_tool(db, session_id, user_id, tool_name, result)
            return _compact(result)

        if tool_name == "create_reservation":
            result = await self.tools.create_reservation(
                db, user_id, str(focus), args.get("slot")
            )
            await self._log_tool(db, session_id, user_id, tool_name, result)
            return _compact(result)

        if tool_name == "apply_refund":
            result_raw = await self.tools.create_refund_case(
                db, user_id, str(focus), str(args.get("reason") or "用户申请退款")
            )
            result = {"ok": True, "refund_id": result_raw.id, "status": result_raw.status}
            await self._log_tool(db, session_id, user_id, tool_name, result)
            return _compact(result)

        if tool_name == "human_handoff":
            ticket = await self.tools.transfer_to_human(
                db,
                session_id,
                user_id,
                str(focus) if focus else None,
                {"reason": str(args.get("reason") or state.message)},
            )
            result = {"ok": True, "ticket_id": ticket.id, "priority": ticket.priority}
            await self._log_tool(db, session_id, user_id, tool_name, result)
            return _compact(result)

        return {"ok": False, "error": f"工具 {tool_name} 尚未实现"}

    @staticmethod
    def _write_guard(state: AgentState, tool_name: str, args: dict) -> dict | None:
        if tool_name == "apply_refund" and not (args.get("order_id") or state.focus_order_id):
            return {"ok": False, "error": "apply_refund 需要 order_id"}
        if tool_name in ("contact_merchant", "create_reservation") and not (args.get("order_id") or state.focus_order_id):
            return {"ok": False, "error": f"{tool_name} 需要 order_id"}
        return None

    def _pending_write(
        self,
        state: AgentState,
        tool_name: str,
        args: dict,
        focus: str | None,
    ) -> dict:
        action_id = TOOL_TO_ACTION_ID.get(tool_name, tool_name)
        title = WRITE_ACTION_TITLES.get(tool_name, tool_name)
        order_id = str(args.get("order_id") or focus or state.focus_order_id or "") or None
        voucher_id = str(args.get("voucher_id") or "") or None
        item = PendingWriteAction(
            tool=tool_name,
            action_id=action_id,
            title=title,
            description=f"写操作 {title} 需您确认后才会执行",
            order_id=order_id,
            voucher_id=voucher_id,
            payload={k: v for k, v in args.items() if k != "user_confirmed"},
        )
        if not any(p.action_id == action_id and p.order_id == order_id for p in state.pending_confirmations):
            state.pending_confirmations.append(item)
        return {
            "ok": False,
            "pending_confirmation": True,
            "reference_channel": "write_gate",
            "tool": tool_name,
            "action_id": action_id,
            "message": (
                f"{title} 需要用户确认。请在 finish.suggested_actions 中提供 "
                f'{{"action_id":"{action_id}","title":"{title}"}}，由用户点击后执行。'
            ),
        }

    async def _log_tool(self, db: AsyncSession, session_id: str, user_id: str, tool_name: str, result: dict) -> None:
        try:
            await self.tools.operation_logs.create(
                db,
                session_id=session_id,
                user_id=user_id,
                operation_type="agent_tool",
                actor="agent",
                summary=f"Agent 调用 {tool_name}",
                payload={"tool": tool_name, "result": result},
            )
        except Exception:
            await db.rollback()
