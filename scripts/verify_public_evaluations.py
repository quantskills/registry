from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts.export_public_evaluations import PUBLICATIONS, canonical, digest, registry_assets, select_recommendations
except ModuleNotFoundError:
    from export_public_evaluations import PUBLICATIONS, canonical, digest, registry_assets, select_recommendations


EXPECTED_PUBLICATION_COUNTS = {
    "publication.v12.13": 209,
    "publication.v12.14": 6,
    "publication.v12.16": 1,
    "publication.v12.20": 1,
    "publication.v12.21": 1,
    "publication.v12.22": 5,
    "publication.v12.23": 1,
}
V1213_ROOTS = {
    "score_rows_root": "f1b44a14dcdeb52b5914f6b03fda2810f050c649afc166c57aac5f0a6bb77679",
    "attestation_rows_root": "6011a1c052ff7598e37c4b6432dc53503daf24b93bb3b58871d82c833c37c974",
    "signed_envelope_files_root": "3f9e6ca71f7e0a32892de65f14c8320cb7ce8ff46e8ec6178f745619800f3394",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_record(record: dict) -> None:
    if record.get("schema") != "quantskills.public-score-record.v2":
        raise ValueError(f"invalid public score schema: {record.get('asset_id')}")
    if record.get("security", {}).get("status") not in {"pass", "pass_with_warning"}:
        raise ValueError(f"security-ineligible record: {record.get('asset_id')}")
    scores = record.get("scores", {})
    if set(scores) != {"behavior", "quality", "token", "total"}:
        raise ValueError(f"invalid score shape: {record.get('asset_id')}")
    calculated = 0.5 * scores["behavior"] + 0.25 * scores["quality"] + 0.25 * scores["token"]
    if abs(calculated - scores["total"]) > 0.03:
        raise ValueError(f"Core formula mismatch: {record.get('asset_id')}")
    if record.get("score_formula") != "score-formula.v9":
        raise ValueError(f"score formula mismatch: {record.get('asset_id')}")
    if not re.fullmatch(r"[0-9a-f]{64}", record.get("integrity", {}).get("signed_envelope_sha256", "")):
        raise ValueError(f"missing signed source reference: {record.get('asset_id')}")


def verify_publication(root: Path) -> dict:
    evaluation_root = root / "evaluations"
    dataset = read_json(evaluation_root / "current-scores.json")
    manifest = read_json(evaluation_root / "manifest.json")
    policy = read_json(evaluation_root / "selection-policy.v1.json")
    recommended = read_json(evaluation_root / "recommended.snapshot.json")
    catalog = read_json(root / "catalog.snapshot.json")
    registry = read_json(root / "registry.json")

    dataset_schema = read_json(evaluation_root / "schemas" / "current-scores.schema.json")
    Draft202012Validator(dataset_schema, format_checker=FormatChecker()).validate(dataset)
    record_validator = Draft202012Validator(dataset_schema["$defs"]["record"])
    Draft202012Validator(
        read_json(evaluation_root / "schemas" / "recommended-snapshot.schema.json"),
        format_checker=FormatChecker(),
    ).validate(recommended)

    records = dataset.get("records", [])
    ids = [row.get("asset_id") for row in records]
    if dataset.get("record_count") != 218 or len(records) != 218 or ids != sorted(ids) or len(set(ids)) != 218:
        raise ValueError("current score dataset must contain 218 unique sorted records")
    if dataset.get("historical_observation_count") != 224:
        raise ValueError("historical observation count mismatch")
    if dataset.get("catalog_snapshot_id") != catalog.get("snapshot_id"):
        raise ValueError("score/catalog snapshot mismatch")
    if dataset.get("publication_precedence") != [row[0] for row in PUBLICATIONS]:
        raise ValueError("publication precedence mismatch")
    for record in records:
        validate_record(record)

    history = []
    for publication, expected in EXPECTED_PUBLICATION_COUNTS.items():
        rows = [json.loads(line) for line in (evaluation_root / "publications" / f"{publication}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        if len(rows) != expected:
            raise ValueError(f"publication observation count mismatch: {publication}")
        for row in rows:
            record_validator.validate(row)
        history.extend(rows)
    if len(history) != 224:
        raise ValueError("publication history mismatch")
    latest: dict[str, dict] = {}
    for publication, _, _ in PUBLICATIONS:
        for row in history:
            if row["source_publication"] == publication:
                latest[row["asset_id"]] = row
    if [latest[key] for key in sorted(latest)] != records:
        raise ValueError("current score projection does not follow publication precedence")

    if policy.get("policy_digest") != digest({key: value for key, value in policy.items() if key != "policy_digest"}):
        raise ValueError("recommendation policy digest mismatch")
    listed_assets = {asset["name"] for asset in registry_assets(registry)}
    expected_recommendations = select_recommendations(records, listed_assets)
    if recommended.get("records") != expected_recommendations:
        raise ValueError("recommendation projection mismatch")
    if recommended.get("catalog_snapshot_id") != catalog.get("snapshot_id"):
        raise ValueError("recommendation/catalog snapshot mismatch")
    if recommended.get("score_dataset_sha256") != file_digest(evaluation_root / "current-scores.json"):
        raise ValueError("recommendation/score snapshot mismatch")

    for name, expected in manifest.get("files", {}).items():
        if file_digest(evaluation_root / name) != expected:
            raise ValueError(f"public evaluation file digest mismatch: {name}")
    unsigned = {key: value for key, value in manifest.items() if key != "snapshot_digest"}
    if manifest.get("snapshot_digest") != hashlib.sha256(canonical(unsigned)).hexdigest():
        raise ValueError("public evaluation manifest digest mismatch")
    roots = {row["publication"]: row for row in manifest.get("publications", [])}
    if {key: roots[key]["observation_count"] for key in roots} != EXPECTED_PUBLICATION_COUNTS:
        raise ValueError("manifest publication counts mismatch")
    if any(roots.get("publication.v12.13", {}).get(key) != value for key, value in V1213_ROOTS.items()):
        raise ValueError("publication.v12.13 immutable roots mismatch")

    patterns = (
        re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(rb"(?:ghp_|github_pat_)[A-Za-z0-9_]{16,}"),
        re.compile(rb"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
        re.compile(rb"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
        re.compile(rb"Cookie:\s*\S+", re.IGNORECASE),
        re.compile(rb"guoyj\.txt", re.IGNORECASE),
        re.compile(rb"(?:[A-Za-z]:\\Users\\|E:\\Quantskills|file:///C:/)", re.IGNORECASE),
    )
    for path in evaluation_root.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            if any(pattern.search(content) for pattern in patterns):
                raise ValueError(f"public safety violation: {path.relative_to(root)}")

    return {"ok": True, "records": len(records), "observations": len(history),
            "recommended": len(expected_recommendations), "snapshot_digest": manifest["snapshot_digest"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(verify_publication(args.root.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
