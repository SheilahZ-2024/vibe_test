from datetime import datetime
from decimal import Decimal
from typing import Any


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def model_dict(obj: Any, fields: list[str]) -> dict:
    out: dict[str, Any] = {}
    for field in fields:
        if field == "metadata" and hasattr(obj, "metadata_"):
            value = getattr(obj, "metadata_")
        else:
            value = getattr(obj, field)
        out[field] = json_value(value)
    return out
