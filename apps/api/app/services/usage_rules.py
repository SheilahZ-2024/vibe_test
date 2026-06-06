"""从券 usage_rule 等平台规则文案推导时段/预约约束（非 seed 诊断标签）。"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")


def _local_now(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(CN_TZ)


def _parse_hhmm(value: str) -> time | None:
    m = re.match(r"(\d{1,2}):(\d{2})", value.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    # 门店文案常见 24:00 表示营业至当日结束，Python time 仅支持 0–23
    if hour == 24 and minute == 0:
        return time(23, 59, 59)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _parse_hours_window(text: str) -> tuple[time, time] | None:
    m = re.search(r"(\d{1,2}:\d{2})\s*[-~至到]\s*(\d{1,2}:\d{2})", text)
    if not m:
        return None
    start, end = _parse_hhmm(m.group(1)), _parse_hhmm(m.group(2))
    if not start or not end:
        return None
    return start, end


def requires_reservation(usage_rule: str, service_type: str, supports_reservation: bool) -> bool:
    rule = usage_rule or ""
    if any(k in rule for k in ("须预约", "提前预约", "预约成功", "未预约不可")):
        return True
    return supports_reservation and service_type in ("团购套餐", "预约服务", "酒店套餐")


def voucher_allowed_at(usage_rule: str, at: datetime | None = None) -> tuple[bool, str]:
    """根据规则文案判断给定时刻是否可核销。返回 (是否允许, 原因简述)。"""
    try:
        rule = usage_rule or ""
        local = _local_now(at)

        if any(k in rule for k in ("仅限周六", "仅限周日", "仅限周末", "周末可用", "周六、周日")):
            if local.weekday() not in (5, 6):
                return False, "仅周末可用"

        lunch = _parse_hours_window(rule) if ("午市" in rule or "11:00" in rule) else None
        if lunch and ("午市" in rule or "11:00-14:00" in rule.replace(" ", "")):
            start, end = lunch
            t = local.time()
            if not (start <= t <= end):
                return False, "非午市时段"

        return True, "ok"
    except Exception:
        return True, "ok"


def within_store_hours(
    business_hours: str,
    at: datetime | None = None,
    today_hours: str | None = None,
) -> tuple[bool, str]:
    """判断时刻是否在门店营业时段内；today_hours 为商家当日临时公告。"""
    try:
        window_text = today_hours or business_hours or ""
        parsed = _parse_hours_window(window_text)
        if not parsed:
            return True, "ok"
        start, end = parsed
        local = _local_now(at)
        t = local.time()
        if start <= end:
            if start <= t <= end:
                return True, "ok"
            return False, "当前不在营业时间"
        # 跨日营业，如 17:00-02:00
        if t >= start or t <= end:
            return True, "ok"
        return False, "当前不在营业时间"
    except Exception:
        return False, "营业时间信息暂时无法校验，请核对是否在营业时段内"
