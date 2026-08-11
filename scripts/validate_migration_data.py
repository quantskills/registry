#!/usr/bin/env python3
"""Fail-closed validator for reviewed catalog migration inputs."""
from __future__ import annotations
import argparse, csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["name", "project_type", "category", "subcategory", "primary_stage", "workflow_stages", "summary_zh", "summary_en", "interface_candidate", "review_status", "evidence"]
STATUSES = {"approved", "needs-maintainer", "blocked"}
MODES = {"structured", "hybrid", "natural-language", "unknown"}
WAVES = {"structured-existing", "core-chain", "structured-remaining", "non-structured-review", "agent-runtime"}
CORE = {"skill-pandadata-warehouse", "skill-factor-mining-pandaai", "skill-factor-grouped-wrapper", "skill-portfolio-optimize", "skill-backtest", "skill-ssquant-ai-trader"}
BAD = re.compile(r"\b(?:official|certified|guaranteed|profit|returns?)\b|保证收益|稳赚", re.I)

def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))

def fail(message: str) -> None:
    raise ValueError(message)

def validate(inventory_path: Path, assignments_path: Path, interfaces_path: Path, waves_path: Path, enforce: bool = False, expected_structured: int | None = None) -> dict:
    inventory = load(inventory_path)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("assets"), list) or not isinstance(inventory.get("sha256"), str): fail("invalid inventory")
    assets = inventory["assets"]
    names = [row.get("name") for row in assets if isinstance(row, dict)]
    if len(names) != len(assets) or any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names): fail("invalid inventory names")
    project_type = {name: "agent" if name.startswith("agent-") else "skill" if name.startswith("skill-") else None for name in names}
    if any(value is None for value in project_type.values()): fail("invalid inventory asset prefix")
    with assignments_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle); rows = list(reader)
        if reader.fieldnames != COLUMNS: fail("invalid assignment columns")
    row_names = [row.get("name") for row in rows]
    if len(rows) != len(names) or len(set(row_names)) != len(rows) or set(row_names) != set(names): fail("assignment join failed")
    taxonomy = load(ROOT / "schema" / "taxonomy.v1.json")
    stages = taxonomy["workflow_stages"]
    subcategories = {item["id"]: category for category, value in taxonomy["categories"].items() for item in value["subcategories"]}
    covered = set()
    for row in rows:
        stages_row = row["workflow_stages"].split("|")
        if not stages_row or stages_row != sorted(set(stages_row), key=stages.index): fail("workflow stages are not taxonomy ordered")
        if row["primary_stage"] not in stages_row or any(stage not in stages for stage in stages_row): fail("invalid workflow stages")
        if row["project_type"] != project_type[row["name"]] or subcategories.get(row["subcategory"]) != row["category"]: fail("invalid assignment classification")
        if row["review_status"] not in STATUSES or (enforce and row["review_status"] != "approved"): fail("unapproved assignment")
        if not row["summary_zh"].strip() or not row["summary_en"].strip() or row["summary_en"].strip().lower() == row["name"] or BAD.search(row["summary_zh"] + " " + row["summary_en"]): fail("invalid summary")
        covered.update(stages_row)
    if set(stages) != covered: fail("stage coverage failed")
    audit, wave_doc = load(interfaces_path), load(waves_path)
    if not isinstance(audit, dict) or set(audit) != {"schema_version", "inventory_sha256", "items"} or audit["inventory_sha256"] != inventory["sha256"] or not isinstance(audit["items"], list): fail("invalid interface audit")
    if not isinstance(wave_doc, dict) or set(wave_doc) != {"schema_version", "inventory_sha256", "waves"} or wave_doc["inventory_sha256"] != inventory["sha256"] or not isinstance(wave_doc["waves"], dict) or set(wave_doc["waves"]) - WAVES: fail("invalid waves")
    item_keys = {"name", "declaration_readable", "structured_io_explicit", "candidate_mode", "evidence_paths", "detected_formats", "detected_fields", "required_maintainer_decision", "waves", "notes"}
    audit_by_name = {}
    for item in audit["items"]:
        if not isinstance(item, dict) or set(item) != item_keys or item.get("name") in audit_by_name: fail("invalid interface item")
        if item["candidate_mode"] not in MODES or not isinstance(item["evidence_paths"], list) or not item["evidence_paths"] or item["evidence_paths"] != sorted(set(item["evidence_paths"])) or not all(isinstance(x, str) and x for x in item["evidence_paths"]): fail("invalid interface evidence")
        audit_by_name[item["name"]] = item
    if set(audit_by_name) != set(names): fail("interface join failed")
    assignment_by_name = {row["name"]: row for row in rows}
    memberships = {name: [] for name in names}
    for wave, members in wave_doc["waves"].items():
        if not isinstance(members, list) or members != sorted(set(members)) or not set(members) <= set(names): fail("invalid wave members")
        for name in members: memberships[name].append(wave)
    for name, item in audit_by_name.items():
        if assignment_by_name[name]["interface_candidate"] != item["candidate_mode"] or item["waves"] != sorted(memberships[name]): fail("interface cross-link failed")
        base = [wave for wave in memberships[name] if wave != "core-chain"]
        if len(base) != 1: fail("invalid base wave")
        if project_type[name] == "agent" and base != ["agent-runtime"]: fail("agent wave failed")
        if project_type[name] == "skill" and item["structured_io_explicit"] and base != ["structured-existing"]: fail("structured wave failed")
        if project_type[name] == "skill" and not item["structured_io_explicit"] and base == ["structured-existing"]: fail("unstructured wave failed")
    if CORE <= set(names) and any("core-chain" not in memberships[name] for name in CORE): fail("core chain wave failed")
    structured = sum(item["structured_io_explicit"] for item in audit_by_name.values())
    if expected_structured is not None and structured != expected_structured: fail("unexpected structured count")
    return {"assets": len(names), "approved": sum(row["review_status"] == "approved" for row in rows), "structured": structured}

def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("inventory", "assignments", "interfaces", "waves"): parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--enforce", action="store_true"); parser.add_argument("--expected-structured", type=int)
    args = parser.parse_args()
    print(json.dumps(validate(args.inventory, args.assignments, args.interfaces, args.waves, args.enforce, args.expected_structured), sort_keys=True))
if __name__ == "__main__": main()
