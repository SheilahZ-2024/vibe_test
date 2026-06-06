"""Bulk mock 数据生成器 → deploy/init-db/03-bulk-seed.sql

原则：
- 只写入平台/商家/用户侧**客观事实**（订单状态、券规则文案、POI 营业状态、履约事件、退款记录等）
- **禁止**诊断捷径标签（merchant_reject、store_mismatch、time_restricted 等）
- 时间以 SEED_ANCHOR 为基准写入相对偏移；API 启动时 mock_time_shift 平移到真实「现在」

重新生成：python scripts/generate_mock_data.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "init-db" / "03-bulk-seed.sql"

SEED_ANCHOR = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"]
CATEGORIES = ["美食", "电影演出", "休闲娱乐", "丽人美发", "酒店民宿", "KTV", "运动健身"]
MERCHANT_PREFIX = ["川巷子", "星河", "松间里", "悦食", "花间", "鹿鸣", "云栖", "青禾", "拾味", "暖居"]
SERVICE_TYPES = ["团购套餐", "电影票", "预约服务", "酒店套餐", "KTV套餐", "健身次卡"]
COUPON_STATUSES = ["available", "unavailable", "used", "expired"]

random.seed(42)
NOW = SEED_ANCHOR

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

# suffix=展示名；其余字段均为可观测事实，非诊断结论
ANOMALY_DEFS: dict[str, dict] = {
    "anomaly_merchant_reject": {"suffix": "·商圈店"},
    "anomaly_merchant_campaign_end": {"suffix": "·活动门店"},
    "anomaly_merchant_reject_receive": {"suffix": "·临街店"},
    "anomaly_scanner_unsynced": {
        "suffix": "·POS待同步店",
        "store_meta": {"pos_last_sync_at": (NOW - timedelta(hours=72)).isoformat()},
    },
    "anomaly_qr_invalid": {
        "suffix": "·核销设备店",
        "store_meta": {"pos_last_sync_at": (NOW - timedelta(hours=48)).isoformat()},
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
        "suffix": "·搬迁新店",
        "store_meta": {"previous_address": "示例路 88 号（旧址）"},
    },
    "anomaly_merchant_unreachable": {"suffix": "·远郊店"},
    "anomaly_store_overcapacity": {"suffix": "·热门店"},
    "anomaly_early_closure": {
        "suffix": "·当日早收店",
        "business_hours": "10:00-22:00",
        "store_meta": {"today_hours": "10:00-14:00"},
    },
    "anomaly_no_reservation": {
        "suffix": "·需预约店",
        "supports_reservation": True,
        "usage_rule_key": "must_reserve",
        "skip_reservation": True,
    },
    "anomaly_reservation_denied": {
        "suffix": "·预约门店",
        "status": "unused",
        "supports_reservation": True,
        "usage_rule_key": "must_reserve",
        "skip_reservation": True,
    },
    "anomaly_reservation_failed": {
        "suffix": "·约满门店",
        "status": "unused",
        "supports_reservation": True,
        "usage_rule_key": "must_reserve",
        "skip_reservation": True,
    },
    "anomaly_off_hours": {
        "suffix": "·夜间营业店",
        "status": "scheduled",
        "business_hours": "17:00-02:00",
        "supports_reservation": True,
        "usage_rule_key": "must_reserve",
        "service_time_offset_hours": 4,
    },
    "anomaly_weekend_only": {"suffix": "·周末店", "usage_rule_key": "weekend_only"},
    "anomaly_lunch_only": {"suffix": "·午市店", "usage_rule_key": "lunch_only"},
    "anomaly_wrong_store": {"suffix": "·A店", "wrong_store": True},
    "anomaly_service_mismatch": {"suffix": "·套餐店", "status": "scheduled"},
    "anomaly_price_increase": {"suffix": "·加价争议店", "status": "unused"},
    "anomaly_force_consumption": {"suffix": "·高消店"},
    "anomaly_out_of_stock": {"suffix": "·热销店", "status": "scheduled"},
    "anomaly_expired_demand_refund": {
        "suffix": "·过期券",
        "status": "expired",
        "voucher_status": "expired",
        "can_refund": False,
        "usage_rule_key": "expired_no_refund",
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
        "suffix": "·风控冻结",
        "voucher_status": "frozen",
        "can_refund": False,
    },
    "anomaly_no_refund_product": {
        "suffix": "·特价不退",
        "can_refund": False,
        "usage_rule_key": "no_refund",
    },
    "anomaly_used_complaint": {
        "suffix": "·品质争议",
        "status": "used",
        "voucher_status": "used",
        "can_refund": False,
        "reject_refund": True,
    },
}

USAGE_RULES: dict[str, str] = {
    "must_reserve": "须提前预约成功后方可到店核销，未预约不可使用。",
    "weekend_only": "仅限周六、周日使用，工作日不可核销。",
    "lunch_only": "仅限每日 11:00-14:00 午市使用，其他时段不可核销。",
    "no_refund": "本商品为特价促销款，标注「不可退」；未核销亦不支持自助退款。",
    "expired_no_refund": "已过期；本商品不支持过期退，无法自助退款。",
    "expired_unused": "已过期不可核销；标注过期退的商品可按平台规则处理。",
    "default": "需按订单规则预约或到店核销，不可与其他优惠叠加。",
}


def esc(value: str) -> str:
    return value.replace("'", "''")


def sql_json(data: dict) -> str:
    return esc(json.dumps(data, ensure_ascii=False))


def service_type_needs_reservation(i: int) -> bool:
    return SERVICE_TYPES[i % len(SERVICE_TYPES)] in ("团购套餐", "预约服务", "酒店套餐")


def _voucher_status(order_status: str, scenario: str) -> str:
    spec = ANOMALY_DEFS.get(scenario, {})
    if spec.get("voucher_status"):
        return str(spec["voucher_status"])
    return {
        "unused": "unused",
        "scheduled": "scheduled",
        "used": "used",
        "refunding": "refund_pending",
        "refunded": "used",
        "expired": "expired",
    }.get(order_status, "unused")


def _usage_rule(scenario: str) -> str:
    spec = ANOMALY_DEFS.get(scenario, {})
    key = spec.get("usage_rule_key")
    if key and key in USAGE_RULES:
        return USAGE_RULES[key]
    if scenario == "expired_unused":
        return USAGE_RULES["expired_unused"]
    return USAGE_RULES["default"]


def _build_store(i: int, scenario: str) -> tuple:
    cat = CATEGORIES[i % len(CATEGORIES)]
    city = CITIES[i % len(CITIES)]
    merchant = f"{MERCHANT_PREFIX[i % len(MERCHANT_PREFIX)]}{cat[:2]}"
    spec = ANOMALY_DEFS.get(scenario, {})
    store_name = f"{merchant}{spec.get('suffix', f'·{city}店')}"
    meta: dict = {"business_status": "open"}
    meta.update(spec.get("store_meta") or {})
    hours = spec.get("business_hours") or random.choice(["10:00-22:00", "09:30-24:00", "11:00-23:00"])
    supports_res = bool(spec.get("supports_reservation")) or (
        not spec and service_type_needs_reservation(i)
    )
    address = f"{city}市示例区示例路 {i} 号"
    if scenario == "anomaly_store_relocated":
        address = f"{city}市示例区新路 {i} 号"
    return (
        f"store_{i:03d}",
        merchant,
        store_name,
        cat,
        city,
        address,
        hours,
        f"010-{random.randint(10000000, 99999999)}",
        supports_res,
        meta,
    )


def _build_anomaly_order(i: int, user_id: str, store: tuple, scenario: str, service_type: str, paid: float, original: float) -> tuple:
    spec = ANOMALY_DEFS[scenario]
    status = str(spec.get("status", "unused"))
    purchase = NOW - timedelta(days=random.randint(1, 6))
    service_time = None
    expire = purchase + timedelta(days=random.randint(14, 35))
    meta: dict = {}

    if status == "scheduled":
        purchase = NOW - timedelta(days=random.randint(1, 4))
        offset_h = int(spec.get("service_time_offset_hours", random.randint(4, 36)))
        service_time = NOW + timedelta(hours=offset_h)
    elif status == "used":
        purchase = NOW - timedelta(days=random.randint(2, 6))
        service_time = NOW - timedelta(hours=random.randint(6, 72))
    elif status == "expired":
        purchase = NOW - timedelta(days=random.randint(50, 70))
        expire = NOW - timedelta(days=random.randint(1, 10))

    if status == "scheduled" and spec.get("usage_rule_key") == "must_reserve" and not spec.get("skip_reservation"):
        meta["reservation_confirmed"] = True
        meta["appointment"] = service_time.isoformat() if service_time else (NOW + timedelta(hours=24)).isoformat()

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

    if scenario == "fresh_purchase":
        status, purchase = "unused", NOW - timedelta(hours=random.randint(1, 36))
        service_time, expire = None, purchase + timedelta(days=random.randint(14, 45))
        can_refund, meta = True, {}

    elif scenario == "scheduled_soon":
        status = "scheduled"
        purchase = NOW - timedelta(days=random.randint(1, 5))
        service_time = NOW + timedelta(hours=random.randint(2, 48))
        expire = purchase + timedelta(days=random.randint(14, 45))
        can_refund = True
        meta = {"reservation_confirmed": True, "appointment": service_time.isoformat()}

    elif scenario == "verified_recent":
        status = "used"
        purchase = NOW - timedelta(days=random.randint(2, 7))
        service_time = NOW - timedelta(hours=random.randint(2, 48))
        expire = purchase + timedelta(days=random.randint(14, 45))
        can_refund, meta = False, {"reservation_confirmed": True}

    elif scenario == "completed_earlier":
        status = "used"
        purchase = NOW - timedelta(days=random.randint(14, 45))
        service_time = purchase + timedelta(days=random.randint(3, 10))
        expire = purchase + timedelta(days=random.randint(30, 60))
        can_refund, meta = False, {"reservation_confirmed": True}

    elif scenario == "expired_unused":
        status = "expired"
        purchase = NOW - timedelta(days=random.randint(45, 75))
        service_time, expire = None, NOW - timedelta(days=random.randint(1, 14))
        can_refund, meta = False, {}

    elif scenario == "refunding":
        status = "refunding"
        purchase = NOW - timedelta(days=random.randint(3, 10))
        service_time = purchase + timedelta(days=1)
        expire = purchase + timedelta(days=30)
        can_refund, meta = False, {"reservation_confirmed": True}

    elif scenario == "refunded":
        status, purchase = "refunded", NOW - timedelta(days=random.randint(5, 20))
        service_time, expire = None, purchase + timedelta(days=30)
        can_refund, meta = False, {}

    else:
        status, purchase = "unused", NOW - timedelta(days=1)
        service_time, expire = None, purchase + timedelta(days=30)
        can_refund, meta = True, {}

    if i == 1:
        meta = {**meta, "seed_time_anchor": SEED_ANCHOR.isoformat()}

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


def _voucher_store_id(order: tuple, scenario: str, stores: list[tuple]) -> str:
    order_store = order[2]
    if scenario == "anomaly_wrong_store":
        idx = int(order_store.replace("store_", ""))
        alt = max(1, idx - 1)
        return f"store_{alt:03d}"
    return order_store


def _build_refund(order: tuple) -> tuple | None:
    scenario, status = order[14], order[5]
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
    oid, uid, sid = order[0], order[1], order[2]
    status, paid = order[5], order[6]
    purchase_iso, service_iso, meta, scenario = order[8], order[9], order[13], order[14]
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
        events.append((oid, uid, sid, "verify", "success", {"summary": "门店核销成功，套餐已使用"}, service.isoformat()))

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
    assert len(ANOMALY_PLAN) == 40 and len(SCENARIO_PLAN) == 120

    lines = [
        "-- Generated by scripts/generate_mock_data.py",
        "-- 客观业务事实 only；时间锚点见 order_001.metadata.seed_time_anchor，启动时 mock_time_shift 对齐",
        "",
    ]

    users = [
        (
            f"user_{i:03d}",
            f"用户{i:03d}",
            CITIES[i % len(CITIES)],
            random.choice(["普通用户", "生活服务银卡", "生活服务金卡", "黑金会员"]),
            f"13{random.randint(0, 9)}****{random.randint(1000, 9999)}",
        )
        for i in range(1, 121)
    ]
    lines += [
        "INSERT INTO users (id, display_name, city, membership_level, phone_mask) VALUES",
        ",\n".join(f"  ('{u[0]}', '{esc(u[1])}', '{u[2]}', '{u[3]}', '{u[4]}')" for u in users),
        "ON CONFLICT (id) DO NOTHING;\n",
    ]

    stores = [_build_store(i, SCENARIO_PLAN[i - 1]) for i in range(1, 121)]
    lines += [
        "INSERT INTO merchant_stores (id, merchant_name, store_name, category, city, address, business_hours, phone, supports_reservation, metadata) VALUES",
        ",\n".join(
            f"  ('{s[0]}', '{esc(s[1])}', '{esc(s[2])}', '{s[3]}', '{s[4]}', '{esc(s[5])}', '{s[6]}', '{s[7]}', {str(s[8]).upper()}, '{sql_json(s[9])}'::jsonb)"
            for s in stores
        ),
        "ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata, business_hours = EXCLUDED.business_hours, store_name = EXCLUDED.store_name, address = EXCLUDED.address;\n",
    ]

    orders = [_build_order(i, f"user_{i:03d}", stores[i - 1], SCENARIO_PLAN[i - 1]) for i in range(1, 121)]
    lines += [
        "INSERT INTO life_orders (id, user_id, store_id, service_type, title, status, paid_amount, original_amount, purchase_time, service_time, expire_time, can_refund, can_reschedule, metadata) VALUES",
        ",\n".join(
            f"  ('{o[0]}', '{o[1]}', '{o[2]}', '{esc(o[3])}', '{esc(o[4])}', '{o[5]}', {o[6]}, {o[7]}, '{o[8]}'::timestamptz, "
            f"{('NULL' if not o[9] else "'" + o[9] + "'::timestamptz")}, '{o[10]}'::timestamptz, {str(o[11]).upper()}, {str(o[12]).upper()}, '{sql_json(o[13])}'::jsonb)"
            for o in orders
        ),
        "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, metadata = EXCLUDED.metadata, service_time = EXCLUDED.service_time, can_refund = EXCLUDED.can_refund;\n",
    ]

    vouchers = []
    for i, o in enumerate(orders, start=1):
        scenario = o[14]
        vsid = _voucher_store_id(o, scenario, stores)
        vouchers.append(
            (
                f"voucher_{i:03d}",
                o[0],
                o[1],
                vsid,
                f"DY{i:04d}-{random.randint(1000, 9999)}",
                o[4],
                _voucher_status(o[5], scenario),
                o[8],
                o[10],
                _usage_rule(scenario),
            )
        )
    lines += [
        "INSERT INTO vouchers (id, order_id, user_id, store_id, code, title, status, valid_from, valid_to, usage_rule) VALUES",
        ",\n".join(
            f"  ('{v[0]}', '{v[1]}', '{v[2]}', '{v[3]}', '{v[4]}', '{esc(v[5])}', '{v[6]}', '{v[7]}'::timestamptz, '{v[8]}'::timestamptz, '{esc(v[9])}')"
            for v in vouchers
        ),
        "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, usage_rule = EXCLUDED.usage_rule, store_id = EXCLUDED.store_id;\n",
    ]

    coupons = [
        (
            f"coupon_{i:03d}",
            f"user_{i:03d}",
            f"{CATEGORIES[i % len(CATEGORIES)]}满 {random.randint(80, 200)} 减 {random.randint(10, 50)}",
            random.randint(10, 50),
            random.randint(80, 200),
            CATEGORIES[i % len(CATEGORIES)],
            stores[i - 1][0] if i % 4 == 0 else None,
            COUPON_STATUSES[i % len(COUPON_STATUSES)],
            (NOW + timedelta(days=random.randint(1, 30))).isoformat(),
            "满足门槛可用，部分券不可与团购套餐叠加。",
        )
        for i in range(1, 121)
    ]
    lines += [
        "INSERT INTO coupons (id, user_id, title, discount_amount, threshold_amount, applicable_category, applicable_store_id, status, valid_to, rule_text) VALUES",
        ",\n".join(
            f"  ('{c[0]}', '{c[1]}', '{esc(c[2])}', {c[3]}, {c[4]}, '{c[5]}', {('NULL' if not c[6] else "'" + c[6] + "'")}, '{c[7]}', '{c[8]}'::timestamptz, '{esc(c[9])}')"
            for c in coupons
        ),
        "ON CONFLICT (id) DO NOTHING;\n",
    ]

    refunds = [r for o in orders if (r := _build_refund(o))]
    lines += [
        "INSERT INTO refund_cases (id, order_id, user_id, reason, status, refundable_amount, estimated_finish_time) VALUES",
        ",\n".join(f"  ('{r[0]}', '{r[1]}', '{r[2]}', '{esc(r[3])}', '{r[4]}', {r[5]}, '{r[6]}'::timestamptz)" for r in refunds),
        "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason;\n",
    ]

    events = [e for o in orders for e in _build_events(o)]
    lines += [
        "INSERT INTO fulfillment_events (order_id, user_id, store_id, event_type, status, detail, created_at) VALUES",
        ",\n".join(f"  ('{e[0]}', '{e[1]}', '{e[2]}', '{e[3]}', '{e[4]}', '{sql_json(e[5])}'::jsonb, '{e[6]}'::timestamptz)" for e in events),
        ";\n",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"  anchor={SEED_ANCHOR.isoformat()} orders={len(orders)} refunds={len(refunds)} anomalies={len(ANOMALY_PLAN)}")


if __name__ == "__main__":
    main()
