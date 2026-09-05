from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


DATASET_SCHEMA = "quantskills.public-score-dataset.v2"
RECORD_SCHEMA = "quantskills.public-score-record.v2"
POLICY_ID = "shadow-category-quartile.v1"
NON_SCOREABLE_ASSETS = {"skill-template", "agent-template"}
PUBLICATIONS = (
    ("publication.v12.13", "PublicationV1213", "central/shadow-assessment.json"),
    ("publication.v12.14", "PublicationV1214", "central/shadow-assessment.b88c492.retry1.json"),
    ("publication.v12.16", "PublicationV1216", "central/shadow-assessment.json"),
    ("publication.v12.20", "PublicationV1220", "central/shadow-assessment.json"),
    ("publication.v12.21", "PublicationV1221", "central/shadow-assessment.retry3.json"),
    ("publication.v12.22", "PublicationV1222", "control/similarity-result.authorization.json"),
    ("publication.v12.23", "PublicationV1223", "central/completion-decision.authorization.json"),
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def registry_assets(value: object) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("assets"), list):
        return value["assets"]
    raise ValueError("invalid Registry projection")


def _asset_name(asset: object, source: str) -> str:
    if not isinstance(asset, dict) or not isinstance(asset.get("name"), str) or not asset["name"]:
        raise ValueError(f"invalid {source} asset name")
    return asset["name"]


def _unique_assets(value: object, source: str) -> dict[str, dict]:
    assets = registry_assets(value)
    result: dict[str, dict] = {}
    for asset in assets:
        name = _asset_name(asset, source)
        if name in result:
            raise ValueError(f"duplicate {source} asset: {name}")
        result[name] = asset
    return result


def _snapshot_id(value: object) -> str | None:
    return value.get("snapshot_id") if isinstance(value, dict) and isinstance(value.get("snapshot_id"), str) else None


def _evaluation_eligible(asset: dict) -> bool:
    """Return the explicit score eligibility marker, defaulting to eligible.

    Catalog v1 has no mandatory evaluation field.  When a future snapshot
    supplies one, honoring an explicit false marker lets orchestration-only
    assets opt out without baking asset names into the exporter.
    """
    markers = []
    for key in ("evaluation_eligible", "score_eligible"):
        if key in asset:
            markers.append(asset[key])
    evaluation = asset.get("evaluation")
    if isinstance(evaluation, dict) and "eligible" in evaluation:
        markers.append(evaluation["eligible"])
    if any(not isinstance(marker, bool) for marker in markers):
        raise ValueError(f"invalid evaluation eligibility marker: {asset.get('name')}")
    if markers and len(set(markers)) != 1:
        raise ValueError(f"conflicting evaluation eligibility markers: {asset.get('name')}")
    return markers[0] if markers else True


def expected_scoring_asset_ids(catalog: object, registry: object) -> set[str]:
    """Derive the closed set of assets that the current score projection must cover.

    ``catalog.snapshot.json`` is the complete asset directory and
    ``registry.json`` is its backward-compatible public projection.  The
    latter may omit deprecated entries, but it must not introduce an asset
    absent from the catalog.  The catalog's explicit eligibility marker is
    the only opt-out; absent a marker an asset is expected to be scored.
    """
    catalog_by_name = _unique_assets(catalog, "catalog")
    registry_by_name = _unique_assets(registry, "registry")
    catalog_snapshot = _snapshot_id(catalog)
    registry_snapshot = _snapshot_id(registry)
    if catalog_snapshot and registry_snapshot and catalog_snapshot != registry_snapshot:
        raise ValueError("catalog/registry snapshot mismatch")
    row_snapshots = {
        asset.get("snapshot_id")
        for asset in registry_by_name.values()
        if isinstance(asset.get("snapshot_id"), str)
    }
    if len(row_snapshots) > 1 or (catalog_snapshot and row_snapshots and row_snapshots != {catalog_snapshot}):
        raise ValueError("registry assets do not share one catalog snapshot")
    unexpected = sorted(set(registry_by_name) - set(catalog_by_name))
    if unexpected:
        raise ValueError(f"registry contains assets absent from catalog: {', '.join(unexpected)}")
    return {
        name for name, asset in catalog_by_name.items()
        if name not in NON_SCOREABLE_ASSETS and _evaluation_eligible(asset)
    }


def expected_scoring_count(catalog: object, registry: object) -> int:
    expected = expected_scoring_asset_ids(catalog, registry)
    if not expected:
        raise ValueError("current public catalog has no scoreable assets")
    return len(expected)


# Short aliases are kept for callers that describe this as the scoreable set.
scoring_asset_ids = expected_scoring_asset_ids
scoreable_asset_ids = expected_scoring_asset_ids


def _record_policy_marker(record: dict) -> tuple[str | None, bool]:
    markers: list[tuple[str, object]] = []
    for key in ("score_policy", "scoring_policy", "policy_id", "scoring_policy_id"):
        if key in record:
            markers.append((key, record[key]))
    scoring = record.get("scoring")
    if isinstance(scoring, dict):
        for key in ("policy", "policy_id"):
            if key in scoring:
                markers.append((f"scoring.{key}", scoring[key]))
    if not markers:
        return None, False
    values = [value for _, value in markers]
    if not all(isinstance(value, str) and value for value in values) or len(set(values)) != 1:
        raise ValueError("score policy cohort is missing or inconsistent")
    return values[0], True


def scoring_cohort(records: list[dict]) -> tuple[str | None, str]:
    """Return the one policy/formula cohort represented by public records.

    Older public rows do not carry a policy id, so the fixed Registry policy
    is represented by ``None`` and the formula remains the binding cohort
    field.  A policy marker, when present, must be present and equal on every
    row.  ``score_comparability`` is intentionally not part of this key: the
    existing publication rows use publication-specific comparability labels
    while sharing the same scoring formula.
    """
    if not isinstance(records, list) or not records:
        raise ValueError("score projection has no records to establish a scoring cohort")
    formulas: set[str] = set()
    policies: list[str | None] = []
    marker_presence: set[bool] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid score record for scoring cohort")
        formula = record.get("score_formula")
        if not isinstance(formula, str) or not formula:
            raise ValueError(f"score formula cohort is undetermined: {record.get('asset_id')}")
        formulas.add(formula)
        policy, present = _record_policy_marker(record)
        policies.append(policy)
        marker_presence.add(present)
    if len(formulas) != 1:
        raise ValueError("mixed score formula cohort")
    if len(marker_presence) != 1 or len(set(policies)) != 1:
        raise ValueError("mixed or undetermined score policy cohort")
    return policies[0], next(iter(formulas))


def validate_scoring_cohort(records: list[dict], expected_policy: str | None = None) -> tuple[str | None, str]:
    policy, formula = scoring_cohort(records)
    if expected_policy is not None and policy is not None and policy != expected_policy:
        raise ValueError(f"unsupported score policy cohort: {policy}")
    return policy, formula


def envelope_payload(envelope: dict) -> dict:
    if "payload_b64" not in envelope:
        return envelope
    return json.loads(base64.b64decode(envelope["payload_b64"], validate=True))


def observation(envelope: dict) -> dict:
    payload = envelope_payload(envelope)
    return payload.get("observation", payload)


def asset_from_envelope(envelope: dict) -> str:
    value = observation(envelope).get("asset_id")
    if not isinstance(value, str) or not value:
        raise ValueError("signed envelope does not identify an asset")
    return value


def signed_envelopes(runtime: Path) -> tuple[dict[str, str], str]:
    hashes: dict[str, str] = {}
    for path in sorted((runtime / "lanes").rglob("envelope.json")):
        envelope = read_json(path)
        asset_id = asset_from_envelope(envelope)
        if asset_id in hashes:
            raise ValueError(f"duplicate signed envelope: {asset_id}")
        hashes[asset_id] = file_digest(path)
    return hashes, digest({key: hashes[key] for key in sorted(hashes)})


def rows_root(connection: sqlite3.Connection, table: str, order_key: str) -> tuple[str, int]:
    hashes: dict[str, str] = {}
    for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order_key}"):
        value = dict(row)
        if table == "attestations":
            key = asset_from_envelope(json.loads(value["envelope"]))
        else:
            key = f'{value["asset_id"]}::{value["score_key"]}'
        if key in hashes:
            raise ValueError(f"duplicate {table} key: {key}")
        hashes[key] = digest(value)
    return digest({key: hashes[key] for key in sorted(hashes)}), len(hashes)


def security_for_request(connection: sqlite3.Connection, request_id: str, runtime: Path, asset_id: str) -> dict:
    row = connection.execute(
        """
        SELECT s.status, s.evidence_digest
        FROM measurement_requests r
        JOIN security_scans s ON s.skey = r.security_scan_key
        WHERE r.request_id = ?
        """,
        (request_id,),
    ).fetchone()
    if row is not None and row["status"] in {"pass", "pass_with_warning"}:
        return dict(row)
    request = connection.execute(
        "SELECT security_scan_key FROM measurement_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    candidates = list((runtime / "lanes").glob(f"*/work/{asset_id}/security-v4.json"))
    if request is None or len(candidates) != 1:
        raise ValueError(f"missing eligible security binding: {request_id}")
    fallback = read_json(candidates[0])
    if fallback.get("skey") != request["security_scan_key"] or fallback.get("status") not in {"pass", "pass_with_warning"}:
        raise ValueError(f"invalid eligible security binding: {request_id}")
    return {"status": fallback["status"], "evidence_digest": fallback["evidence_digest"]}


def build_record(publication: str, row: sqlite3.Row, attestation: sqlite3.Row, security: sqlite3.Row,
                 envelope_sha256: str, category: str) -> dict:
    score = json.loads(row["score"])
    payload = observation(json.loads(attestation["envelope"]))
    featured = score.get("diagnostics", {}).get("featured", {})
    regressions = featured.get("material_core_regressions") or []
    return {
        "schema": RECORD_SCHEMA,
        "asset_id": row["asset_id"],
        "kind": "agent" if row["asset_id"].startswith("agent-") else "skill",
        "category": category,
        "repo": row["repo"],
        "commit_sha": row["commit_sha"],
        "source_publication": publication,
        "source_request_id": row["request_id"],
        "score_key": row["score_key"],
        "score_formula": score["formula"],
        "score_comparability": score["score_comparability"],
        "security": {"status": security["status"], "evidence_digest": security["evidence_digest"]},
        "scores": score["display"],
        "featured": {
            "status": featured.get("status"),
            "score": featured.get("score"),
            "reason": featured.get("reason"),
            "affects_total": bool(featured.get("affects_total", False)),
            "material_core_regression_count": len(regressions),
        },
        "metrics": {
            key: (score.get("metrics") or {}).get(key)
            for key in ("artifact_outcome", "competition_eligible", "evaluation_tier", "reliability", "trigger_f1")
        },
        "usage": {
            "model_calls": payload.get("model_calls"),
            "core_model_calls": payload.get("core_model_calls", 16),
            "featured_model_calls": payload.get("featured_model_calls", 0),
            "recovery_model_calls": payload.get("recovery_model_calls", payload.get("adaptive_calls", 0)),
            "total_tokens": payload.get("total_tokens"),
            "elapsed_ms": payload.get("elapsed_ms"),
            "token_accounting": payload.get("token_accounting", "complete"),
        },
        "integrity": {
            "measurement_digest": row["measurement_digest"],
            "attestation_key": attestation["attestation_key"],
            "attestation_payload_digest": attestation["payload_digest"],
            "attestation_key_id": attestation["key_id"],
            "signed_envelope_sha256": envelope_sha256,
            "score_row_sha256": digest(dict(row)),
        },
    }


def select_recommendations(records: list[dict], listed_assets: set[str]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        eligible = (
            record["asset_id"] in listed_assets
            and record["security"]["status"] in {"pass", "pass_with_warning"}
            and record["metrics"].get("reliability") == 100
            and record["featured"].get("material_core_regression_count") == 0
        )
        if eligible:
            groups.setdefault((record["kind"], record["category"]), []).append(record)

    selected: list[dict] = []
    for group, rows in sorted(groups.items()):
        ranked = sorted(rows, key=lambda row: (-row["scores"]["total"], row["asset_id"]))
        count = max(1, math.ceil(len(ranked) * 0.25))
        for rank, row in enumerate(ranked[:count], start=1):
            selected.append({
                "asset_id": row["asset_id"],
                "kind": row["kind"],
                "category": row["category"],
                "group": f"{group[0]}:{group[1]}",
                "rank": rank,
                "group_size": len(ranked),
                "core": row["scores"]["total"],
                "source_publication": row["source_publication"],
                "score_record_sha256": digest(row),
            })
    return sorted(selected, key=lambda row: (row["group"], row["rank"], row["asset_id"]))


GENERATED_EVALUATION_FILES = (
    "current-scores.json",
    "selection-policy.v1.json",
    "recommended.snapshot.json",
    "manifest.json",
)


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return "".join(canonical(row).decode("utf-8") + "\n" for row in rows).encode("utf-8")


def _copy_existing_output(output: Path, stage: Path) -> None:
    if not output.exists():
        return
    if not output.is_dir():
        raise ValueError(f"evaluation output root is not a directory: {output}")
    shutil.copytree(output, stage, dirs_exist_ok=True)


def promote_evaluation_artifacts(stage: Path, output: Path, relative_files: list[str] | tuple[str, ...]) -> None:
    """Replace a complete staged projection, restoring every old file on failure."""
    destinations = [output / relative for relative in relative_files]
    previous = {destination: destination.read_bytes() if destination.exists() else None for destination in destinations}
    try:
        for relative in sorted(relative_files):
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / relative, destination)
    except Exception:
        for destination, old in previous.items():
            if old is None:
                if destination.exists():
                    destination.unlink()
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(old)
        raise


def _score_asset_set_error(expected: set[str], observed: set[str]) -> str:
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    details = []
    if missing:
        details.append(f"missing={','.join(missing)}")
    if unexpected:
        details.append(f"unexpected={','.join(unexpected)}")
    return "; ".join(details) or "unknown mismatch"


def project_current_records(current: dict[str, dict], expected_ids: set[str]) -> list[dict]:
    observed_ids = set(current)
    missing_ids = expected_ids - observed_ids
    if missing_ids:
        raise ValueError(
            f"current score asset set mismatch: expected {len(expected_ids)}, found {len(observed_ids)} "
            f"({_score_asset_set_error(expected_ids, observed_ids)})"
        )
    # Signed observations for assets that left the catalog remain in immutable
    # publication history, but not in current or recommended projections.
    return [current[key] for key in sorted(expected_ids)]


def export_public_evaluations(
    source_root: Path,
    catalog_path: Path,
    registry_path: Path,
    output_root: Path,
    generated_at: str,
) -> dict:
    """Build and atomically publish the full and recommendation projections."""
    generated = datetime.fromisoformat(generated_at)
    if generated.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
    generated_at_text = generated.isoformat(timespec="seconds")

    catalog = read_json(catalog_path)
    registry = read_json(registry_path)
    expected_ids = expected_scoring_asset_ids(catalog, registry)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("snapshot_id"), str):
        raise ValueError("catalog snapshot id is required")
    census = read_json(source_root / "PublicationV1213" / "census" / "private.json")
    if not isinstance(census, dict) or not isinstance(census.get("items"), list):
        raise ValueError("invalid evaluation census")
    categories = {item["asset_id"]: item["category"] for item in census["items"]}
    catalog_assets = _unique_assets(catalog, "catalog")
    categories.update({name: asset["category"] for name, asset in catalog_assets.items() if "category" in asset})
    listed_assets = set(_unique_assets(registry, "registry"))

    output = output_root.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=f".{output.name}.evaluation-stage-") as temporary:
        stage = Path(temporary)
        _copy_existing_output(output, stage)
        publication_dir = stage / "publications"
        publication_dir.mkdir(parents=True, exist_ok=True)

        current: dict[str, dict] = {}
        publication_manifests: list[dict] = []
        observation_count = 0
        for publication, runtime_name, control_relative in PUBLICATIONS:
            runtime = source_root / runtime_name
            db_path = runtime / "central" / "evaluation.sqlite3"
            control_path = runtime / control_relative
            envelope_hashes, envelope_root = signed_envelopes(runtime)
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute("SELECT * FROM score_records ORDER BY asset_id").fetchall()
                publication_records = []
                for row in rows:
                    asset_id = row["asset_id"]
                    attestation = connection.execute(
                        "SELECT * FROM attestations WHERE request_id = ?", (row["request_id"],)
                    ).fetchone()
                    if attestation is None or asset_id not in envelope_hashes or asset_id not in categories:
                        raise ValueError(f"incomplete publication binding: {publication}/{asset_id}")
                    record = build_record(
                        publication, row, attestation, security_for_request(connection, row["request_id"], runtime, asset_id),
                        envelope_hashes[asset_id], categories[asset_id],
                    )
                    publication_records.append(record)
                    current[asset_id] = record
                score_root, score_count = rows_root(connection, "score_records", "asset_id")
                attestation_root, attestation_count = rows_root(connection, "attestations", "request_id")
            finally:
                connection.close()

            if not (len(publication_records) == score_count == attestation_count == len(envelope_hashes)):
                raise ValueError(f"publication count mismatch: {publication}")
            observation_count += len(publication_records)
            publication_manifests.append({
                "publication": publication,
                "observation_count": len(publication_records),
                "control_artifact_sha256": file_digest(control_path),
                "score_rows_root": score_root,
                "attestation_rows_root": attestation_root,
                "signed_envelope_files_root": envelope_root,
            })
            (publication_dir / f"{publication}.jsonl").write_bytes(_jsonl_bytes(publication_records))

        records = project_current_records(current, expected_ids)
        validate_scoring_cohort(records, POLICY_ID)

        dataset = {
            "schema": DATASET_SCHEMA,
            "generated_at": generated_at_text,
            "mode": "shadow",
            "record_count": len(records),
            "historical_observation_count": observation_count,
            "catalog_snapshot_id": catalog["snapshot_id"],
            "publication_precedence": [row[0] for row in PUBLICATIONS],
            "records": records,
        }
        write_json(stage / "current-scores.json", dataset)

        policy = {
            "schema": "quantskills.recommendation-policy.v1",
            "policy_id": POLICY_ID,
            "status": "shadow",
            "grouping": ["kind", "category"],
            "selection": "top_25_percent_by_core",
            "minimum_reliability": 100,
            "exclude_material_core_regression": True,
            "requires_active_registry_listing": True,
            "affects_registry": False,
            "endorsement": False,
        }
        policy["policy_digest"] = digest(policy)
        write_json(stage / "selection-policy.v1.json", policy)
        recommendations = select_recommendations(records, listed_assets)
        recommended = {
            "schema": "quantskills.recommended-snapshot.v1",
            "generated_at": generated_at_text,
            "status": "shadow",
            "catalog_snapshot_id": catalog["snapshot_id"],
            "score_dataset_sha256": file_digest(stage / "current-scores.json"),
            "policy_id": policy["policy_id"],
            "policy_digest": policy["policy_digest"],
            "record_count": len(recommendations),
            "records": recommendations,
        }
        write_json(stage / "recommended.snapshot.json", recommended)

        release_files = sorted(
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        )
        manifest = {
            "schema": "quantskills.public-evaluation-manifest.v1",
            "generated_at": generated_at_text,
            "integrity_model": "signed-source-attestations-plus-sha256-public-projection",
            "record_count": len(records),
            "historical_observation_count": observation_count,
            "catalog_snapshot_id": catalog["snapshot_id"],
            "publications": publication_manifests,
            "files": {name: file_digest(stage / name) for name in release_files},
        }
        manifest["snapshot_digest"] = digest(manifest)
        write_json(stage / "manifest.json", manifest)
        publication_files = [f"publications/{publication}.jsonl" for publication, _, _ in PUBLICATIONS]
        promote_evaluation_artifacts(stage, output, [*GENERATED_EVALUATION_FILES, *publication_files])

    return {
        "ok": True,
        "records": len(records),
        "observations": observation_count,
        "recommended": len(recommendations),
        "snapshot_digest": manifest["snapshot_digest"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()
    print(json.dumps(export_public_evaluations(
        args.source_root, args.catalog, args.registry, args.output_root, args.generated_at,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
