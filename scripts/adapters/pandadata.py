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


def _json_value(value: object, _active: set[int] | None = None) -> None:
    """Validate a native JSON value without recursing through cycles.

    Shared containers are valid JSON-shaped Python values, so the identity set
    is active only for the current recursion path.  A repeated identity after
    its first branch has completed is therefore not mistaken for a cycle.
    """
    active = set() if _active is None else _active
    if type(value) is dict:
        identity = id(value)
        if identity in active:
            raise ValueError("pandadata-native-json")
        active.add(identity)
        try:
            if any(type(key) is not str for key in value):
                raise ValueError("pandadata-native-json")
            for item in value.values():
                _json_value(item, active)
        finally:
            active.remove(identity)
    elif type(value) is list:
        identity = id(value)
        if identity in active:
            raise ValueError("pandadata-native-json")
        active.add(identity)
        try:
            for item in value:
                _json_value(item, active)
        finally:
            active.remove(identity)
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


_PANDADATA_MAPPING_SPECS = {
    "pandadata-fundamental-pit-v1": {
        "dataset": "financial-pit", "profile": "fundamental-pit", "callable": "fundamental_pit_envelope", "fixture": "tests/fixtures/pandadata/fundamental-pit-native.json",
        "fields": {"available_at": "available_at", "currency": "currency", "instrument": "instrument_id", "metric": "metric_id", "period_end": "period_end", "revision": "revision", "statement_scope": "statement_scope", "value": "value", "vintage": "vintage"},
        "native_fields_retained": ["native_note"],
        "policies": {"pit": "available_at, revision, and vintage are preserved unchanged", "timezone": "source timestamp strings are retained in payload.native"},
        "units": {"currency": "CNY"},
    },
    "pandadata-futures-contract-v1": {
        "dataset": "futures-settlement", "profile": "futures-contract", "callable": "futures_contract_envelope", "fixture": "tests/fixtures/pandadata/futures-contract-native.json",
        "fields": {"continuous_series_id": "continuous_series_id", "contract": "contract_id", "delivery_terms": "delivery_terms", "exchange": "exchange", "expiry": "expiry", "open_interest": "open_interest", "roll_rule": "roll_rule", "settlement": "settlement", "trade_date": "trade_date"},
        "native_fields_retained": ["native_note"],
        "policies": {"roll": "contract identity, continuous series, and roll rule are preserved unchanged", "timezone": "source timezone metadata is retained"},
        "units": {"currency": "CNY", "open_interest": "contracts"},
    },
    "pandadata-market-bar-v1": {
        "dataset": "bars-daily", "profile": "market-bar", "callable": "market_bar_envelope", "fixture": "tests/fixtures/pandadata/market-bar-native.json",
        "fields": {"adjustment": "adjustment", "close": "close", "high": "high", "instrument": "instrument_id", "low": "low", "open": "open", "source_timestamp": "timestamp", "volume": "volume"},
        "native_fields_retained": ["native_note", "source_timestamp"],
        "policies": {"adjustment": "raw/adjusted flag is preserved without conversion", "timezone": "original timestamp with offset is retained in normalized record and payload.native"},
        "units": {"currency": "CNY", "volume": "shares"},
    },
}

_PANDADATA_EXPECTED_MODULE = "scripts.adapters.pandadata"
_PANDADATA_EXPECTED_ENVELOPE = {"name": "quantskills-envelope", "version": "1.0.0"}
_PANDADATA_REPRESENTATION = "provider-native-json"


def _strict_json_load(raw: bytes) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)


def _mapping_path(root: Path, relative: str) -> Path | None:
    try:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        root_resolved = Path(root).resolve()
        resolved = (root_resolved / candidate).resolve()
        resolved.relative_to(root_resolved)
        return resolved
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _admit_pandadata_mappings(document: object, root: Path) -> bool:
    """Admit only the three checked, lossless provider-normalization rows.

    This is intentionally a closed-world check.  A malformed catalog, an
    unreadable fixture, a callable/validator failure, or any evidence mismatch
    is rejected rather than allowed to create provider evidence.
    """
    try:
        expected_rows = {
            "id",
            "source",
            "target",
            "implementation",
            "fields",
            "native_fields_retained",
            "policies",
            "units",
            "lossless",
            "validation_status",
            "evidence",
        }
        if (
            type(document) is not dict
            or set(document) != {"schema_version", "mappings"}
            or document.get("schema_version") != "1.0.0"
            or type(document.get("mappings")) is not list
        ):
            return False
        rows = document["mappings"]
        expected_ids = sorted(_PANDADATA_MAPPING_SPECS)
        if len(rows) != len(expected_ids):
            return False
        ids = [row.get("id") if type(row) is dict else None for row in rows]
        if ids != expected_ids:
            return False

        root_path = Path(root).resolve()
        for row in rows:
            if (
                type(row) is not dict
                or set(row) != expected_rows
                or row["id"] not in _PANDADATA_MAPPING_SPECS
                or row.get("lossless") is not True
                or row.get("validation_status") != "validated"
            ):
                return False
            spec = _PANDADATA_MAPPING_SPECS[row["id"]]
            source = row["source"]
            target = row["target"]
            implementation = row["implementation"]
            evidence = row["evidence"]
            if (
                type(source) is not dict
                or source
                != {
                    "provider": "pandadata",
                    "dataset": spec["dataset"],
                    "representation": _PANDADATA_REPRESENTATION,
                }
            ):
                return False
            if (
                type(target) is not dict
                or target
                != {"envelope": _PANDADATA_EXPECTED_ENVELOPE, "profile": {"id": spec["profile"], "version": "1.0.0"}}
            ):
                return False
            if (
                type(implementation) is not dict
                or implementation != {"module": _PANDADATA_EXPECTED_MODULE, "callable": spec["callable"]}
            ):
                return False
            if (
                type(evidence) is not dict
                or set(evidence) != {"fixture", "raw_sha256"}
                or evidence.get("fixture") != spec["fixture"]
            ):
                return False
            if (
                row["fields"] != spec["fields"]
                or row["native_fields_retained"] != spec["native_fields_retained"]
                or row["policies"] != spec["policies"]
                or row["units"] != spec["units"]
            ):
                return False

            fixture = _mapping_path(root_path, evidence["fixture"])
            expected_path = _mapping_path(root_path, f"tests/fixtures/pandadata/expected-{spec['profile']}-envelope.json")
            if fixture is None or expected_path is None or not fixture.is_file() or not expected_path.is_file():
                return False
            fixture_bytes = fixture.read_bytes()
            native = _strict_json_load(fixture_bytes)
            if type(native) is not dict or fixture_bytes != _canonical_bytes(native):
                return False
            expected_bytes = expected_path.read_bytes()
            expected = _strict_json_load(expected_bytes)
            if type(expected) is not dict:
                return False

            if native.get("provider") != source["provider"] or native.get("dataset") != source["dataset"]:
                return False
            fixture_sha = "sha256:" + hashlib.sha256(fixture_bytes).hexdigest()
            if evidence["raw_sha256"] != fixture_sha:
                return False
            provenance = expected.get("meta", {}).get("provenance") if type(expected.get("meta")) is dict else None
            if type(provenance) is not list or len(provenance) != 1 or type(provenance[0]) is not dict:
                return False
            provenance_row = provenance[0]
            if (
                provenance_row.get("provider") != native.get("provider")
                or provenance_row.get("dataset") != native.get("dataset")
                or provenance_row.get("raw_ref") != native.get("raw_ref")
                or provenance_row.get("raw_sha256") != fixture_sha
            ):
                return False

            module = importlib.import_module(implementation["module"])
            adapter = getattr(module, implementation["callable"])
            code = getattr(adapter, "__code__", None)
            if (
                not callable(adapter)
                or getattr(adapter, "__module__", None) != implementation["module"]
                or getattr(adapter, "__name__", None) != implementation["callable"]
                or getattr(code, "co_filename", None) != __file__
                or getattr(code, "co_name", None) != implementation["callable"]
            ):
                return False
            native_for_call = copy.deepcopy(native)
            actual = adapter(native_for_call)
            if native_for_call != native or actual != expected or type(actual) is not dict:
                return False

            from scripts.validate_contract import validate_contract

            validation = validate_contract(expected, root_path)
            if not isinstance(validation, dict) or validation.get("status") != "valid" or validation.get("errors") != []:
                return False
            contract = actual.get("$contract")
            if contract != {
                "envelope": "quantskills-envelope",
                "envelope_version": "1.0.0",
                "profile": spec["profile"],
                "profile_version": "1.0.0",
            }:
                return False

            actual_records = actual.get("payload", {}).get("records") if type(actual.get("payload")) is dict else None
            actual_fields = actual.get("schema", {}).get("fields") if type(actual.get("schema")) is dict else None
            if type(actual_records) is not list or not actual_records or type(actual_fields) is not dict:
                return False
            source_keys = set().union(*(set(record) for record in native.get("records", []) if type(record) is dict))
            for source_key, target_key in row["fields"].items():
                if source_key not in source_keys or target_key not in actual_fields:
                    return False
                for native_record, actual_record in zip(native["records"], actual_records):
                    if source_key not in native_record or target_key not in actual_record or native_record[source_key] != actual_record[target_key]:
                        return False
            if any(field not in source_keys for field in row["native_fields_retained"]):
                return False

            metadata = native.get("metadata")
            if type(metadata) is not dict or row["units"].get("currency") != metadata.get("currency"):
                return False
            if actual.get("meta", {}).get("currency") != metadata.get("currency"):
                return False
            if spec["profile"] == "market-bar":
                volume_units = {record.get("volume_unit") for record in native["records"]}
                if row["units"].get("volume") not in volume_units or actual_fields.get("volume", {}).get("unit") != row["units"]["volume"]:
                    return False
            if spec["profile"] == "futures-contract" and actual_fields.get("open_interest", {}).get("unit") != row["units"].get("open_interest"):
                return False
        return True
    except BaseException:
        return False
