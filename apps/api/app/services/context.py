from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.life_service import (
    CouponRepository,
    LifeOrderRepository,
    RefundRepository,
    StoreRepository,
    UserRepository,
    VoucherRepository,
)
from app.schemas.api import EdgeContextPacket
from app.services.serializers import model_dict


class ServiceContextBuilder:
    def __init__(self):
        self.users = UserRepository()
        self.orders = LifeOrderRepository()
        self.vouchers = VoucherRepository()
        self.coupons = CouponRepository()
        self.refunds = RefundRepository()
        self.stores = StoreRepository()

    async def build(self, db: AsyncSession, edge: EdgeContextPacket | None, user_id: str) -> dict:
        user = await self.users.get(db, user_id)
        orders = await self.orders.list_for_user(db, user_id)
        vouchers = await self.vouchers.list_for_user(db, user_id)
        coupons = await self.coupons.list_for_user(db, user_id)
        refunds = await self.refunds.list_for_user(db, user_id)
        store_ids = {o.store_id for o in orders} | {v.store_id for v in vouchers}
        stores = await self.stores.get_many(db, store_ids)

        return {
            "edge": edge.model_dump() if edge else {},
            "user": model_dict(user, ["id", "display_name", "city", "membership_level", "phone_mask"]) if user else {},
            "orders": [
                model_dict(
                    o,
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
                    ],
                )
                for o in orders
            ],
            "vouchers": [
                model_dict(v, ["id", "order_id", "store_id", "code", "title", "status", "valid_to", "usage_rule"])
                for v in vouchers
            ],
            "coupons": [
                model_dict(
                    c,
                    [
                        "id",
                        "title",
                        "discount_amount",
                        "threshold_amount",
                        "applicable_category",
                        "status",
                        "valid_to",
                        "rule_text",
                    ],
                )
                for c in coupons
            ],
            "refunds": [
                model_dict(r, ["id", "order_id", "reason", "status", "refundable_amount", "estimated_finish_time"])
                for r in refunds
            ],
            "stores": [
                model_dict(
                    s,
                    [
                        "id",
                        "merchant_name",
                        "store_name",
                        "category",
                        "city",
                        "address",
                        "business_hours",
                        "phone",
                        "supports_reservation",
                    ],
                )
                for s in stores
            ],
        }


def context_summary(ctx: dict) -> str:
    lines = []
    user = ctx.get("user") or {}
    if user:
        lines.append(f"用户：{user.get('display_name')}，城市：{user.get('city')}，等级：{user.get('membership_level')}")
    for order in ctx.get("orders", [])[:3]:
        lines.append(
            f"订单 {order['id']}：{order['title']}，状态 {order['status']}，实付 {order['paid_amount']}，"
            f"到期 {order.get('expire_time') or '-'}"
        )
    for voucher in ctx.get("vouchers", [])[:3]:
        code = voucher.get("code")
        code_part = f"，券码 {code}" if code else ""
        lines.append(
            f"券 {voucher['id']}：{voucher['title']}，状态 {voucher['status']}{code_part}，规则：{voucher['usage_rule']}"
        )
    for coupon in ctx.get("coupons", [])[:2]:
        lines.append(f"优惠券 {coupon['id']}：{coupon['title']}，状态 {coupon['status']}，规则：{coupon['rule_text']}")
    for refund in ctx.get("refunds", [])[:2]:
        lines.append(f"售后 {refund['id']}：订单 {refund['order_id']}，状态 {refund['status']}，原因：{refund['reason']}")
    for store in ctx.get("stores", [])[:2]:
        lines.append(
            f"门店 {store['id']}：{store.get('store_name') or store.get('merchant_name')}，"
            f"营业 {store.get('business_hours') or '-'}，地址 {store.get('address') or '-'}"
        )
    return "\n".join(lines)


def context_summary_for_agent(ctx: dict, focus_order_id: str | None = None) -> str:
    """Agent Prompt 用：聚焦订单时只展开相关实体，其余压缩为一行摘要。"""
    user = ctx.get("user") or {}
    orders = ctx.get("orders") or []
    vouchers = ctx.get("vouchers") or []
    coupons = ctx.get("coupons") or []
    refunds = ctx.get("refunds") or []
    stores = ctx.get("stores") or []
    lines: list[str] = []

    if user:
        lines.append(f"用户 {user.get('display_name')}（{user.get('city')}）")

    if focus_order_id:
        if len(orders) > 1:
            lines.append(f"共 {len(orders)} 笔订单，聚焦 {focus_order_id}")
        focus = next((o for o in orders if str(o.get("id")) == str(focus_order_id)), None)
        if focus:
            lines.append(
                f"订单 {focus['id']}：{focus['title']}，{focus['status']}，实付 {focus['paid_amount']}"
            )
            store_id = focus.get("store_id")
            voucher = next((v for v in vouchers if str(v.get("order_id")) == str(focus_order_id)), None)
            if voucher:
                code = voucher.get("code")
                code_part = f"，券码 {code}" if code else ""
                lines.append(
                    f"券 {voucher['id']}：{voucher['status']}{code_part}，{str(voucher.get('usage_rule') or '')[:80]}"
                )
            if store_id:
                store = next((s for s in stores if str(s.get("id")) == str(store_id)), None)
                if store:
                    lines.append(
                        f"门店：{store.get('store_name') or store.get('merchant_name')}，"
                        f"营业 {store.get('business_hours') or '-'}"
                    )
            refund = next((r for r in refunds if str(r.get("order_id")) == str(focus_order_id)), None)
            if refund:
                lines.append(f"售后 {refund['id']}：{refund['status']}，{str(refund.get('reason') or '')[:60]}")
        if coupons:
            lines.append(f"优惠券 {len(coupons)} 张（需时用 query_coupon）")
        return "\n".join(lines) or context_summary(ctx)

    if len(orders) <= 3:
        return context_summary(ctx)

    lines.append(f"共 {len(orders)} 笔订单（未聚焦，请先 list_orders 或 clarify）")
    for order in orders[:4]:
        lines.append(f"  · {order['id']} {order['title']}（{order['status']}）")
    if len(orders) > 4:
        lines.append(f"  … 另有 {len(orders) - 4} 笔")
    if coupons:
        lines.append(f"优惠券 {len(coupons)} 张")
    return "\n".join(lines)
