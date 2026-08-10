"""Deterministic PandaData synthetic-fixture adapters."""
from __future__ import annotations

import copy
import hashlib
import json
import math

__all__ = ["market_bar_envelope", "fundamental_pit_envelope", "futures_contract_envelope"]


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _has_nonfinite(value: object) -> bool:
    if isinstance(value, dict):
        return any(_has_nonfinite(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_nonfinite(item) for item in value)
    return isinstance(value, float) and not math.isfinite(value)


def _native(native: dict) -> tuple[dict, list[dict]]:
    if not isinstance(native, dict):
        raise ValueError("pandadata-native-object")
    if _has_nonfinite(native):
        raise ValueError("pandadata-nonfinite")
    records = native.get("records")
    metadata = native.get("metadata")
    required = ("provider", "dataset", "raw_ref", "generated_at")
    if (
        not all(isinstance(native.get(key), str) and native[key] for key in required)
        or not isinstance(metadata, dict)
        or not isinstance(records, list)
        or not records
        or any(not isinstance(record, dict) for record in records)
    ):
        raise ValueError("pandadata-native-shape")
    return metadata, records


def _envelope(native: dict, profile: str, primary_key: list[str], fields: dict, records: list[dict]) -> dict:
    metadata, raw_records = _native(native)
    required_metadata = ("producer", "timezone")
    if not all(isinstance(metadata.get(key), str) and metadata[key] for key in required_metadata):
        raise ValueError("pandadata-native-shape")
    if any(any(key not in record for key in primary_key) for record in records):
        raise ValueError("pandadata-native-shape")
    meta = {
        "dataset_id": native["dataset"],
        "producer": metadata["producer"],
        "generated_at": native["generated_at"],
        "timezone": metadata["timezone"],
        "provenance": [{
            "provider": native["provider"],
            "dataset": native["dataset"],
            "raw_ref": native["raw_ref"],
            "raw_sha256": "sha256:" + hashlib.sha256(_canonical_bytes(native)).hexdigest(),
        }],
    }
    for key in ("currency", "calendar"):
        if key in metadata:
            meta[key] = metadata[key]
    return {
        "$contract": {"envelope": "quantskills-envelope", "envelope_version": "1.0.0", "profile": profile, "profile_version": "1.0.0"},
        "meta": meta,
        "schema": {"primary_key": primary_key, "fields": fields},
        "payload": {"native": {"provider": native["provider"], "raw_ref": native["raw_ref"], "raw_records": copy.deepcopy(raw_records)}, "records": records},
        "quality": {"status": "pass", "checks": ["lossless-native-recovery"], "warnings": []},
    }


def market_bar_envelope(native: dict) -> dict:
    metadata, raw_records = _native(native)
    if not all(isinstance(metadata.get(key), str) and metadata[key] for key in ("currency", "calendar", "frequency")):
        raise ValueError("pandadata-native-shape")
    fields = {
        "instrument_id": {"type": "string", "nullable": False}, "timestamp": {"type": "string", "nullable": False, "format": "date-time"},
        "open": {"type": "number", "nullable": False, "unit": "currency"}, "high": {"type": "number", "nullable": False, "unit": "currency"},
        "low": {"type": "number", "nullable": False, "unit": "currency"}, "close": {"type": "number", "nullable": False, "unit": "currency"},
        "volume": {"type": "number", "nullable": False, "unit": raw_records[0].get("volume_unit")}, "frequency": {"type": "string", "nullable": False},
        "adjustment": {"type": "string", "nullable": False}, "calendar": {"type": "string", "nullable": False},
    }
    records = [{"instrument_id": row.get("instrument"), "timestamp": row.get("source_timestamp"), "open": row.get("open"), "high": row.get("high"), "low": row.get("low"), "close": row.get("close"), "volume": row.get("volume"), "frequency": metadata["frequency"], "adjustment": row.get("adjustment"), "calendar": metadata["calendar"]} for row in raw_records]
    return _envelope(native, "market-bar", ["instrument_id", "timestamp"], fields, records)


def fundamental_pit_envelope(native: dict) -> dict:
    _metadata, raw_records = _native(native)
    fields = {
        "instrument_id": {"type": "string", "nullable": False}, "period_end": {"type": "string", "nullable": False, "format": "date"},
        "available_at": {"type": "string", "nullable": False, "format": "date-time"}, "statement_scope": {"type": "string", "nullable": False},
        "metric_id": {"type": "string", "nullable": False}, "value": {"type": "number", "nullable": False, "unit": "currency"},
        "currency": {"type": "string", "nullable": False}, "revision": {"type": "string", "nullable": False}, "vintage": {"type": "string", "nullable": False},
    }
    records = [{"instrument_id": row.get("instrument"), "period_end": row.get("period_end"), "available_at": row.get("available_at"), "statement_scope": row.get("statement_scope"), "metric_id": row.get("metric"), "value": row.get("value"), "currency": row.get("currency"), "revision": row.get("revision"), "vintage": row.get("vintage")} for row in raw_records]
    return _envelope(native, "fundamental-pit", ["instrument_id", "period_end", "available_at", "statement_scope"], fields, records)


def futures_contract_envelope(native: dict) -> dict:
    _metadata, raw_records = _native(native)
    fields = {
        "exchange": {"type": "string", "nullable": False}, "contract_id": {"type": "string", "nullable": False}, "trade_date": {"type": "string", "nullable": False, "format": "date"},
        "settlement": {"type": "number", "nullable": False, "unit": "currency"}, "open_interest": {"type": "number", "nullable": False, "unit": "contracts"},
        "expiry": {"type": "string", "nullable": False, "format": "date"}, "delivery_terms": {"type": "string", "nullable": False},
        "continuous_series_id": {"type": "string", "nullable": False}, "roll_rule": {"type": "string", "nullable": False},
    }
    records = [{"exchange": row.get("exchange"), "contract_id": row.get("contract"), "trade_date": row.get("trade_date"), "settlement": row.get("settlement"), "open_interest": row.get("open_interest"), "expiry": row.get("expiry"), "delivery_terms": row.get("delivery_terms"), "continuous_series_id": row.get("continuous_series_id"), "roll_rule": row.get("roll_rule")} for row in raw_records]
    return _envelope(native, "futures-contract", ["exchange", "contract_id", "trade_date"], fields, records)
