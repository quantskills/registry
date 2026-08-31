from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path


DATASET_SCHEMA = "quantskills.public-score-dataset.v2"
RECORD_SCHEMA = "quantskills.public-score-record.v2"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()

    generated_at = datetime.fromisoformat(args.generated_at)
    if generated_at.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
    generated_at_text = generated_at.isoformat(timespec="seconds")

    catalog = read_json(args.catalog)
    census = read_json(args.source_root / "PublicationV1213" / "census" / "private.json")
    categories = {item["asset_id"]: item["category"] for item in census["items"]}
    categories.update({asset["name"]: asset["category"] for asset in catalog["assets"]})
    listed_assets = {asset["name"] for asset in registry_assets(read_json(args.registry))}
    output = args.output_root.resolve()
    publication_dir = output / "publications"
    publication_dir.mkdir(parents=True, exist_ok=True)

    current: dict[str, dict] = {}
    publication_manifests: list[dict] = []
    observation_count = 0
    for publication, runtime_name, control_relative in PUBLICATIONS:
        runtime = args.source_root / runtime_name
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
        with (publication_dir / f"{publication}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("".join(canonical(row).decode("utf-8") + "\n" for row in publication_records))

    records = [current[key] for key in sorted(current)]
    if len(records) != 218:
        raise ValueError(f"expected 218 current score records, found {len(records)}")
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
    write_json(output / "current-scores.json", dataset)

    policy = {
        "schema": "quantskills.recommendation-policy.v1",
        "policy_id": "shadow-category-quartile.v1",
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
    write_json(output / "selection-policy.v1.json", policy)
    recommendations = select_recommendations(records, listed_assets)
    recommended = {
        "schema": "quantskills.recommended-snapshot.v1",
        "generated_at": generated_at_text,
        "status": "shadow",
        "catalog_snapshot_id": catalog["snapshot_id"],
        "score_dataset_sha256": file_digest(output / "current-scores.json"),
        "policy_id": policy["policy_id"],
        "policy_digest": policy["policy_digest"],
        "record_count": len(recommendations),
        "records": recommendations,
    }
    write_json(output / "recommended.snapshot.json", recommended)

    release_files = sorted(
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
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
        "files": {name: file_digest(output / name) for name in release_files},
    }
    manifest["snapshot_digest"] = digest(manifest)
    write_json(output / "manifest.json", manifest)
    print(json.dumps({"ok": True, "records": len(records), "observations": observation_count,
                      "recommended": len(recommendations), "snapshot_digest": manifest["snapshot_digest"]}, sort_keys=True))


if __name__ == "__main__":
    main()
