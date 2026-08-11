#!/usr/bin/env python3
"""Fail-closed validator for reviewed catalog migration inputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

try:
    # Keep summary semantics identical to the catalog contract.  These helpers
    # are intentionally shared rather than maintaining a second deny-list.
    from catalog_contract import _generic_summary as _catalog_generic_summary
    from catalog_contract import _has_prohibited_claim as _catalog_has_prohibited_claim
except ImportError:  # pragma: no cover - only relevant when copied standalone
    _catalog_generic_summary = None
    _catalog_has_prohibited_claim = None


ROOT = Path(__file__).resolve().parent.parent
COLUMNS = [
    "name",
    "project_type",
    "category",
    "subcategory",
    "primary_stage",
    "workflow_stages",
    "summary_zh",
    "summary_en",
    "interface_candidate",
    "review_status",
    "evidence",
]
SCHEMA_VERSION = "1.0.0"
STATUSES = {"approved", "needs-maintainer", "blocked"}
MODES = {"structured", "hybrid", "natural-language", "not-applicable", "unknown"}
NOT_APPLICABLE_REASONS = {"natural-language-only", "report-only", "orchestration-only"}
WAVES = {
    "structured-existing",
    "core-chain",
    "structured-remaining",
    "non-structured-review",
    "agent-runtime",
}
CORE = {
    "skill-pandadata-warehouse",
    "skill-factor-mining-pandaai",
    "skill-factor-grouped-wrapper",
    "skill-portfolio-optimize",
    "skill-backtest",
    "skill-ssquant-ai-trader",
}
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
NAME_RE = re.compile(r"^(?:skill|agent)-[a-z0-9]+(?:-[a-z0-9]+)*$")
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LETTER_RE = re.compile(r"[A-Za-z]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]*\)")
GENERIC_SUMMARY_RE = re.compile(
    r"^(?:(?:quantskills)(?: [a-z0-9]+){0,3} )?(?:(?:a|an) )?(?:skill|agent) repository$",
    re.I,
)


def load(path: Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise ValueError(message)


def _sorted_unique_strings(value: object) -> bool:
    """Return whether value is a deterministic list of non-empty strings."""
    if not isinstance(value, list):
        return False
    if not all(isinstance(item, str) and item == item.strip() and item for item in value):
        return False
    return value == sorted(set(value))


def _unique_nonempty_strings(value: object) -> bool:
    """Return whether value is a list of unique, non-empty strings."""
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) and item == item.strip() and item for item in value) and len(value) == len(set(value))


def _pipe_list(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parts = value.split("|")
    return _sorted_unique_strings(parts)


def _generic_summary(summary: str, repo_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", summary.lower()).strip()
    if _catalog_generic_summary is not None and _catalog_generic_summary(summary, repo_name):
        return True
    return bool(GENERIC_SUMMARY_RE.fullmatch(normalized))


def _has_prohibited_claim(summary: str) -> bool:
    if _catalog_has_prohibited_claim is None:
        # This fallback is only for a standalone copy.  The normal validator
        # imports the catalog contract implementation above.
        return bool(
            re.search(
                r"\b(?:official|certified|verified|endorsed|production-ready|"
                r"guaranteed returns?|risk-free|safe strategy|investment advice)\b",
                summary,
                re.I,
            )
        )
    return _catalog_has_prohibited_claim(summary)


def _validate_summary(summary_zh: object, summary_en: object, name: str) -> None:
    if not isinstance(summary_zh, str) or not isinstance(summary_en, str):
        fail("invalid summary")
    zh, en = summary_zh.strip(), summary_en.strip()
    # Match the declaration contract's useful-length floor and language
    # requirements while retaining its generous upper bounds.
    if not (8 <= len(zh) <= 120 and HAN_RE.search(zh)):
        fail("invalid summary")
    if not (8 <= len(en) <= 200 and LETTER_RE.search(en)):
        fail("invalid summary")
    for summary in (zh, en):
        if "\n" in summary or "\r" in summary or MARKDOWN_LINK_RE.search(summary):
            fail("invalid summary")
        if _generic_summary(summary, name) or _has_prohibited_claim(summary):
            fail("invalid summary")


def _validate_inventory(inventory: object) -> tuple[list[dict], str, dict[str, str]]:
    if not isinstance(inventory, dict):
        fail("invalid inventory")
    digest = inventory.get("sha256")
    assets = inventory.get("assets")
    if not isinstance(digest, str) or not HASH_RE.fullmatch(digest) or not isinstance(assets, list):
        fail("invalid inventory")
    unsigned = {key: value for key, value in inventory.items() if key != "sha256"}
    expected_digest = "sha256:" + hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != expected_digest:
        fail("inventory hash mismatch")

    rows: list[dict] = []
    project_type: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            fail("invalid inventory asset")
        name = asset.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in project_type:
            fail("invalid inventory names")
        expected = "agent" if name.startswith("agent-") else "skill" if name.startswith("skill-") else None
        if expected is None:
            fail("invalid inventory asset prefix")
        # project_type is optional in the frozen inventory; if present it is
        # still checked against the repository prefix.
        if "project_type" in asset and asset["project_type"] != expected:
            fail("invalid inventory project type")
        if "head_sha" in asset and (
            not isinstance(asset["head_sha"], str) or not GIT_SHA_RE.fullmatch(asset["head_sha"])
        ):
            fail("invalid inventory head sha")
        rows.append(asset)
        project_type[name] = expected
    return rows, digest, project_type


def validate(
    inventory_path: Path,
    assignments_path: Path,
    interfaces_path: Path,
    waves_path: Path,
    enforce: bool = False,
    expected_structured: int | None = None,
) -> dict:
    inventory = load(inventory_path)
    assets, inventory_sha256, project_type = _validate_inventory(inventory)
    names = list(project_type)

    with Path(assignments_path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if reader.fieldnames != COLUMNS:
            fail("invalid assignment columns")
    if len(rows) != len(names):
        fail("assignment join failed")
    if any(not isinstance(row.get(column), str) for row in rows for column in COLUMNS):
        fail("invalid assignment values")
    row_names = [row["name"] for row in rows]
    if len(set(row_names)) != len(rows) or set(row_names) != set(names):
        fail("assignment join failed")

    taxonomy = load(ROOT / "schema" / "taxonomy.v1.json")
    if not isinstance(taxonomy, dict) or not isinstance(taxonomy.get("workflow_stages"), list):
        fail("invalid taxonomy")
    stages = taxonomy["workflow_stages"]
    if not all(isinstance(stage, str) and stage for stage in stages) or len(set(stages)) != len(stages):
        fail("invalid taxonomy")
    subcategories = {
        item["id"]: category
        for category, value in taxonomy.get("categories", {}).items()
        for item in value.get("subcategories", [])
    }
    covered: set[str] = set()
    for row in rows:
        stage_values = row["workflow_stages"].split("|")
        if not _unique_nonempty_strings(stage_values):
            fail("workflow stages are not taxonomy ordered")
        if any(stage not in stages for stage in stage_values) or stage_values != sorted(stage_values, key=stages.index):
            fail("workflow stages are not taxonomy ordered")
        if row["primary_stage"] not in stage_values:
            fail("invalid workflow stages")
        if row["project_type"] != project_type[row["name"]] or subcategories.get(row["subcategory"]) != row["category"]:
            fail("invalid assignment classification")
        if row["interface_candidate"] not in MODES:
            fail("invalid interface candidate")
        if row["review_status"] not in STATUSES or (enforce and row["review_status"] != "approved"):
            fail("unapproved assignment")
        if not _pipe_list(row["evidence"]):
            fail("invalid assignment evidence")
        _validate_summary(row["summary_zh"], row["summary_en"], row["name"])
        covered.update(stage_values)
    if set(stages) != covered:
        fail("stage coverage failed")

    audit, wave_doc = load(interfaces_path), load(waves_path)
    if (
        not isinstance(audit, dict)
        or set(audit) != {"schema_version", "inventory_sha256", "items"}
        or audit.get("schema_version") != SCHEMA_VERSION
        or audit.get("inventory_sha256") != inventory_sha256
        or not HASH_RE.fullmatch(audit.get("inventory_sha256", ""))
        or not isinstance(audit.get("items"), list)
    ):
        fail("invalid interface audit")
    if (
        not isinstance(wave_doc, dict)
        or set(wave_doc) != {"schema_version", "inventory_sha256", "waves"}
        or wave_doc.get("schema_version") != SCHEMA_VERSION
        or wave_doc.get("inventory_sha256") != inventory_sha256
        or not HASH_RE.fullmatch(wave_doc.get("inventory_sha256", ""))
        or not isinstance(wave_doc.get("waves"), dict)
        or set(wave_doc["waves"]) != WAVES
    ):
        fail("invalid waves")

    item_keys = {
        "name",
        "declaration_readable",
        "structured_io_explicit",
        "candidate_mode",
        "evidence_paths",
        "detected_formats",
        "detected_fields",
        "required_maintainer_decision",
        "waves",
        "notes",
    }
    audit_by_name: dict[str, dict] = {}
    for item in audit["items"]:
        if not isinstance(item, dict) or set(item) != item_keys:
            fail("invalid interface item")
        name = item.get("name")
        if not isinstance(name, str) or name in audit_by_name:
            fail("invalid interface item")
        if not isinstance(item["declaration_readable"], bool) or not isinstance(item["structured_io_explicit"], bool):
            fail("invalid interface flags")
        if not isinstance(item["required_maintainer_decision"], bool) or not isinstance(item["notes"], str):
            fail("invalid interface review fields")
        if not isinstance(item["candidate_mode"], str) or item["candidate_mode"] not in MODES:
            fail("invalid interface candidate")
        if item["candidate_mode"] == "not-applicable" and (
            item["structured_io_explicit"] or item["notes"] not in NOT_APPLICABLE_REASONS
        ):
            fail("invalid not-applicable interface")
        if not _sorted_unique_strings(item["evidence_paths"]) or not item["evidence_paths"]:
            fail("invalid interface evidence")
        if not _sorted_unique_strings(item["detected_formats"]) or not _sorted_unique_strings(item["detected_fields"]):
            fail("invalid interface detections")
        if not _sorted_unique_strings(item["waves"]) or not set(item["waves"]) <= WAVES:
            fail("invalid interface waves")
        audit_by_name[name] = item
    if set(audit_by_name) != set(names):
        fail("interface join failed")

    assignment_by_name = {row["name"]: row for row in rows}
    memberships = {name: [] for name in names}
    for wave, members in wave_doc["waves"].items():
        if not _sorted_unique_strings(members) or not set(members) <= set(names):
            fail("invalid wave members")
        for name in members:
            memberships[name].append(wave)
    core_members = wave_doc["waves"]["core-chain"]
    if not set(core_members) <= CORE:
        fail("invalid core chain wave")
    if CORE <= set(names) and core_members != sorted(CORE):
        fail("core chain wave failed")

    for name, item in audit_by_name.items():
        expected_waves = sorted(memberships[name])
        if assignment_by_name[name]["interface_candidate"] != item["candidate_mode"] or item["waves"] != expected_waves:
            fail("interface cross-link failed")
        base = [wave for wave in memberships[name] if wave != "core-chain"]
        if len(base) != 1:
            fail("invalid base wave")
        if project_type[name] == "agent":
            expected_base = "agent-runtime"
        elif item["candidate_mode"] == "not-applicable":
            expected_base = "non-structured-review"
        elif item["structured_io_explicit"]:
            if item["candidate_mode"] not in {"structured", "hybrid"}:
                fail("structured wave failed")
            expected_base = "structured-existing"
        elif item["candidate_mode"] in {"structured", "hybrid"}:
            expected_base = "structured-remaining"
        else:
            expected_base = "non-structured-review"
        if base != [expected_base]:
            fail("candidate wave failed")

    structured = sum(
        item["structured_io_explicit"]
        for name, item in audit_by_name.items()
        if project_type[name] == "skill"
    )
    if expected_structured is not None and structured != expected_structured:
        fail("unexpected structured count")
    return {"assets": len(names), "approved": sum(row["review_status"] == "approved" for row in rows), "structured": structured}


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("inventory", "assignments", "interfaces", "waves"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--expected-structured", type=int)
    args = parser.parse_args()
    try:
        result = validate(args.inventory, args.assignments, args.interfaces, args.waves, args.enforce, args.expected_structured)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
