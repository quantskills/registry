"""Deterministic semantic checks shared by versioned data contracts."""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
import math
import re

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_PROFILE_TEMPORAL_FIELDS = {
    "event-record": (("event_time", "rfc3339"), ("published_at", "rfc3339")),
    "factor-panel": (("timestamp", "rfc3339"),),
    "fundamental-pit": (("period_end", "date"), ("available_at", "rfc3339")),
    "futures-contract": (("trade_date", "date"), ("expiry", "date")),
    "holdings": (("as_of", "rfc3339"),),
    "macro-series": (("observation_date", "date"), ("vintage_date", "date")),
    "market-bar": (("timestamp", "rfc3339"),),
    "option-chain": (("quote_time", "rfc3339"), ("expiry", "date")),
}
_MACRO_UNITS = {"percent", "index", "currency", "count", "ratio"}


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


def _strict_date(value: object) -> bool:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        date_type.fromisoformat(value)
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
    if not isinstance(contract, dict):
        return []
    profile = contract.get("profile")
    if not isinstance(profile, str):
        return []
    temporal_fields = _PROFILE_TEMPORAL_FIELDS.get(profile)
    if temporal_fields is None:
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
        for field, kind in temporal_fields:
            if field not in record:
                continue
            if not isinstance(record[field], str):
                continue
            valid = _strict_rfc3339(record[field]) if kind == "rfc3339" else _strict_date(record[field])
            if not valid:
                issues.append(_issue(f"profile-{kind}", f"/payload/records/{index}/{field}"))

        for field, value in record.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
                issues.append(_issue("profile-finite", f"/payload/records/{index}/{field}"))

        if profile == "factor-panel" and record.get("value") is None and record.get("missing_policy") != "keep-null":
            issues.append(_issue("factor-panel-nullability", f"/payload/records/{index}/value"))

        if profile == "macro-series":
            schema = document.get("schema")
            fields = schema.get("fields") if isinstance(schema, dict) else None
            value_descriptor = fields.get("value") if isinstance(fields, dict) else None
            descriptor_unit = value_descriptor.get("unit") if isinstance(value_descriptor, dict) else None
            if isinstance(descriptor_unit, str) and descriptor_unit in _MACRO_UNITS and record.get("unit") != descriptor_unit:
                issues.append(_issue("macro-series-unit", f"/payload/records/{index}/unit"))
            if descriptor_unit == "currency":
                meta = document.get("meta")
                meta_currency = meta.get("currency") if isinstance(meta, dict) else None
                if not isinstance(meta_currency, str) or not re.fullmatch(r"[A-Z]{3}", meta_currency):
                    issues.append(_issue("macro-series-currency", "/meta/currency"))

        if profile == "market-bar":
            values = {field: record.get(field) for field in ("low", "open", "close", "high")}
            if all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in values.values()
            ):
                low, open_, close, high = values["low"], values["open"], values["close"], values["high"]
                if low > high:
                    issues.append(_issue("market-bar-ohlc-range", f"/payload/records/{index}"))
                if open_ < low or open_ > high:
                    issues.append(_issue("market-bar-open-outside-range", f"/payload/records/{index}/open"))
                if close < low or close > high:
                    issues.append(_issue("market-bar-close-outside-range", f"/payload/records/{index}/close"))
    return issues
