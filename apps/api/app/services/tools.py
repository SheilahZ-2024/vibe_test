import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import RefundCase, ServiceTicket
from app.repositories.life_service import (
    CouponRepository,
    LifeOrderRepository,
    OperationLogRepository,
    RefundRepository,
    StoreRepository,
    TicketRepository,
    VoucherRepository,
)
from app.services.serializers import model_dict
from app.services.workflows import ServiceWorkflowResult, analyze_voucher_verification_failure


class LifeServiceTools:
    def __init__(self):
        self.orders = LifeOrderRepository()
        self.vouchers = VoucherRepository()
        self.coupons = CouponRepository()
        self.refunds = RefundRepository()
        self.stores = StoreRepository()
        self.tickets = TicketRepository()
        self.operation_logs = OperationLogRepository()

    async def query_order(self, db: AsyncSession, user_id: str, order_id: str | None = None) -> dict:
        order = await self.orders.get(db, order_id) if order_id else None
        if not order:
            orders = await self.orders.list_for_user(db, user_id, limit=1)
            order = orders[0] if orders else None
        if not order:
            return {"found": False}
        store = await self.stores.get(db, order.store_id)
        return {
            "found": True,
            "order": model_dict(
                order,
                [
                    "id",
                    "store_id",
                    "service_type",
                    "title",
                    "status",
                    "paid_amount",
                    "original_amount",
                    "service_time",
                    "expire_time",
                    "can_refund",
                    "can_reschedule",
                    "metadata",
                ],
            ),
            "store": model_dict(store, ["store_name", "business_hours", "address", "phone", "metadata"]) if store else None,
        }

    async def query_voucher(self, db: AsyncSession, user_id: str, voucher_id: str | None = None) -> dict:
        if voucher_id:
            voucher = await self.vouchers.get(db, voucher_id)
            vouchers = [voucher] if voucher else []
        else:
            vouchers = await self.vouchers.list_for_user(db, user_id)
        return {
            "count": len(vouchers),
            "vouchers": [
                model_dict(v, ["id", "order_id", "code", "title", "status", "valid_to", "usage_rule"])
                for v in vouchers
                if v
            ],
        }

    async def query_coupon(self, db: AsyncSession, user_id: str) -> dict:
        coupons = await self.coupons.list_for_user(db, user_id)
        unavailable = [c for c in coupons if c.status != "available"]
        target = unavailable[0] if unavailable else (coupons[0] if coupons else None)
        return {
            "count": len(coupons),
            "found": bool(target),
            "coupons": [
                model_dict(c, ["id", "title", "discount_amount", "threshold_amount", "status", "rule_text"])
                for c in coupons
            ],
            "coupon": model_dict(target, ["id", "title", "discount_amount", "threshold_amount", "status", "rule_text"])
            if target
            else None,
        }

    async def query_store(self, db: AsyncSession, user_id: str, order_id: str | None = None) -> dict:
        order_payload = await self.query_order(db, user_id, order_id)
        if not order_payload.get("found") or not order_payload.get("store"):
            return {"found": False}
        return {"found": True, "store": order_payload["store"], "order": order_payload["order"]}

    async def query_refund(self, db: AsyncSession, user_id: str, order_id: str | None = None) -> dict:
        order_payload = await self.query_order(db, user_id, order_id)
        if not order_payload.get("found"):
            return {"can_refund": False, "reason": "未找到可售后订单"}
        order = order_payload["order"]
        if order["status"] == "scheduled" and not order["can_refund"]:
            return {"can_refund": False, "reason": "该服务已预约且规则不支持退款，可尝试改签或转人工"}
        if order["status"] == "refunding":
            return {"can_refund": False, "reason": "该订单已有退款处理中"}
        if order["can_refund"]:
            return {"can_refund": True, "reason": "订单未核销且仍在有效期内，预计可按实付金额退款", "order": order}
        return {"can_refund": False, "reason": "当前订单规则不支持自助退款", "order": order}

    async def diagnose_voucher_issue(
        self,
        db: AsyncSession,
        user_id: str,
        order_id: str | None = None,
        voucher_id: str | None = None,
    ) -> dict:
        order_id = order_id or "order_hotpot_8821"
        voucher_id = voucher_id or "voucher_hotpot_8821"
        order_payload = await self.query_order(db, user_id, order_id)
        voucher_payload = await self.query_voucher(db, user_id, voucher_id)
        store_payload = await self.query_store(db, user_id, order_id)
        voucher = next((v for v in voucher_payload.get("vouchers", []) if v["id"] == voucher_id), None)
        if not voucher and voucher_payload.get("vouchers"):
            voucher = voucher_payload["vouchers"][0]

        workflow: ServiceWorkflowResult = analyze_voucher_verification_failure(
            voucher,
            order_payload.get("order"),
            store_payload.get("store"),
        )
        return {
            "issue": workflow.issue,
            "root_cause": workflow.root_cause,
            "confidence": workflow.confidence,
            "diagnosis": [
                {"check": d.check, "status": d.status, "detail": d.detail, "root_cause": d.root_cause}
                for d in workflow.diagnosis
            ],
            "solution": [{"action_id": s.action_id, "title": s.title, "description": s.description, "tool": s.tool_name} for s in workflow.solutions],
            "order": order_payload.get("order"),
            "voucher": voucher,
            "store": store_payload.get("store"),
        }

    async def regenerate_voucher_qr(self, db: AsyncSession, user_id: str, voucher_id: str) -> dict:
        voucher = await self.vouchers.get(db, voucher_id)
        if not voucher or voucher.user_id != user_id:
            return {"ok": False, "reason": "券码不存在"}
        new_code = f"{voucher.code.split('-')[0]}-{uuid.uuid4().hex[:4].upper()}"
        return {
            "ok": True,
            "voucher_id": voucher.id,
            "previous_code": voucher.code,
            "new_code": new_code,
            "qr_url": f"https://mock.douyin.local/voucher/qr/{new_code}",
            "message": "已重新生成核销二维码，请让商家重新扫码",
        }

    async def contact_merchant(self, db: AsyncSession, user_id: str, order_id: str, reason: str) -> dict:
        order_payload = await self.query_order(db, user_id, order_id)
        if not order_payload.get("found"):
            return {"ok": False, "reason": "订单不存在"}
        store = order_payload.get("store") or {}
        return {
            "ok": True,
            "store_name": store.get("store_name"),
            "phone": store.get("phone"),
            "message_sent": True,
            "reason": reason,
            "eta_minutes": 5,
            "note": "已通知商家同步券状态并协助核销",
        }

    async def create_reservation(self, db: AsyncSession, user_id: str, order_id: str, slot: str | None = None) -> dict:
        order = await self.orders.get(db, order_id)
        if not order or order.user_id != user_id:
            return {"ok": False, "reason": "订单不存在"}
        slot = slot or (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        meta = dict(order.metadata_ or {})
        meta["reservation_confirmed"] = True
        meta["appointment"] = slot
        order.metadata_ = meta
        await db.commit()
        return {"ok": True, "order_id": order_id, "appointment": slot, "message": "预约已创建，可到店核销"}

    async def create_refund_case(self, db: AsyncSession, user_id: str, order_id: str, reason: str) -> RefundCase:
        order = await self.orders.get(db, order_id)
        if not order:
            raise ValueError("订单不存在")
        case = RefundCase(
            id=f"refund_{uuid.uuid4().hex[:8]}",
            order_id=order.id,
            user_id=user_id,
            reason=reason,
            status="submitted",
            refundable_amount=order.paid_amount,
            estimated_finish_time=datetime.now(timezone.utc) + timedelta(days=1),
        )
        return await self.refunds.create(db, case)

    async def create_service_ticket(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        order_id: str | None,
        ticket_type: str,
        payload: dict,
    ) -> ServiceTicket:
        ticket = ServiceTicket(
            id=f"LS-{uuid.uuid4().hex[:8].upper()}",
            session_id=session_id,
            user_id=user_id,
            order_id=order_id,
            type=ticket_type,
            priority="high" if ticket_type in ("complaint", "verification_failed") else "normal",
            payload=payload,
        )
        return await self.tickets.create(db, ticket)

    async def transfer_to_human(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        order_id: str | None,
        payload: dict,
    ) -> ServiceTicket:
        return await self.create_service_ticket(
            db=db,
            session_id=session_id,
            user_id=user_id,
            order_id=order_id,
            ticket_type="human_handoff",
            payload=payload,
        )

    async def execute_workflow_action(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        action_id: str,
        order_id: str | None = None,
        voucher_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        payload = payload or {}
        if action_id == "regenerate_qr":
            result = await self.regenerate_voucher_qr(db, user_id, voucher_id or "voucher_hotpot_8821")
        elif action_id == "contact_merchant":
            result = await self.contact_merchant(db, user_id, order_id or "order_hotpot_8821", payload.get("reason", "核销协助"))
        elif action_id == "create_reservation":
            result = await self.create_reservation(db, user_id, order_id or "order_hotpot_8821", payload.get("slot"))
        elif action_id == "apply_refund":
            case = await self.create_refund_case(db, user_id, order_id or "order_hotpot_8821", payload.get("reason", "券无法核销申请退款"))
            result = {"ok": True, "refund_id": case.id, "status": case.status}
        elif action_id == "human_handoff":
            ticket = await self.transfer_to_human(db, session_id, user_id, order_id, payload)
            result = {"ok": True, "ticket_id": ticket.id, "priority": ticket.priority}
        elif action_id == "manual_code":
            voucher_payload = await self.query_voucher(db, user_id, voucher_id)
            voucher = voucher_payload["vouchers"][0] if voucher_payload.get("vouchers") else None
            result = {"ok": bool(voucher), "voucher": voucher, "message": "请向商家展示券码进行手动核销"}
        else:
            result = {"ok": False, "reason": f"未知动作 {action_id}"}

        await self.operation_logs.create(
            db,
            session_id=session_id,
            user_id=user_id,
            operation_type="execute",
            actor="tool",
            summary=f"执行动作 {action_id}",
            payload={"action_id": action_id, "result": result},
        )
        return result
