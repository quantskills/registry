"""Deterministic semantic checks shared by versioned data contracts."""
from __future__ import annotations

from datetime import datetime
import re

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$")


def _issue(code: str, path: str) -> dict:
    return {"code": code, "path": path}


def _strict_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return True


def envelope_semantic_issues(document: object) -> list[dict]:
    """Return stable, value-free Envelope v1 semantic issues."""
    if not isinstance(document, dict):
        return [_issue("envelope-object", "/")]
    issues: list[dict] = []
    meta = document.get("meta")
    if isinstance(meta, dict) and not _strict_rfc3339(meta.get("generated_at")):
        issues.append(_issue("envelope-rfc3339", "/meta/generated_at"))
    if isinstance(meta, dict) and "as_of" in meta and not _strict_rfc3339(meta.get("as_of")):
        issues.append(_issue("envelope-rfc3339", "/meta/as_of"))
    schema = document.get("schema")
    if isinstance(schema, dict):
        fields = schema.get("fields")
        primary_key = schema.get("primary_key")
        if isinstance(fields, dict) and isinstance(primary_key, list):
            issues.extend(
                _issue("envelope-primary-key", f"/schema/primary_key/{index}")
                for index, key in enumerate(primary_key)
                if isinstance(key, str) and key not in fields
            )
    return issues


def profile_semantic_issues(document: object) -> list[dict]:
    """Return value-free Profile issues; tolerate schema-invalid documents."""
    if not isinstance(document, dict):
        return []
    contract = document.get("$contract")
    if not isinstance(contract, dict) or contract.get("profile") != "market-bar":
        return []
    payload = document.get("payload")
    if not isinstance(payload, dict):
        return []
    records = payload.get("records")
    if not isinstance(records, list):
        return []
    issues: list[dict] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if not all(
            isinstance(record.get(key), (int, float))
            and not isinstance(record.get(key), bool)
            for key in ("low", "open", "close", "high")
        ):
            continue
        low, open_, close, high = record["low"], record["open"], record["close"], record["high"]
        if low > high:
            issues.append(_issue("market-bar-ohlc-range", f"/payload/records/{index}"))
        if open_ < low or open_ > high:
            issues.append(_issue("market-bar-open-outside-range", f"/payload/records/{index}/open"))
        if close < low or close > high:
            issues.append(_issue("market-bar-close-outside-range", f"/payload/records/{index}/close"))
    return issues
