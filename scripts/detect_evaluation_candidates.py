"""Detect deterministic evaluation work without contacting asset repositories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.export_public_evaluations import (
        _snapshot_id,
        _unique_assets,
        digest,
        expected_scoring_asset_ids,
        validate_scoring_cohort,
    )
except ModuleNotFoundError:
    from export_public_evaluations import (  # type: ignore
        _snapshot_id,
        _unique_assets,
        digest,
        expected_scoring_asset_ids,
        validate_scoring_cohort,
    )


SCHEMA = "quantskills.evaluation-candidate-diff.v1"


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_key(
    candidate_type: str,
    asset_id: str,
    catalog_snapshot_id: str | None,
    target_commit_sha: str | None,
    current_commit_sha: str | None,
) -> str:
    return "sha256:" + digest({
        "asset_id": asset_id,
        "candidate_type": candidate_type,
        "catalog_snapshot_id": catalog_snapshot_id,
        "current_commit_sha": current_commit_sha,
        "target_commit_sha": target_commit_sha,
    })


def _event(
    candidate_type: str,
    asset_id: str,
    catalog_snapshot_id: str | None,
    target_commit_sha: str | None = None,
    current_commit_sha: str | None = None,
) -> dict:
    event = {
        "asset_id": asset_id,
        "candidate_type": candidate_type,
        "catalog_commit_sha": target_commit_sha,
        "current_commit_sha": current_commit_sha,
    }
    event["idempotency_key"] = _candidate_key(
        candidate_type, asset_id, catalog_snapshot_id, target_commit_sha, current_commit_sha,
    )
    return event


def detect_evaluation_candidates(catalog: object, registry: object, current_scores: object) -> dict:
    """Return new, changed-commit, and offline score candidates.

    The catalog is the complete public asset directory; the Registry may omit
    deprecated rows but cannot add rows outside that directory.  This function
    only reads its three inputs and never contacts or mutates an asset repo.
    """
    if not isinstance(current_scores, dict) or not isinstance(current_scores.get("records"), list):
        raise ValueError("invalid current score projection")
    catalog_by_name = _unique_assets(catalog, "catalog")
    registry_by_name = _unique_assets(registry, "registry")
    expected = expected_scoring_asset_ids(catalog, registry)
    catalog_snapshot_id = _snapshot_id(catalog)

    records = current_scores["records"]
    scores: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("asset_id"), str) or not record["asset_id"]:
            raise ValueError("invalid current score asset id")
        asset_id = record["asset_id"]
        if asset_id in scores:
            raise ValueError(f"duplicate current score asset: {asset_id}")
        scores[asset_id] = record
    cohort = validate_scoring_cohort(records) if records else (None, None)

    target_assets: dict[str, dict] = {}
    for asset_id in sorted(expected):
        asset = catalog_by_name[asset_id]
        catalog_commit = asset.get("commit_sha")
        registry_asset = registry_by_name.get(asset_id)
        if registry_asset is not None:
            registry_commit = registry_asset.get("commit_sha")
            if catalog_commit is not None and registry_commit is not None and catalog_commit != registry_commit:
                raise ValueError(f"catalog/registry commit mismatch: {asset_id}")
            if catalog_commit is None:
                catalog_commit = registry_commit
        if catalog_commit is not None and not isinstance(catalog_commit, str):
            raise ValueError(f"invalid catalog commit sha: {asset_id}")
        target_assets[asset_id] = {"commit_sha": catalog_commit}

    new_candidates = [
        _event("new", asset_id, catalog_snapshot_id, target_assets[asset_id]["commit_sha"])
        for asset_id in sorted(expected - set(scores))
    ]
    changed_candidates = []
    for asset_id in sorted(expected & set(scores)):
        target_commit = target_assets[asset_id]["commit_sha"]
        current_commit = scores[asset_id].get("commit_sha")
        if target_commit is None or current_commit is None:
            raise ValueError(f"cannot determine commit change: {asset_id}")
        if target_commit != current_commit:
            changed_candidates.append(_event(
                "commit_changed", asset_id, catalog_snapshot_id, target_commit, current_commit,
            ))
    offline_candidates = [
        _event("offline", asset_id, catalog_snapshot_id, current_commit_sha=scores[asset_id].get("commit_sha"))
        for asset_id in sorted(set(scores) - expected)
    ]

    result = {
        "schema": SCHEMA,
        "catalog_snapshot_id": catalog_snapshot_id,
        "current_scores_snapshot_id": current_scores.get("catalog_snapshot_id"),
        "scoring_cohort": {"policy_id": cohort[0], "score_formula": cohort[1]},
        "new": new_candidates,
        "commit_changed": changed_candidates,
        "offline": offline_candidates,
    }
    result["counts"] = {
        "new": len(new_candidates),
        "commit_changed": len(changed_candidates),
        "offline": len(offline_candidates),
        "total": len(new_candidates) + len(changed_candidates) + len(offline_candidates),
    }
    result["idempotency_key"] = "sha256:" + digest({key: value for key, value in result.items() if key != "idempotency_key"})
    return result


detect_candidates = detect_evaluation_candidates
build_candidate_diff = detect_evaluation_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect offline evaluation candidates from public snapshots.")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--current-scores", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = detect_evaluation_candidates(
        read_json(args.catalog), read_json(args.registry), read_json(args.current_scores),
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
