"""工具返回结构统一解析 — 避免 vouchers[] / order 嵌套等历史格式不一致。"""

from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def order_from_payload(payload: dict | None) -> dict | None:
    if not payload:
        return None
    direct = payload.get("order")
    if isinstance(direct, dict) and direct:
        return direct
    wrap = _as_dict(payload.get("order"))
    if wrap.get("order") is not None:
        nested = wrap.get("order")
        return nested if isinstance(nested, dict) else None
    if wrap.get("title") or wrap.get("id"):
        return wrap
    return None


def voucher_from_payload(payload: dict | None) -> dict | None:
    if not payload:
        return None
    single = payload.get("voucher")
    if isinstance(single, dict) and single:
        return single
    vouchers = payload.get("vouchers")
    if isinstance(vouchers, list) and vouchers:
        first = vouchers[0]
        return first if isinstance(first, dict) else None
    return None


def store_from_payload(payload: dict | None) -> dict | None:
    if not payload:
        return None
    direct = payload.get("store")
    if isinstance(direct, dict) and direct:
        if direct.get("store_name") or direct.get("id"):
            return direct
        nested = direct.get("store")
        if isinstance(nested, dict) and nested:
            return nested
    wrap = _as_dict(payload.get("store"))
    if wrap.get("store") is not None:
        nested = wrap.get("store")
        return nested if isinstance(nested, dict) else None
    if wrap.get("store_name") or wrap.get("id"):
        return wrap
    return None


def normalize_query_voucher(result: dict) -> dict:
    """保证 query_voucher 始终含 voucher 单对象（若有券）。"""
    out = dict(result)
    primary = voucher_from_payload(out)
    if primary:
        out["voucher"] = primary
        out["found"] = True
    else:
        out.setdefault("found", bool(out.get("count")))
    return out


def normalize_focus_bundle(result: dict) -> dict:
    """扁平化 query_focus_bundle 便于 ReAct / memory / fact_sheet 读取。"""
    out = dict(result)
    order = order_from_payload(out)
    voucher = voucher_from_payload(out)
    store = store_from_payload(out)
    if order is not None:
        out["order"] = order
    if voucher is not None:
        out["voucher"] = voucher
    if store is not None:
        out["store"] = store
    return out


def unwrap_tool_result(result: Any) -> dict | None:
    if result is None:
        return None
    if not isinstance(result, dict):
        return None
    if result.get("truncated") and isinstance(result.get("preview"), str):
        return result
    return result
