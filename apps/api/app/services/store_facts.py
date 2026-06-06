"""门店侧可观测事实（POI、POS 同步等），供诊断树推导，非诊断结论标签。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def pos_sync_stale(store_meta: dict, *, stale_after: timedelta | None = None) -> bool:
    """POS 与平台最后同步时间过久，可能导致扫码失败（事实遥测，非 merchant_reject 标签）。"""
    threshold = stale_after or timedelta(hours=6)
    synced_at = _parse_dt(store_meta.get("pos_last_sync_at"))
    if not synced_at:
        return False
    return datetime.now(timezone.utc) - synced_at > threshold


def store_relocated(store_meta: dict) -> bool:
    """POI 是否已搬迁：存在上一地址记录即视为搬迁公告。"""
    return bool(store_meta.get("previous_address"))
