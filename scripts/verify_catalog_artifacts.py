#!/usr/bin/env python3
"""Independent, offline, fail-closed verification of catalog artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog_projection import public_registry_projection
from interface_catalog import load_contract_catalogs, load_core_lineage

RESOURCE_NAMES = [".github", "join", "quantskills", "registry"]
_CHAIN = (
    ("skill-pandadata-warehouse", "skill-factor-mining-pandaai", "market-bar", "market-bar"),
    ("skill-factor-mining-pandaai", "skill-factor-grouped-wrapper", "factor-panel", "factor-panel"),
    ("skill-factor-grouped-wrapper", "skill-portfolio-optimize", "ranked-factor-set", "ranked-factor-set"),
    ("skill-portfolio-optimize", "skill-backtest", "portfolio-target", "portfolio-target"),
    ("skill-backtest", "skill-ssquant-ai-trader", "evaluation-result", "evaluation-result"),
)
_CHAIN_NAMES = {name for edge in _CHAIN for name in edge[:2]}
_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable(value: object) -> object:
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key not in {"snapshot_id", "generated_at", "validated_at", "scan_time", "last_validated"}}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError(f"nonstandard JSON constant: {value}")


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)


def _validate(value: object, schema_name: str) -> list[str]:
    schema = _load(ROOT / "schema" / schema_name)
    return [error.message for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)]


def _parse_range(value: object) -> list[tuple[str, tuple[int, int, int]]] | None:
    if not isinstance(value, str) or not value or value.strip() != value:
        return None
    parts = value.split(" ")
    if any(not part for part in parts):
        return None
    exact = [part for part in parts if _SEMVER.fullmatch(part)]
    if exact:
        return [("", tuple(map(int, exact[0].split(".")) ))] if len(parts) == 1 else None
    result = []
    for part in parts:
        match = re.fullmatch(r"(>=|>|<=|<)(.+)", part)
        if match is None or any(part == f"{op}{'.'.join(map(str, version))}" for op, version in result):
            return None
        if _SEMVER.fullmatch(match.group(2)) is None:
            return None
        result.append((match.group(1), tuple(map(int, match.group(2).split(".")))))
    return result


def _satisfies(version: str, range_: str) -> bool:
    if _SEMVER.fullmatch(version) is None:
        return False
    actual = tuple(map(int, version.split(".")))
    clauses = _parse_range(range_)
    return clauses is not None and all(
        (op == "" and actual == wanted) or (op == ">=" and actual >= wanted) or
        (op == ">" and actual > wanted) or (op == "<=" and actual <= wanted) or (op == "<" and actual < wanted)
        for op, wanted in clauses
    )


def _diagnostics(asset: object, envelope: dict, profiles: dict) -> list[dict]:
    interface = asset.get("interface") if isinstance(asset, dict) else None
    if not isinstance(interface, dict) or interface.get("mode") not in {"structured", "hybrid"}:
        return []
    known = {(row["id"], row["version"]) for row in profiles["items"]}
    if interface.get("envelope") != {"name": envelope["name"], "version": "1.0.0"}:
        return [{"code": "interface-envelope", "path": "$.interface.envelope"}]
    result = []
    outputs, inputs = interface.get("outputs", []), interface.get("inputs", [])
    if not isinstance(outputs, list):
        result.append({"code": "interface-output", "path": "$.interface.outputs"}); outputs = []
    if not isinstance(inputs, list):
        result.append({"code": "interface-input", "path": "$.interface.inputs"}); inputs = []
    for index, value in enumerate(outputs):
        if not isinstance(value, dict) or set(value) != {"profile", "version"} or (value.get("profile"), value.get("version")) not in known:
            result.append({"code": "interface-output", "path": f"$.interface.outputs[{index}]"})
    for index, value in enumerate(inputs):
        if not isinstance(value, dict) or set(value) != {"profile", "version_range", "required"} or type(value.get("required")) is not bool or value.get("profile") not in {x[0] for x in known} or _parse_range(value.get("version_range")) is None:
            result.append({"code": "interface-input", "path": f"$.interface.inputs[{index}]"})
    return result


def _edges(assets: list, adapters: list) -> list[dict]:
    """Recompute compatible edges from snapshot declarations and trusted adapters only."""
    graph = {}
    for adapter in adapters:
        source, target = adapter["source"], adapter["target"]
        graph.setdefault((source["profile"], source["version"]), []).append((adapter["id"], target["profile"], target["version"]))
    result = []
    for producer in assets:
        pi = producer.get("interface", {})
        for consumer in assets:
            ci = consumer.get("interface", {})
            if producer is consumer or pi.get("mode") not in {"structured", "hybrid"} or ci.get("mode") not in {"structured", "hybrid"}:
                continue
            for output in pi.get("outputs", []):
                for input_ in ci.get("inputs", []):
                    routes, visited = [((), (output["profile"], output["version"]))], set()
                    while routes:
                        route, node = routes.pop(0)
                        if node in visited: continue
                        visited.add(node)
                        if node[0] == input_["profile"] and _satisfies(node[1], input_["version_range"]):
                            result.append({"producer": producer["name"], "consumer": consumer["name"], "output": {"profile": output["profile"], "version": output["version"]}, "input": {"profile": input_["profile"], "version_range": input_["version_range"], "required": input_["required"]}, "status": "compatible" if not route else "adapter-required", "adapter_path": list(route)})
                            break
                        routes.extend((route + (aid,), (profile, version)) for aid, profile, version in sorted(graph.get(node, [])))
    return [json.loads(value) for value in sorted({json.dumps(edge, sort_keys=True, separators=(",", ":")) for edge in result})]


def _closed_chain(assets: list, edges: list, lineage: dict, envelope: dict, mappings: dict) -> bool:
    by_name = {asset.get("name"): asset for asset in assets if isinstance(asset, dict)}
    actual = {(edge["producer"], edge["consumer"], edge["output"]["profile"], edge["input"]["profile"]) for edge in edges}
    first = lineage["artifacts"][0]
    mapping = next((row for row in mappings["items"] if row["id"] == first["source_mapping_id"]), None)
    producer = by_name.get(first["producer"])
    return (set(by_name) == _CHAIN_NAMES and actual == set(_CHAIN) and mapping is not None and producer is not None
            and producer.get("interface", {}).get("outputs") == [{"profile": first["profile"], "version": first["version"]}]
            and producer["interface"].get("envelope") == {"name": envelope["name"], "version": "1.0.0"}
            and mapping.get("target", {}).get("profile") == {"id": first["profile"], "version": first["version"]})


def verify(snapshot_path: Path, registry_path: Path, readmes: tuple[Path, ...] = (), expected_contract_mode: str | None = None) -> None:
    if expected_contract_mode not in {None, "audit", "enforce"}:
        raise ValueError("expected_contract_mode must be audit or enforce")
    try:
        snapshot, registry = _load(snapshot_path), _load(registry_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid artifact JSON: {error}") from error
    errors = _validate(snapshot, "catalog-snapshot.schema.json") + _validate(registry, "registry.schema.json")
    if not isinstance(snapshot, dict) or not isinstance(registry, list):
        errors.append("snapshot or registry root has invalid type")
    else:
        try:
            envelope, profiles, adapters, mappings = load_contract_catalogs(ROOT)
            lineage = load_core_lineage(ROOT)
            taxonomy = _load(ROOT / "schema" / "taxonomy.v1.json")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"trusted catalog load failed: {error}")
            envelope = profiles = adapters = mappings = lineage = taxonomy = None
        expected_id = "sha256:" + hashlib.sha256(canonical(stable(snapshot))).hexdigest()
        if snapshot.get("snapshot_id") != expected_id:
            errors.append("snapshot_id does not match canonical content")
        if canonical(registry) != canonical(public_registry_projection(snapshot)):
            errors.append("registry does not exactly equal the snapshot public projection")
        names = [asset.get("name") for asset in snapshot.get("assets", []) if isinstance(asset, dict)]
        if not names or any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
            errors.append("snapshot assets must have nonempty unique names")
        expected_resources = [{"name": name, "url": f"https://github.com/quantskills/{name}"} for name in RESOURCE_NAMES]
        if snapshot.get("resources") != expected_resources:
            errors.append("snapshot resources must be the four closed resources")
        if any(item.get("snapshot_id") != snapshot.get("snapshot_id") for item in registry if isinstance(item, dict)):
            errors.append("registry rows do not share snapshot_id")
        if envelope is not None:
            for key, expected in (("envelope", envelope), ("profiles", profiles), ("adapters", adapters), ("provider_mappings", mappings), ("taxonomy", taxonomy)):
                if canonical(snapshot.get(key)) != canonical(expected): errors.append(f"{key} does not match trusted canonical catalog")
            diagnostics = sorted((item for asset in snapshot.get("assets", []) for item in _diagnostics(asset, envelope, profiles)), key=lambda item: canonical(item))
            edges = _edges(snapshot.get("assets", []), adapters["items"])
            if canonical(snapshot.get("interface_diagnostics")) != canonical(diagnostics): errors.append("interface diagnostics do not match independent validation")
            if canonical(snapshot.get("compatibility_edges")) != canonical(edges): errors.append("compatibility edges do not match independent validation")
            closed = not diagnostics and _closed_chain(snapshot.get("assets", []), edges, lineage, envelope, mappings)
            expected_lineage = lineage if closed else {"version": "1.0.0", "artifacts": []}
            if canonical(snapshot.get("core_lineage")) != canonical(expected_lineage): errors.append("core lineage does not match trusted physical lineage")
            if snapshot.get("contract_mode") == "enforce" and not closed: errors.append("enforce snapshot is not the approved closed core chain")
            if expected_contract_mode == "enforce" and (snapshot.get("contract_mode") != "enforce" or not closed): errors.append("expected enforce snapshot is not the approved closed core chain")
            if expected_contract_mode == "audit" and snapshot.get("contract_mode") != "audit": errors.append("snapshot does not have expected audit contract mode")
    for readme in readmes:
        text = readme.read_text(encoding="utf-8")
        starts, ends = text.count("<!-- registry-snapshot:start -->"), text.count("<!-- registry-snapshot:end -->")
        markers = re.findall(r"<!-- registry-snapshot:start -->.*?`(sha256:[0-9a-f]{64})`.*?<!-- registry-snapshot:end -->", text, re.S)
        if starts != 1 or ends != 1 or len(markers) != 1 or markers[0] != snapshot.get("snapshot_id"):
            errors.append(f"README snapshot marker mismatch: {readme.name}")
    if errors:
        raise ValueError("; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("snapshot", nargs="?", default="catalog.snapshot.json"); parser.add_argument("registry", nargs="?", default="registry.json"); parser.add_argument("--readme", action="append", default=[]); parser.add_argument("--expected-contract-mode", choices=("audit", "enforce"))
    args = parser.parse_args(); verify(Path(args.snapshot), Path(args.registry), tuple(Path(path) for path in args.readme), args.expected_contract_mode); print("catalog artifacts verification passed")


if __name__ == "__main__": main()
