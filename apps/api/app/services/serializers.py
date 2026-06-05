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
        attr = field
        if not hasattr(obj, attr) and field == "metadata" and hasattr(obj, "metadata_"):
            attr = "metadata_"
        out[field] = json_value(getattr(obj, attr))
    return out
