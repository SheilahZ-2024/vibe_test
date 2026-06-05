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
        lines.append(f"券 {voucher['id']}：{voucher['title']}，状态 {voucher['status']}，规则：{voucher['usage_rule']}")
    for coupon in ctx.get("coupons", [])[:2]:
        lines.append(f"优惠券 {coupon['id']}：{coupon['title']}，状态 {coupon['status']}，规则：{coupon['rule_text']}")
    for refund in ctx.get("refunds", [])[:2]:
        lines.append(f"售后 {refund['id']}：订单 {refund['order_id']}，状态 {refund['status']}，原因：{refund['reason']}")
    return "\n".join(lines)
