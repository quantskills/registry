#!/usr/bin/env python3
"""Deep, offline consistency verification for generated catalog artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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
    asset_names = [asset.get("name") for asset in snapshot.get("assets", [])]
    registry_names = [asset.get("name") for asset in registry] if isinstance(registry, list) else []
    if asset_names != registry_names:
        errors.append("registry asset names/order do not exactly match snapshot")
    if len(asset_names) != len(set(asset_names)) or not asset_names:
        errors.append("snapshot assets must be nonempty and unique")
    if [item.get("name") for item in snapshot.get("resources", [])] != RESOURCE_NAMES:
        errors.append("snapshot resources must be the four closed resources")
    if any(item.get("snapshot_id") != snapshot.get("snapshot_id") for item in registry if isinstance(item, dict)):
        errors.append("registry rows do not share snapshot_id")
    if not all(isinstance(snapshot.get(key), dict) and isinstance(snapshot[key].get("items"), list) for key in ("profiles", "adapters")) or not isinstance(snapshot.get("compatibility_edges"), list):
        errors.append("nested catalogs or compatibility edges are malformed")
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
