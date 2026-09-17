import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
import uuid


def canonical_normalize(value: Any) -> Any:
    """
    Recursively normalize supported matching snapshot values into deterministic canonical types.

    Supported types:
    - dict (keys sorted as strings)
    - list/tuple (ordered preserved)
    - str, int, bool, None
    - Decimal (normalized stable string, never float)
    - UUID (canonical lowercase 36-character string)
    - date (ISO-8601 string YYYY-MM-DD)
    - timezone-aware datetime (converted to UTC ISO-8601 string)

    Rejects naive datetimes, floats, sets, and arbitrary non-deterministic objects.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError(f"Floats are not permitted in deterministic matching snapshots; use Decimal: {value}")
    if isinstance(value, str):
        return value
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value.is_zero():
            return "0"
        return f"{value.normalize():f}"
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(f"Naive datetime is not permitted in deterministic snapshots: {value}")
        utc_dt = value.astimezone(datetime.timezone.utc)
        return utc_dt.isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [canonical_normalize(item) for item in value]
    if isinstance(value, dict):
        # Validate keys and recursively normalize items
        for k in value.keys():
            if not isinstance(k, (str, int, uuid.UUID)):
                raise TypeError(f"Invalid dict key type for deterministic snapshot: {type(k).__name__}")
        return {
            str(k): canonical_normalize(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }

    raise TypeError(f"Unsupported type for canonical snapshot fingerprinting: {type(value).__name__}")


def canonical_json_bytes(data: Any) -> bytes:
    """Serialize normalized data into deterministic canonical UTF-8 JSON bytes."""
    normalized = canonical_normalize(data)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_fingerprint(data: Any) -> str:
    """Compute the SHA-256 hex digest of canonically serialized data."""
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()
