"""Deterministic PandaData synthetic-fixture adapters."""
from __future__ import annotations

import copy
from datetime import date, datetime
import hashlib
import importlib
import json
import math
from pathlib import Path
import re

__all__ = ["market_bar_envelope", "fundamental_pit_envelope", "futures_contract_envelope"]

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_INTEGER_LIMIT = 2**53 - 1


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _json_value(value: object) -> None:
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("pandadata-native-json")
        for item in value.values():
            _json_value(item)
    elif type(value) is list:
        for item in value:
            _json_value(item)
    elif type(value) is int:
        if abs(value) > _INTEGER_LIMIT:
            raise ValueError("pandadata-integer-range")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("pandadata-nonfinite")
    elif type(value) not in (str, bool, type(None)):
        raise ValueError("pandadata-native-json")


def _text(value: object) -> bool:
    return type(value) is str and bool(value)


def _number(value: object, nonnegative: bool = False) -> bool:
    return type(value) in (int, float) and (not nonnegative or value >= 0)


def _date(value: object) -> bool:
    if not _text(value) or _DATE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _datetime(value: object) -> bool:
    if not _text(value) or _DATETIME.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return True


def _native(native: dict, profile: str) -> tuple[dict, list[dict]]:
    if type(native) is not dict:
        raise ValueError("pandadata-native-object")
    _json_value(native)
    metadata, records = native.get("metadata"), native.get("records")
    if not all(_text(native.get(key)) for key in ("provider", "dataset", "raw_ref")) or not _datetime(native.get("generated_at")):
        raise ValueError("pandadata-native-shape")
    if type(metadata) is not dict or type(records) is not list or not records or any(type(record) is not dict for record in records):
        raise ValueError("pandadata-native-shape")
    if not all(_text(metadata.get(key)) for key in ("producer", "timezone", "calendar")) or not re.fullmatch(r"[A-Z]{3}", metadata.get("currency", "")):
        raise ValueError("pandadata-native-shape")
    for row in records:
        if profile == "market-bar":
            required = ("instrument", "source_timestamp", "adjustment", "volume_unit")
            valid = all(_text(row.get(key)) for key in required) and _datetime(row.get("source_timestamp")) and row.get("adjustment") in {"none", "split", "total-return"} and row.get("volume_unit") in {"shares", "contracts", "lots", "units", "currency"} and all(_number(row.get(key)) for key in ("open", "high", "low", "close")) and _number(row.get("volume"), True)
            if not valid or not _text(metadata.get("frequency")) or metadata["frequency"] not in {"1m", "5m", "1h", "1d", "1w", "1mo"}:
                raise ValueError("pandadata-native-shape")
            if row["low"] > row["high"] or not row["low"] <= row["open"] <= row["high"] or not row["low"] <= row["close"] <= row["high"]:
                raise ValueError("pandadata-native-shape")
        elif profile == "fundamental-pit":
            valid = all(_text(row.get(key)) for key in ("instrument", "metric", "revision", "vintage")) and _date(row.get("period_end")) and _datetime(row.get("available_at")) and row.get("statement_scope") in {"consolidated", "standalone", "adjusted"} and _number(row.get("value")) and re.fullmatch(r"[A-Z]{3}", row.get("currency", "")) is not None and row["currency"] == metadata["currency"]
            if not valid:
                raise ValueError("pandadata-native-shape")
        else:
            valid = all(_text(row.get(key)) for key in ("exchange", "contract", "continuous_series_id")) and _date(row.get("trade_date")) and _date(row.get("expiry")) and _number(row.get("settlement")) and _number(row.get("open_interest"), True) and row.get("delivery_terms") in {"physical", "cash", "unknown"} and row.get("roll_rule") in {"volume", "open-interest", "calendar", "none"}
            if not valid:
                raise ValueError("pandadata-native-shape")
    return metadata, records


def _envelope(native: dict, profile: str, primary_key: list[str], fields: dict, records: list[dict]) -> dict:
    metadata, _ = _native(native, profile)
    meta = {"dataset_id": native["dataset"], "producer": metadata["producer"], "generated_at": native["generated_at"], "timezone": metadata["timezone"], "currency": metadata["currency"], "calendar": metadata["calendar"], "provenance": [{"provider": native["provider"], "dataset": native["dataset"], "raw_ref": native["raw_ref"], "raw_sha256": "sha256:" + hashlib.sha256(_canonical_bytes(native)).hexdigest()}]}
    return {"$contract": {"envelope": "quantskills-envelope", "envelope_version": "1.0.0", "profile": profile, "profile_version": "1.0.0"}, "meta": meta, "schema": {"primary_key": primary_key, "fields": fields}, "payload": {"native": {"provider": native["provider"], "raw_ref": native["raw_ref"], "raw_records": [copy.deepcopy(native)]}, "records": copy.deepcopy(records)}, "quality": {"status": "pass", "checks": ["lossless-native-recovery"], "warnings": []}}


def market_bar_envelope(native: dict) -> dict:
    metadata, rows = _native(native, "market-bar")
    units = {row["volume_unit"] for row in rows}
    if len(units) != 1:
        raise ValueError("pandadata-volume-unit")
    fields = {"instrument_id": {"type": "string", "nullable": False}, "timestamp": {"type": "string", "nullable": False, "format": "date-time"}, "open": {"type": "number", "nullable": False, "unit": "currency"}, "high": {"type": "number", "nullable": False, "unit": "currency"}, "low": {"type": "number", "nullable": False, "unit": "currency"}, "close": {"type": "number", "nullable": False, "unit": "currency"}, "volume": {"type": "number", "nullable": False, "unit": next(iter(units))}, "frequency": {"type": "string", "nullable": False}, "adjustment": {"type": "string", "nullable": False}, "calendar": {"type": "string", "nullable": False}}
    records = [{"instrument_id": row["instrument"], "timestamp": row["source_timestamp"], "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"], "volume": row["volume"], "frequency": metadata["frequency"], "adjustment": row["adjustment"], "calendar": metadata["calendar"]} for row in rows]
    return _envelope(native, "market-bar", ["instrument_id", "timestamp"], fields, records)


def fundamental_pit_envelope(native: dict) -> dict:
    _metadata, rows = _native(native, "fundamental-pit")
    fields = {"instrument_id": {"type": "string", "nullable": False}, "period_end": {"type": "string", "nullable": False, "format": "date"}, "available_at": {"type": "string", "nullable": False, "format": "date-time"}, "statement_scope": {"type": "string", "nullable": False}, "metric_id": {"type": "string", "nullable": False}, "value": {"type": "number", "nullable": False, "unit": "currency"}, "currency": {"type": "string", "nullable": False}, "revision": {"type": "string", "nullable": False}, "vintage": {"type": "string", "nullable": False}}
    records = [{"instrument_id": row["instrument"], "period_end": row["period_end"], "available_at": row["available_at"], "statement_scope": row["statement_scope"], "metric_id": row["metric"], "value": row["value"], "currency": row["currency"], "revision": row["revision"], "vintage": row["vintage"]} for row in rows]
    return _envelope(native, "fundamental-pit", ["instrument_id", "period_end", "available_at", "statement_scope"], fields, records)


def futures_contract_envelope(native: dict) -> dict:
    _metadata, rows = _native(native, "futures-contract")
    fields = {"exchange": {"type": "string", "nullable": False}, "contract_id": {"type": "string", "nullable": False}, "trade_date": {"type": "string", "nullable": False, "format": "date"}, "settlement": {"type": "number", "nullable": False, "unit": "currency"}, "open_interest": {"type": "number", "nullable": False, "unit": "contracts"}, "expiry": {"type": "string", "nullable": False, "format": "date"}, "delivery_terms": {"type": "string", "nullable": False}, "continuous_series_id": {"type": "string", "nullable": False}, "roll_rule": {"type": "string", "nullable": False}}
    records = [{"exchange": row["exchange"], "contract_id": row["contract"], "trade_date": row["trade_date"], "settlement": row["settlement"], "open_interest": row["open_interest"], "expiry": row["expiry"], "delivery_terms": row["delivery_terms"], "continuous_series_id": row["continuous_series_id"], "roll_rule": row["roll_rule"]} for row in rows]
    return _envelope(native, "futures-contract", ["exchange", "contract_id", "trade_date"], fields, records)


def _admit_pandadata_mappings(document: object, root: Path) -> bool:
    expected_rows = {"id", "source", "target", "implementation", "fields", "native_fields_retained", "policies", "units", "lossless", "validation_status", "evidence"}
    if type(document) is not dict or set(document) != {"schema_version", "mappings"} or document.get("schema_version") != "1.0.0" or type(document["mappings"]) is not list:
        return False
    rows = document["mappings"]
    ids = [row.get("id") for row in rows if type(row) is dict]
    if len(ids) != len(rows) or ids != sorted(ids) or len(set(ids)) != len(ids):
        return False
    for row in rows:
        if type(row) is not dict or set(row) != expected_rows or not _text(row.get("id")) or not row["id"].startswith("pandadata-") or row.get("lossless") is not True or row.get("validation_status") != "validated":
            return False
        source, target, implementation, evidence = row["source"], row["target"], row["implementation"], row["evidence"]
        if type(source) is not dict or set(source) != {"provider", "dataset", "representation"} or source.get("provider") != "pandadata" or not all(_text(source.get(key)) for key in source):
            return False
        if type(target) is not dict or set(target) != {"envelope", "profile"} or target.get("envelope") != {"name": "quantskills-envelope", "version": "1.0.0"} or type(target.get("profile")) is not dict or set(target["profile"]) != {"id", "version"} or not _text(target["profile"].get("id")) or target["profile"].get("version") != "1.0.0":
            return False
        if type(implementation) is not dict or set(implementation) != {"module", "callable"} or type(evidence) is not dict or set(evidence) != {"fixture", "raw_sha256"}:
            return False
        if not all(type(row[key]) is dict and all(_text(key_) and _text(value) for key_, value in row[key].items()) for key in ("fields", "policies", "units")) or type(row["native_fields_retained"]) is not list or not all(_text(item) for item in row["native_fields_retained"]):
            return False
        try:
            module = importlib.import_module(implementation["module"])
            adapter = getattr(module, implementation["callable"])
            fixture = root / evidence["fixture"]
            native = json.loads(fixture.read_text(encoding="utf-8"))
            expected = json.loads((fixture.parent / ("expected-" + target["profile"]["id"] + "-envelope.json")).read_text(encoding="utf-8"))
            from scripts.validate_contract import validate_contract
        except (AttributeError, ImportError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if not callable(adapter) or not fixture.is_file() or evidence["raw_sha256"] != "sha256:" + hashlib.sha256(fixture.read_bytes()).hexdigest() or adapter(native) != expected or validate_contract(expected, root)["status"] != "valid" or expected.get("$contract", {}).get("profile") != target["profile"]["id"]:
            return False
    return True
