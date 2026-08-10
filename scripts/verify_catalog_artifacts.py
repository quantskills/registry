#!/usr/bin/env python3
"""Deep, offline consistency verification for generated catalog artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from catalog_projection import public_registry_projection

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_NAMES = [".github", "join", "quantskills", "registry"]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable(value: object) -> object:
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key not in {"snapshot_id", "generated_at", "validated_at", "scan_time", "last_validated"}}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def _validate(value: object, schema_name: str) -> list[str]:
    schema = json.loads((ROOT / "schema" / schema_name).read_text(encoding="utf-8"))
    return [error.message for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)]


def verify(snapshot_path: Path, registry_path: Path, readmes: tuple[Path, ...] = ()) -> None:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    errors = _validate(snapshot, "catalog-snapshot.schema.json") + _validate(registry, "registry.schema.json")
    expected = "sha256:" + hashlib.sha256(canonical(stable(snapshot))).hexdigest()
    if snapshot.get("snapshot_id") != expected:
        errors.append("snapshot_id does not match canonical content")
    expected_registry = public_registry_projection(snapshot) if isinstance(snapshot.get("assets"), list) else []
    asset_names = [asset.get("name") for asset in snapshot.get("assets", [])]
    registry_names = [asset.get("name") for asset in registry] if isinstance(registry, list) else []
    if canonical(registry) != canonical(expected_registry):
        errors.append("registry does not exactly equal the snapshot public projection")
    if len(asset_names) != len(set(asset_names)) or not asset_names:
        errors.append("snapshot assets must be nonempty and unique")
    if [item.get("name") for item in snapshot.get("resources", [])] != RESOURCE_NAMES:
        errors.append("snapshot resources must be the four closed resources")
    if any(item.get("snapshot_id") != snapshot.get("snapshot_id") for item in registry if isinstance(item, dict)):
        errors.append("registry rows do not share snapshot_id")
    if not all(isinstance(snapshot.get(key), dict) and isinstance(snapshot[key].get("items"), list) for key in ("profiles", "adapters")) or not isinstance(snapshot.get("compatibility_edges"), list):
        errors.append("nested catalogs or compatibility edges are malformed")
    if "envelope" in snapshot or "provider_mappings" in snapshot:
        if not all(isinstance(snapshot.get(key), dict) and isinstance(snapshot[key].get("items"), list) for key in ("envelope", "provider_mappings")):
            errors.append("enriched catalogs are malformed")
        else:
            profiles = {(item.get("id"), item.get("version")) for item in snapshot["profiles"]["items"] if isinstance(item, dict)}
            mappings = {item.get("id"): item for item in snapshot["provider_mappings"]["items"] if isinstance(item, dict)}
            for asset in snapshot.get("assets", []):
                lineage = asset.get("lineage") if isinstance(asset, dict) else None
                if lineage is not None:
                    mapping = mappings.get(lineage.get("source_mapping_id")) if isinstance(lineage, dict) else None
                    outputs = asset.get("interface", {}).get("outputs", []) if isinstance(asset.get("interface"), dict) else []
                    if not mapping or not outputs or mapping.get("target", {}).get("profile") != {"id": outputs[0].get("profile"), "version": outputs[0].get("version")}:
                        errors.append("lineage provider mapping cross-reference mismatch")
            for mapping in mappings.values():
                target = mapping.get("target", {}) if isinstance(mapping, dict) else {}
                profile = target.get("profile", {}) if isinstance(target, dict) else {}
                evidence = mapping.get("evidence", {}) if isinstance(mapping, dict) else {}
                if not isinstance(mapping.get("implementation"), dict) or "path" in mapping["implementation"] or (profile.get("id"), profile.get("version")) not in profiles or not isinstance(evidence.get("raw_sha256"), str):
                    errors.append("provider mapping catalog cross-reference mismatch")
            mapping_ids = list(mappings)
            if mapping_ids != sorted(mapping_ids) or len(mapping_ids) != len(snapshot["provider_mappings"]["items"]):
                errors.append("provider mapping IDs must be unique and sorted")
            for mapping in mappings.values():
                target = mapping.get("target", {})
                if (not isinstance(target.get("envelope"), dict)
                        or target["envelope"] != {"name": snapshot["envelope"].get("name"), "version": "1.0.0"}
                        or not re.fullmatch(r"sha256:[0-9a-f]{64}", mapping.get("evidence", {}).get("raw_sha256", ""))):
                    errors.append("provider mapping target or hash is invalid")
            adapter_ids = {item.get("id") for item in snapshot["adapters"]["items"] if isinstance(item, dict)}
            asset_by_name = {item.get("name"): item for item in snapshot.get("assets", []) if isinstance(item, dict)}
            for edge in snapshot.get("compatibility_edges", []):
                if not isinstance(edge, dict) or set(edge) != {"producer", "consumer", "output", "input", "status", "adapter_path"}:
                    errors.append("compatibility edge shape is invalid")
                    continue
                producer, consumer = asset_by_name.get(edge["producer"]), asset_by_name.get(edge["consumer"])
                if producer is None or consumer is None or edge["producer"] == edge["consumer"]:
                    errors.append("compatibility edge endpoint is invalid")
                    continue
                if edge["output"] not in producer.get("interface", {}).get("outputs", []):
                    errors.append("compatibility edge output is not declared")
                if edge["input"] not in consumer.get("interface", {}).get("inputs", []):
                    errors.append("compatibility edge input is not declared")
                if edge["status"] not in {"compatible", "adapter-required"} or not isinstance(edge["adapter_path"], list) or any(item not in adapter_ids for item in edge["adapter_path"]):
                    errors.append("compatibility edge adapter path is invalid")
            for asset in asset_by_name.values():
                lineage = asset.get("lineage")
                if lineage is not None and (set(lineage) != {"source_mapping_id"} or lineage["source_mapping_id"] not in mappings):
                    errors.append("asset lineage mapping is invalid")
    for readme in readmes:
        text = readme.read_text(encoding="utf-8")
        marker = re.search(r"<!-- registry-snapshot:start -->.*?`(sha256:[0-9a-f]{64})`.*?<!-- registry-snapshot:end -->", text, re.S)
        if not marker or marker.group(1) != snapshot.get("snapshot_id"):
            errors.append(f"README snapshot marker mismatch: {readme.name}")
    if errors:
        raise ValueError("; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", nargs="?", default="catalog.snapshot.json")
    parser.add_argument("registry", nargs="?", default="registry.json")
    parser.add_argument("--readme", action="append", default=[])
    args = parser.parse_args()
    verify(Path(args.snapshot), Path(args.registry), tuple(Path(path) for path in args.readme))
    print("catalog artifacts verification passed")


if __name__ == "__main__":
    main()
