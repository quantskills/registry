"""Fail-closed loader for the Registry's committed interface catalogs."""
from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENVELOPE = "quantskills-envelope"
_VERSION = "1.0.0"
_APPROVED_PROFILES = {
    "backtest-result": ("result", ("strategy_id", "period_start", "period_end"), "backtest_period"),
    "evaluation-result": ("result", ("subject_id", "evaluated_at"), "evaluated_at"),
    "event-record": ("base", ("event_id", "event_time", "entity_id"), "event_time"),
    "execution-plan": ("result", ("portfolio_id", "as_of"), "as_of"),
    "factor-panel": ("base", ("instrument_id", "timestamp", "factor_id"), "timestamp"),
    "fundamental-pit": ("base", ("instrument_id", "period_end", "available_at", "statement_scope"), "point-in-time"),
    "futures-contract": ("base", ("exchange", "contract_id", "trade_date"), "trade_date"),
    "holdings": ("base", ("portfolio_id", "instrument_id", "as_of"), "as_of"),
    "macro-series": ("base", ("series_id", "observation_date", "vintage_date"), "vintage"),
    "market-bar": ("base", ("instrument_id", "timestamp"), "bar_timestamp"),
    "model-artifact": ("result", ("model_id", "training_cutoff"), "training_cutoff"),
    "option-chain": ("base", ("underlying_id", "quote_time", "expiry", "strike", "option_type"), "quote_time"),
    "portfolio-target": ("result", ("portfolio_id", "as_of"), "as_of"),
    "ranked-factor-set": ("result", ("set_id", "factor_id"), "as_of"),
    "report-artifact": ("result", ("report_id", "as_of"), "as_of"),
    "risk-result": ("result", ("subject_id", "as_of"), "as_of"),
}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid interface catalog")
        result[key] = value
    return result


def _root(root: Path) -> Path:
    try:
        value = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError("invalid interface catalog") from error
    if not value.is_dir():
        raise ValueError("invalid interface catalog")
    return value


def _path(root: Path, relative: str) -> Path:
    try:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError
        value = (root / candidate).resolve(strict=True)
        value.relative_to(root)
        if not value.is_file():
            raise ValueError
        return value
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError("invalid interface catalog") from error


def _load(root: Path, relative: str) -> Any:
    try:
        return json.loads(_path(root, relative).read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid interface catalog") from error


def _semver(value: object) -> bool:
    return type(value) is str and _SEMVER.fullmatch(value) is not None


def _profile_schema(root: Path, row: dict[str, Any]) -> None:
    schema = _load(root, "schema/profiles/" + row["schema"])
    try:
        contract = schema["properties"]["$contract"]["properties"]
        primary = schema["properties"]["schema"]["properties"]["primary_key"]["prefixItems"]
        if (contract["envelope"].get("const"), contract["envelope_version"].get("const"),
                contract["profile"].get("const"), contract["profile_version"].get("const")) != (_ENVELOPE, _VERSION, row["id"], _VERSION):
            raise ValueError
        if tuple(item.get("const") for item in primary) != tuple(row["primary_key"]):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid interface catalog") from error


def _profiles(root: Path) -> list[dict[str, Any]]:
    document = _load(root, "schema/profiles/index.json")
    if type(document) is not dict or set(document) != {"profiles"} or type(document.get("profiles")) is not list:
        raise ValueError("invalid interface catalog")
    rows = document["profiles"]
    if len(rows) != len(_APPROVED_PROFILES):
        raise ValueError("invalid interface catalog")
    ids: list[str] = []
    for row in rows:
        if type(row) is not dict or set(row) != {"id", "version", "schema", "kind", "primary_key", "time_semantics"}:
            raise ValueError("invalid interface catalog")
        identifier = row.get("id")
        spec = _APPROVED_PROFILES.get(identifier) if type(identifier) is str else None
        if _ID.fullmatch(identifier or "") is None or not _semver(row.get("version")) or row["version"] != _VERSION or spec is None:
            raise ValueError("invalid interface catalog")
        kind, primary_key, time_semantics = spec
        if row.get("kind") != kind or tuple(row.get("primary_key", ())) != primary_key or row.get("time_semantics") != time_semantics:
            raise ValueError("invalid interface catalog")
        if row.get("schema") != f"{kind}/{identifier}/{_VERSION}.schema.json":
            raise ValueError("invalid interface catalog")
        _profile_schema(root, row)
        ids.append(identifier)
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid interface catalog")
    return rows


def _envelope(root: Path) -> dict[str, Any]:
    document = _load(root, "schema/envelope/index.json")
    if type(document) is not dict or set(document) != {"name", "versions"} or document.get("name") != _ENVELOPE or document.get("versions") != {_VERSION: f"{_VERSION}.schema.json"}:
        raise ValueError("invalid interface catalog")
    schema = _load(root, "schema/envelope/" + document["versions"][_VERSION])
    try:
        contract = schema["properties"]["$contract"]
        required = contract["required"]
        properties = contract["properties"]
        expected = {"envelope", "envelope_version", "profile", "profile_version"}
        if (contract.get("type") != "object" or contract.get("additionalProperties") is not False
                or type(required) is not list or len(required) != len(expected) or set(required) != expected
                or type(properties) is not dict or set(properties) != expected
                or properties["envelope"].get("const") != _ENVELOPE
                or properties["envelope_version"].get("const") != _VERSION):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid interface catalog") from error
    return {"version": _VERSION, "name": _ENVELOPE, "items": [{"version": _VERSION, "schema": f"{_VERSION}.schema.json"}]}


def admit_adapter_registry(document: object, root: Path = ROOT) -> bool:
    """Return whether a closed, lossless, validated adapter catalog is trusted."""
    try:
        base = _root(root)
        schema = _load(base, "schema/adapters/adapter-registry.schema.json")
        if type(document) is not dict or list(Draft202012Validator(schema).iter_errors(document)):
            return False
        rows = document.get("adapters")
        if type(rows) is not list:
            return False
        known = {(name, _VERSION) for name in _APPROVED_PROFILES}
        ids: list[str] = []
        edges: set[tuple[str, str, str, str]] = set()
        for row in rows:
            if row.get("lossless") is not True or row.get("validation_status") != "validated":
                return False
            source, target, implementation = row["source"], row["target"], row["implementation"]
            edge = (source["profile"], source["version"], target["profile"], target["version"])
            if (source["profile"], source["version"]) not in known or (target["profile"], target["version"]) not in known or edge in edges:
                return False
            path = implementation["path"]
            if not isinstance(path, str) or not path.endswith(".py"):
                return False
            _path(base, path)
            ids.append(row["id"]); edges.add(edge)
        return ids == sorted(ids) and len(ids) == len(set(ids))
    except Exception:
        return False


def load_contract_catalogs(root: Path = ROOT) -> tuple[dict, dict, dict, dict]:
    """Load only the approved, root-contained local interface catalog sources."""
    base = _root(root)
    envelope = _envelope(base)
    profiles = _profiles(base)
    adapters_doc = _load(base, "schema/adapters/registry.v1.json")
    if not admit_adapter_registry(adapters_doc, base):
        raise ValueError("invalid interface catalog")
    mappings_doc = _load(base, "schema/adapters/pandadata-mappings.v1.json")
    try:
        from adapters.pandadata import admit_pandadata_mappings
    except ModuleNotFoundError:
        from scripts.adapters.pandadata import admit_pandadata_mappings
    if not admit_pandadata_mappings(mappings_doc, base):
        raise ValueError("invalid interface catalog")
    return (envelope, {"version": _VERSION, "items": profiles},
            {"version": _VERSION, "items": adapters_doc["adapters"]},
            {"version": _VERSION, "items": mappings_doc["mappings"]})


_CORE_FILES = (
    "01-market-bar.json", "02-factor-panel.json", "03-ranked-factor-set.json",
    "04-portfolio-target.json", "05-backtest-result.json", "06-evaluation-result.json",
    "07-execution-plan.json",
)
_CORE_IDS = ("market-bar", "factor-panel", "ranking", "portfolio", "backtest", "evaluation", "execution")
_CORE_PRODUCERS = (
    "skill-pandadata-warehouse", "skill-factor-mining-pandaai", "skill-factor-grouped-wrapper",
    "skill-portfolio-optimize", "skill-backtest", "skill-backtest", "skill-ssquant-ai-trader",
)
_CORE_PROFILES = ("market-bar", "factor-panel", "ranked-factor-set", "portfolio-target", "backtest-result", "evaluation-result", "execution-plan")


def load_core_lineage(root: Path = ROOT) -> dict:
    """Load the committed closed core chain without importing the builder."""
    base = _root(root)
    envelope, profiles, _, mappings = load_contract_catalogs(base)
    manifest = _load(base, "tests/fixtures/e2e/core-chain/lineage.json")
    if type(manifest) is not dict or set(manifest) != {"version", "artifacts"} or manifest.get("version") != _VERSION:
        raise ValueError("invalid core lineage")
    rows = manifest.get("artifacts")
    if type(rows) is not list or len(rows) != len(_CORE_FILES):
        raise ValueError("invalid core lineage")
    mapping = {item["id"]: item for item in mappings["items"]}
    profile_rows = {(item["id"], item["version"]) for item in profiles["items"]}
    previous: dict[str, Any] | None = None
    for index, row in enumerate(rows):
        required = {"id", "file", "artifact_sha256", "producer", "profile", "version", "inputs"}
        if index == 0:
            required |= {"source_mapping_id", "provenance"}
        if type(row) is not dict or set(row) != required or row.get("id") != _CORE_IDS[index] or row.get("file") != _CORE_FILES[index] or row.get("producer") != _CORE_PRODUCERS[index] or row.get("profile") != _CORE_PROFILES[index] or row.get("version") != _VERSION:
            raise ValueError("invalid core lineage")
        raw = _path(base, "tests/fixtures/e2e/core-chain/" + row["file"]).read_bytes()
        actual = "sha256:" + hashlib.sha256(raw).hexdigest()
        if row.get("artifact_sha256") != actual:
            raise ValueError("invalid core lineage")
        document = _load(base, "tests/fixtures/e2e/core-chain/" + row["file"])
        try:
            from validate_contract import validate_contract
        except ModuleNotFoundError:
            from scripts.validate_contract import validate_contract
        if validate_contract(document, base).get("status") != "valid" or document["$contract"]["profile"] != row["profile"] or document["meta"]["producer"] != row["producer"]:
            raise ValueError("invalid core lineage")
        if (row["profile"], row["version"]) not in profile_rows:
            raise ValueError("invalid core lineage")
        if index == 0:
            provenance = row["provenance"]
            source_id = row["source_mapping_id"]
            target = mapping.get(source_id, {}).get("target", {})
            meta_source = document.get("meta", {}).get("provenance", [None])[0]
            if (type(provenance) is not dict or set(provenance) != {"provider", "dataset", "raw_sha256"}
                    or target.get("envelope") != {"name": envelope["name"], "version": _VERSION}
                    or target.get("profile") != {"id": row["profile"], "version": _VERSION}
                    or not isinstance(meta_source, dict) or meta_source.get("raw_sha256") != provenance.get("raw_sha256")
                    or mapping[source_id]["evidence"]["raw_sha256"] != provenance.get("raw_sha256")):
                raise ValueError("invalid core lineage")
        else:
            assert previous is not None
            inputs = row["inputs"]
            source = document.get("payload", {}).get("records", [None])[0].get("lineage", {}).get("sources", [None])[0] if index >= 2 and isinstance(document.get("payload", {}).get("records"), list) and document["payload"]["records"] else {}
            meta_source = document.get("meta", {}).get("provenance", [None])[0]
            expected_input = {"id": previous["id"], "artifact_sha256": previous["artifact_sha256"]}
            if (inputs != [expected_input] or (index >= 2 and (not isinstance(source, dict)
                    or source.get("sha256") != previous["artifact_sha256"]
                    or source.get("profile") != previous["profile"] or source.get("version") != _VERSION
                    or source.get("artifact_ref") != f"artifact://core-chain/{previous['id']}"))
                    or not isinstance(meta_source, dict) or meta_source.get("raw_sha256") != previous["artifact_sha256"]):
                raise ValueError("invalid core lineage")
        previous = row
    return manifest
