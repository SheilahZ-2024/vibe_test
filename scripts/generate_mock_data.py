"""Bulk mock 数据生成器（产出 deploy/init-db/03-bulk-seed.sql）。

本脚本只写入应答流程会查到的业务表字段（用户/门店/订单/券/优惠券/退款/履约事件），
**不预写诊断结论**（无 Case ID、hint、agent_operation_logs、对话记录）。

诊断引擎在运行时根据上述事实 + 用户话术，走 SDS v1 诊断树得出 Case。
字段对齐见 apps/api/app/diagnosis/engine.py 中 _meta() 合并后的 order/store metadata。

重新生成：
  python scripts/generate_mock_data.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "init-db" / "03-bulk-seed.sql"

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"]
CATEGORIES = ["美食", "电影演出", "休闲娱乐", "丽人美发", "酒店民宿", "KTV", "运动健身"]
MERCHANT_PREFIX = ["川巷子", "星河", "松间里", "悦食", "花间", "鹿鸣", "云栖", "青禾", "拾味", "暖居"]
SERVICE_TYPES = ["团购套餐", "电影票", "预约服务", "酒店套餐", "KTV套餐", "健身次卡"]
COUPON_STATUSES = ["available", "unavailable", "used", "expired"]

random.seed(42)
NOW = datetime.now(timezone.utc)

# 120 单 = 80 正常履约 + 9 售后 + 40 异常（等用户来问，不预填对话）
NORMAL_PLAN: list[str] = (
    ["fresh_purchase"] * 20
    + ["scheduled_soon"] * 18
    + ["verified_recent"] * 16
    + ["completed_earlier"] * 8
    + ["expired_unused"] * 9
    + ["refunding"] * 5
    + ["refunded"] * 4
)

ANOMALY_PLAN: list[str] = [
    "anomaly_merchant_reject", "anomaly_merchant_reject",
    "anomaly_merchant_campaign_end", "anomaly_merchant_campaign_end",
    "anomaly_merchant_reject_receive",
    "anomaly_scanner_unsynced", "anomaly_scanner_unsynced", "anomaly_scanner_unsynced",
    "anomaly_qr_invalid",
    "anomaly_store_closed", "anomaly_store_permanent_closed",
    "anomaly_store_relocated", "anomaly_merchant_unreachable",
    "anomaly_store_overcapacity", "anomaly_early_closure",
    "anomaly_no_reservation", "anomaly_no_reservation",
    "anomaly_reservation_denied", "anomaly_reservation_failed",
    "anomaly_off_hours", "anomaly_weekend_only", "anomaly_weekend_only",
    "anomaly_lunch_only", "anomaly_wrong_store", "anomaly_wrong_store",
    "anomaly_service_mismatch", "anomaly_service_mismatch",
    "anomaly_price_increase", "anomaly_price_increase",
    "anomaly_force_consumption", "anomaly_out_of_stock",
    "anomaly_expired_demand_refund", "anomaly_expired_demand_refund",
    "anomaly_expired_demand_verify",
    "anomaly_used_demand_refund", "anomaly_used_demand_refund",
    "anomaly_frozen_voucher",
    "anomaly_no_refund_product",
    "anomaly_used_complaint", "anomaly_used_complaint",
]

SCENARIO_PLAN: list[str] = NORMAL_PLAN + ANOMALY_PLAN

# 仅含引擎/工具链会读的事实字段；suffix 仅用于门店展示名
ANOMALY_DEFS: dict[str, dict] = {
    "anomaly_merchant_reject": {
        "suffix": "·拒核销店",
        "store_meta": {"merchant_reject": True, "scanner_synced": True},
    },
    "anomaly_merchant_campaign_end": {
        "suffix": "·声称活动结束店",
        "store_meta": {"merchant_reject": True},
    },
    "anomaly_merchant_reject_receive": {
        "suffix": "·拒接待店",
        "store_meta": {"merchant_reject": True},
    },
    "anomaly_scanner_unsynced": {
        "suffix": "·扫码异常店",
        "store_meta": {"scanner_synced": False},
    },
    "anomaly_qr_invalid": {
        "suffix": "·二维码异常店",
        "order_meta": {"qr_invalid": True},
        "store_meta": {"scanner_synced": True},
    },
    "anomaly_store_closed": {
        "suffix": "·暂停营业店",
        "store_meta": {"business_status": "suspended"},
    },
    "anomaly_store_permanent_closed": {
        "suffix": "·永久闭店",
        "store_meta": {"business_status": "permanently_closed"},
    },
    "anomaly_store_relocated": {
        "suffix": "·搬迁店",
        "store_meta": {"relocated": True},
    },
    "anomaly_merchant_unreachable": {
        "suffix": "·联系不上店",
        "store_meta": {"phone_unreachable": True},
    },
    "anomaly_store_overcapacity": {
        "suffix": "·排队超负荷店",
        "store_meta": {"over_capacity": True},
    },
    "anomaly_early_closure": {
        "suffix": "·提前打烊店",
        "store_meta": {"early_closure": True},
        "business_hours": "10:00-22:00",
    },
    "anomaly_no_reservation": {
        "suffix": "·需预约店",
        "order_meta": {"reservation_required": True, "reservation_confirmed": False},
    },
    "anomaly_reservation_denied": {
        "suffix": "·拒预约店",
        "status": "unused",
        "order_meta": {"reservation_required": True},
    },
    "anomaly_reservation_failed": {
        "suffix": "·约满店",
        "status": "unused",
        "order_meta": {"reservation_required": True},
    },
    "anomaly_off_hours": {
        "suffix": "·非全营业店",
        "status": "scheduled",
        "business_hours": "17:00-02:00",
        "order_meta": {"reservation_required": True, "reservation_confirmed": True},
    },
    "anomaly_weekend_only": {
        "suffix": "·周末限定店",
        "order_meta": {"time_restricted": True, "allowed_now": False},
    },
    "anomaly_lunch_only": {
        "suffix": "·午市限定店",
        "order_meta": {"time_restricted": True, "allowed_now": False},
    },
    "anomaly_wrong_store": {
        "suffix": "·跨店误到店",
        "order_meta": {"store_mismatch": True},
    },
    "anomaly_service_mismatch": {"suffix": "·套餐缩水店", "status": "scheduled"},
    "anomaly_price_increase": {"suffix": "·临时加价店", "status": "unused"},
    "anomaly_force_consumption": {"suffix": "·强制消费店"},
    "anomaly_out_of_stock": {"suffix": "·缺货店", "status": "scheduled"},
    "anomaly_expired_demand_refund": {
        "suffix": "·过期券",
        "status": "expired",
        "voucher_status": "expired",
        "can_refund": False,
        "order_meta": {"expired_refund_eligible": False},
    },
    "anomaly_expired_demand_verify": {
        "suffix": "·过期仍要用",
        "status": "expired",
        "voucher_status": "expired",
        "can_refund": False,
    },
    "anomaly_used_demand_refund": {
        "suffix": "·已核销争议",
        "status": "used",
        "voucher_status": "used",
        "can_refund": False,
        "reject_refund": True,
    },
    "anomaly_frozen_voucher": {
        "suffix": "·券冻结",
        "voucher_status": "frozen",
        "can_refund": False,
    },
    "anomaly_no_refund_product": {
        "suffix": "·特价不退",
        "can_refund": False,
        "order_meta": {"no_refund_product": True, "promo_non_refundable": True},
    },
    "anomaly_used_complaint": {
        "suffix": "·品质争议店",
        "status": "used",
        "voucher_status": "used",
        "can_refund": False,
        "reject_refund": True,
    },
}

USAGE_RULES: dict[str, str] = {
    "anomaly_weekend_only": "仅限周六、周日使用，工作日不可核销。",
    "anomaly_lunch_only": "仅限每日 11:00-14:00 午市使用，其他时段不可核销。",
    "anomaly_no_reservation": "须提前预约成功后方可到店核销，未预约不可使用。",
    "anomaly_off_hours": "请按预约时段到店；门店非 24 小时营业，请以详情页营业时间为准。",
    "anomaly_early_closure": "若遇门店提前结束营业，可改期或按平台规则申请售后。",
    "anomaly_store_closed": "门店暂停营业期间不可核销，恢复营业后可使用。",
    "anomaly_store_permanent_closed": "门店已永久闭店，请申请退款或联系客服转店。",
    "anomaly_merchant_reject": "到店出示抖音券码核销；若商家拒收请保留凭证并联系平台。",
    "anomaly_merchant_campaign_end": "若商家称活动结束但平台显示券有效，以平台状态为准并可投诉。",
    "anomaly_scanner_unsynced": "支持抖音码扫码或手动输入券码；若扫码失败可重新生成核销码。",
    "anomaly_wrong_store": "仅适用于购买页公示的门店列表，非适用门店不可核销。",
    "anomaly_no_refund_product": "本商品为特价促销款，标注「不可退」；未核销亦不支持自助退款。",
    "anomaly_frozen_voucher": "券暂被系统冻结，请联系平台客服处理后再核销。",
    "expired_unused": "已过期不可核销；标注过期退的商品可按平台规则处理。",
    "anomaly_expired_demand_refund": "已过期；本商品不支持过期退，无法自助退款。",
    "anomaly_expired_demand_verify": "已过期不可核销。",
    "anomaly_used_demand_refund": "已核销视为已消费，自助退款通道已关闭。",
}


def esc(value: str) -> str:
    return value.replace("'", "''")


def sql_json(data: dict) -> str:
    return esc(json.dumps(data, ensure_ascii=False))


def _voucher_status(order_status: str, scenario: str) -> str:
    spec = ANOMALY_DEFS.get(scenario, {})
    if spec.get("voucher_status"):
        return str(spec["voucher_status"])
    mapping = {
        "unused": "unused",
        "scheduled": "scheduled",
        "used": "used",
        "refunding": "refund_pending",
        "refunded": "used",
        "expired": "expired",
    }
    return mapping.get(order_status, "unused")


def service_type_needs_reservation(i: int) -> bool:
    st = SERVICE_TYPES[i % len(SERVICE_TYPES)]
    return st in ("团购套餐", "预约服务", "酒店套餐")


def _build_store(i: int, scenario: str) -> tuple:
    cat = CATEGORIES[i % len(CATEGORIES)]
    city = CITIES[i % len(CITIES)]
    merchant = f"{MERCHANT_PREFIX[i % len(MERCHANT_PREFIX)]}{cat[:2]}"
    spec = ANOMALY_DEFS.get(scenario)
    if spec:
        store_name = f"{merchant}{spec['suffix']}"
        meta = {"business_status": "open", "scanner_synced": True}
        meta.update(spec.get("store_meta") or {})
        hours = spec.get("business_hours") or random.choice(["10:00-22:00", "09:30-24:00", "11:00-23:00"])
        supports_res = scenario in (
            "anomaly_no_reservation",
            "anomaly_reservation_denied",
            "anomaly_reservation_failed",
            "anomaly_off_hours",
        )
    else:
        store_name = f"{merchant}·{city}店"
        meta = {"business_status": "open", "scanner_synced": random.random() > 0.12}
        hours = random.choice(["10:00-22:00", "09:30-24:00", "11:00-23:00", "12:00-02:00"])
        supports_res = service_type_needs_reservation(i)
    return (
        f"store_{i:03d}",
        merchant,
        store_name,
        cat,
        city,
        f"{city}市示例区示例路 {i} 号",
        hours,
        f"010-{random.randint(10000000, 99999999)}",
        supports_res,
        meta,
    )


def _build_anomaly_order(
    i: int, user_id: str, store: tuple, scenario: str, service_type: str, paid: float, original: float
) -> tuple:
    spec = ANOMALY_DEFS[scenario]
    status = str(spec.get("status", "unused"))
    purchase = NOW - timedelta(days=random.randint(1, 6))
    service_time = None
    expire = purchase + timedelta(days=random.randint(14, 35))

    if status == "scheduled":
        purchase = NOW - timedelta(days=random.randint(1, 4))
        if scenario == "anomaly_off_hours":
            service_time = NOW.replace(hour=14, minute=0, second=0, microsecond=0)
            if service_time < NOW:
                service_time += timedelta(days=1)
        else:
            service_time = NOW + timedelta(hours=random.randint(4, 36))
    elif status == "used":
        purchase = NOW - timedelta(days=random.randint(2, 6))
        service_time = NOW - timedelta(hours=random.randint(6, 72))
    elif status == "expired":
        purchase = NOW - timedelta(days=random.randint(50, 70))
        expire = NOW - timedelta(days=random.randint(1, 10))

    meta: dict = dict(spec.get("order_meta") or {})

    reservation_required = bool(
        meta.get("reservation_required")
        or service_type in ("团购套餐", "预约服务", "酒店套餐")
        or scenario.startswith("anomaly_no_reservation")
        or scenario.startswith("anomaly_reservation")
    )
    if reservation_required and "reservation_required" not in meta:
        meta["reservation_required"] = True

    can_refund = bool(spec.get("can_refund", True))
    can_reschedule = status == "scheduled" and service_type in ("电影票", "预约服务", "酒店套餐")

    return (
        f"order_{i:03d}",
        user_id,
        store[0],
        service_type,
        f"{store[1]}{service_type}",
        status,
        paid,
        original,
        purchase.isoformat(),
        service_time.isoformat() if service_time else None,
        expire.isoformat(),
        can_refund,
        can_reschedule,
        meta,
        scenario,
    )


def _build_order(i: int, user_id: str, store: tuple, scenario: str) -> tuple:
    service_type = SERVICE_TYPES[i % len(SERVICE_TYPES)]
    paid = round(random.uniform(39, 399), 2)
    original = round(paid * random.uniform(1.1, 1.6), 2)

    if scenario in ANOMALY_DEFS:
        return _build_anomaly_order(i, user_id, store, scenario, service_type, paid, original)

    reservation_required = service_type in ("团购套餐", "预约服务", "酒店套餐")

    if scenario == "fresh_purchase":
        status = "unused"
        purchase = NOW - timedelta(hours=random.randint(1, 36))
        service_time = None
        expire = purchase + timedelta(days=random.randint(14, 45))
        can_refund = True
        meta = {"reservation_required": reservation_required, "reservation_confirmed": False}

    elif scenario == "scheduled_soon":
        status = "scheduled"
        purchase = NOW - timedelta(days=random.randint(1, 5))
        service_time = NOW + timedelta(hours=random.randint(2, 48))
        expire = purchase + timedelta(days=random.randint(14, 45))
        can_refund = True
        meta = {
            "reservation_required": reservation_required,
            "reservation_confirmed": True,
            "appointment": service_time.isoformat(),
        }

    elif scenario == "verified_recent":
        status = "used"
        purchase = NOW - timedelta(days=random.randint(2, 7))
        service_time = NOW - timedelta(hours=random.randint(2, 48))
        expire = purchase + timedelta(days=random.randint(14, 45))
        can_refund = False
        meta = {"reservation_required": reservation_required, "reservation_confirmed": True}

    elif scenario == "completed_earlier":
        status = "used"
        purchase = NOW - timedelta(days=random.randint(14, 45))
        service_time = purchase + timedelta(days=random.randint(3, 10))
        expire = purchase + timedelta(days=random.randint(30, 60))
        can_refund = False
        meta = {"reservation_required": reservation_required, "reservation_confirmed": True}

    elif scenario == "expired_unused":
        status = "expired"
        purchase = NOW - timedelta(days=random.randint(45, 75))
        service_time = None
        expire = NOW - timedelta(days=random.randint(1, 14))
        can_refund = False
        meta = {"reservation_required": reservation_required}

    elif scenario == "refunding":
        status = "refunding"
        purchase = NOW - timedelta(days=random.randint(3, 10))
        service_time = purchase + timedelta(days=1)
        expire = purchase + timedelta(days=30)
        can_refund = False
        meta = {"reservation_required": reservation_required, "reservation_confirmed": True}

    elif scenario == "refunded":
        status = "refunded"
        purchase = NOW - timedelta(days=random.randint(5, 20))
        service_time = None
        expire = purchase + timedelta(days=30)
        can_refund = False
        meta = {"reservation_required": reservation_required}

    else:
        status = "unused"
        purchase = NOW - timedelta(days=1)
        service_time = None
        expire = purchase + timedelta(days=30)
        can_refund = True
        meta = {}

    can_reschedule = status == "scheduled" and service_type in ("电影票", "预约服务", "酒店套餐")

    return (
        f"order_{i:03d}",
        user_id,
        store[0],
        service_type,
        f"{store[1]}{service_type}",
        status,
        paid,
        original,
        purchase.isoformat(),
        service_time.isoformat() if service_time else None,
        expire.isoformat(),
        can_refund,
        can_reschedule,
        meta,
        scenario,
    )


def _usage_rule(scenario: str) -> str:
    return USAGE_RULES.get(scenario, "需按订单规则预约或到店核销，不可与其他优惠叠加。")


def _build_refund(order: tuple) -> tuple | None:
    scenario = order[14]
    status = order[5]
    spec = ANOMALY_DEFS.get(scenario, {})
    if spec.get("reject_refund"):
        reason = {
            "anomaly_used_complaint": "核销后服务质量与详情页严重不符",
            "anomaly_used_demand_refund": "用户坚称未使用，但系统记录已核销",
        }.get(scenario, "不符合退款规则")
        return (
            f"refund_{order[0].replace('order_', '')}",
            order[0],
            order[1],
            reason,
            "rejected",
            order[6],
            (NOW + timedelta(days=2)).isoformat(),
        )
    if status == "refunding":
        return (
            f"refund_{order[0].replace('order_', '')}",
            order[0],
            order[1],
            random.choice(["行程变更", "买多了/误购", "商家暂时无法接待"]),
            random.choice(["submitted", "processing"]),
            order[6],
            (NOW + timedelta(days=random.randint(1, 5))).isoformat(),
        )
    if status == "refunded":
        return (
            f"refund_{order[0].replace('order_', '')}",
            order[0],
            order[1],
            random.choice(["未核销自助退款", "过期自动退", "商家同意退款"]),
            "approved",
            order[6],
            (NOW - timedelta(days=random.randint(1, 3))).isoformat(),
        )
    return None


def _build_events(order: tuple) -> list[tuple]:
    oid, uid, sid, _, _, status, paid, _, purchase_iso, service_iso, _, _, meta, scenario = (
        order[0],
        order[1],
        order[2],
        order[3],
        order[4],
        order[5],
        order[6],
        order[7],
        order[8],
        order[9],
        order[10],
        order[11],
        order[13],
        order[14],
    )
    purchase = datetime.fromisoformat(purchase_iso.replace("Z", "+00:00"))
    service = (
        datetime.fromisoformat(service_iso.replace("Z", "+00:00"))
        if service_iso
        else purchase + timedelta(days=1)
    )
    spec = ANOMALY_DEFS.get(scenario, {})
    events: list[tuple] = [
        (oid, uid, sid, "purchase", "success", {"summary": f"支付成功 ¥{paid}", "channel": "抖音 App"}, purchase.isoformat()),
    ]

    if meta.get("reservation_confirmed") and status in ("scheduled", "used", "refunding"):
        events.append(
            (
                oid,
                uid,
                sid,
                "reservation",
                "success",
                {"summary": "预约成功", "slot": service.isoformat()},
                (service - timedelta(hours=24)).isoformat(),
            )
        )

    if status in ("used", "refunding") or spec.get("reject_refund"):
        events.append((oid, uid, sid, "arrive", "success", {"summary": "用户到店"}, (service - timedelta(minutes=20)).isoformat()))
        events.append(
            (oid, uid, sid, "verify", "success", {"summary": "门店核销成功，套餐已使用"}, service.isoformat())
        )

    if status in ("refunding", "refunded"):
        refund = _build_refund(order)
        if refund:
            rstatus = refund[4]
            events.append(
                (
                    oid,
                    uid,
                    sid,
                    "refund",
                    "processing" if rstatus in ("submitted", "processing") else rstatus,
                    {
                        "summary": refund[3],
                        "amount": float(paid),
                        "money_status": "退款处理中" if status == "refunding" else "退款已原路返回",
                    },
                    (service + timedelta(hours=6)).isoformat()
                    if status == "refunding"
                    else (purchase + timedelta(days=3)).isoformat(),
                )
            )

    return events


def main() -> None:
    assert len(ANOMALY_PLAN) == 40
    assert len(SCENARIO_PLAN) == 120

    lines: list[str] = [
        "-- Bulk mock data generated by scripts/generate_mock_data.py",
        "-- 仅业务事实字段；无诊断结论、无预填 agent_operation_logs / 对话",
        "-- 平台知识库见 deploy/init-db/02-knowledge-seed.sql",
        "",
    ]

    users: list[tuple] = []
    for i in range(1, 121):
        city = CITIES[i % len(CITIES)]
        users.append(
            (
                f"user_{i:03d}",
                f"用户{i:03d}",
                city,
                random.choice(["普通用户", "生活服务银卡", "生活服务金卡", "黑金会员"]),
                f"13{random.randint(0, 9)}****{random.randint(1000, 9999)}",
            )
        )
    lines.append("INSERT INTO users (id, display_name, city, membership_level, phone_mask) VALUES")
    lines.append(",\n".join(f"  ('{u[0]}', '{esc(u[1])}', '{u[2]}', '{u[3]}', '{u[4]}')" for u in users))
    lines.append("ON CONFLICT (id) DO NOTHING;\n")

    stores: list[tuple] = []
    for i in range(1, 121):
        scenario = SCENARIO_PLAN[i - 1]
        stores.append(_build_store(i, scenario))

    lines.append(
        "INSERT INTO merchant_stores (id, merchant_name, store_name, category, city, address, business_hours, phone, supports_reservation, metadata) VALUES"
    )
    lines.append(
        ",\n".join(
            f"  ('{s[0]}', '{esc(s[1])}', '{esc(s[2])}', '{s[3]}', '{s[4]}', '{esc(s[5])}', '{s[6]}', '{s[7]}', {str(s[8]).upper()}, '{sql_json(s[9])}'::jsonb)"
            for s in stores
        )
    )
    lines.append("ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, business_hours = EXCLUDED.business_hours, store_name = EXCLUDED.store_name;\n")

    orders: list[tuple] = []
    for i in range(1, 121):
        scenario = SCENARIO_PLAN[i - 1]
        orders.append(_build_order(i, f"user_{i:03d}", stores[i - 1], scenario))

    lines.append(
        "INSERT INTO life_orders (id, user_id, store_id, service_type, title, status, paid_amount, original_amount, purchase_time, service_time, expire_time, can_refund, can_reschedule, metadata) VALUES"
    )
    order_values = []
    for o in orders:
        st = f"'{o[9]}'::timestamptz" if o[9] else "NULL"
        order_values.append(
            f"  ('{o[0]}', '{o[1]}', '{o[2]}', '{esc(o[3])}', '{esc(o[4])}', '{o[5]}', {o[6]}, {o[7]}, '{o[8]}'::timestamptz, {st}, '{o[10]}'::timestamptz, {str(o[11]).upper()}, {str(o[12]).upper()}, '{sql_json(o[13])}'::jsonb)"
        )
    lines.append(",\n".join(order_values))
    lines.append("ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, metadata = EXCLUDED.metadata, service_time = EXCLUDED.service_time, can_refund = EXCLUDED.can_refund;\n")

    vouchers: list[tuple] = []
    for i, o in enumerate(orders, start=1):
        scenario = o[14]
        vouchers.append(
            (
                f"voucher_{i:03d}",
                o[0],
                o[1],
                o[2],
                f"DY{i:04d}-{random.randint(1000, 9999)}",
                o[4],
                _voucher_status(o[5], scenario),
                o[8],
                o[10],
                _usage_rule(scenario),
            )
        )
    lines.append(
        "INSERT INTO vouchers (id, order_id, user_id, store_id, code, title, status, valid_from, valid_to, usage_rule) VALUES"
    )
    lines.append(
        ",\n".join(
            f"  ('{v[0]}', '{v[1]}', '{v[2]}', '{v[3]}', '{v[4]}', '{esc(v[5])}', '{v[6]}', '{v[7]}'::timestamptz, '{v[8]}'::timestamptz, '{esc(v[9])}')"
            for v in vouchers
        )
    )
    lines.append("ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, usage_rule = EXCLUDED.usage_rule;\n")

    coupons: list[tuple] = []
    for i in range(1, 121):
        user_id = f"user_{i:03d}"
        cat = CATEGORIES[i % len(CATEGORIES)]
        coupons.append(
            (
                f"coupon_{i:03d}",
                user_id,
                f"{cat}满 {random.randint(80, 200)} 减 {random.randint(10, 50)}",
                random.randint(10, 50),
                random.randint(80, 200),
                cat,
                stores[i - 1][0] if i % 4 == 0 else None,
                COUPON_STATUSES[i % len(COUPON_STATUSES)],
                (NOW + timedelta(days=random.randint(1, 30))).isoformat(),
                "满足门槛可用，部分券不可与团购套餐叠加。",
            )
        )
    lines.append(
        "INSERT INTO coupons (id, user_id, title, discount_amount, threshold_amount, applicable_category, applicable_store_id, status, valid_to, rule_text) VALUES"
    )
    coupon_values = []
    for c in coupons:
        store_id = f"'{c[6]}'" if c[6] else "NULL"
        coupon_values.append(
            f"  ('{c[0]}', '{c[1]}', '{esc(c[2])}', {c[3]}, {c[4]}, '{c[5]}', {store_id}, '{c[7]}', '{c[8]}'::timestamptz, '{esc(c[9])}')"
        )
    lines.append(",\n".join(coupon_values))
    lines.append("ON CONFLICT (id) DO NOTHING;\n")

    refunds: list[tuple] = []
    for o in orders:
        r = _build_refund(o)
        if r:
            refunds.append(r)
    lines.append(
        "INSERT INTO refund_cases (id, order_id, user_id, reason, status, refundable_amount, estimated_finish_time) VALUES"
    )
    lines.append(
        ",\n".join(
            f"  ('{r[0]}', '{r[1]}', '{r[2]}', '{esc(r[3])}', '{r[4]}', {r[5]}, '{r[6]}'::timestamptz)" for r in refunds
        )
    )
    lines.append("ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason;\n")

    events: list[tuple] = []
    for o in orders:
        events.extend(_build_events(o))
    lines.append(
        "INSERT INTO fulfillment_events (order_id, user_id, store_id, event_type, status, detail, created_at) VALUES"
    )
    lines.append(
        ",\n".join(
            f"  ('{e[0]}', '{e[1]}', '{e[2]}', '{e[3]}', '{e[4]}', '{sql_json(e[5])}'::jsonb, '{e[6]}'::timestamptz)"
            for e in events
        )
    )
    lines.append(";\n")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"  orders={len(orders)} refunds={len(refunds)} events={len(events)} anomalies={len(ANOMALY_PLAN)}")


if __name__ == "__main__":
    main()
