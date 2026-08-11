#!/usr/bin/env python3
"""Read-only migration audit.  Its only write is the caller-selected report."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:
    from .render_migration_proposals import NAME, _dirty, _frontmatter, _git, redact
    from .runtime_policy import evaluate_runtime_policy
except ImportError:
    from render_migration_proposals import NAME, _dirty, _frontmatter, _git, redact
    from runtime_policy import evaluate_runtime_policy


def audit(inventory: Path, assignments: Path, interfaces: Path, workspace: Path) -> dict:
    assets = json.loads(inventory.read_text(encoding="utf-8"))["assets"]
    with assignments.open(encoding="utf-8", newline="") as h: rows = {x["name"]: x for x in csv.DictReader(h)}
    iface = {x["name"]: x for x in json.loads(interfaces.read_text(encoding="utf-8"))["items"]}
    names = [x.get("name", "") for x in assets]
    if len(names) != len(set(names)) or any(not NAME.fullmatch(x) for x in names): raise ValueError("invalid asset name")
    findings, runtime_rows = [], []
    expected_names = set(names)
    for name in sorted(set(rows) - expected_names): findings.append({"name": name, "check": "assignment", "detail": "not in inventory"})
    for name in sorted(set(iface) - expected_names): findings.append({"name": name, "check": "interface", "detail": "not in inventory"})
    for asset in sorted(assets, key=lambda x: x["name"]):
        name, repo = asset["name"], workspace / asset["name"]
        declaration = asset.get("declaration", {}).get("file") or ("AGENTS.md" if name.startswith("agent-") else "SKILL.md")
        _, _, _, malformed = _frontmatter(repo / declaration)
        if not repo.is_dir(): findings.append({"name": name, "check": "repository", "detail": "missing"})
        if _dirty(repo): findings.append({"name": name, "check": "git", "detail": "dirty"})
        if malformed: findings.append({"name": name, "check": "declaration", "detail": malformed})
        if name not in rows: findings.append({"name": name, "check": "assignment", "detail": "missing"})
        if name not in iface: findings.append({"name": name, "check": "interface", "detail": "missing"})
        expected, actual = asset.get("head_sha"), _git(repo, "rev-parse", "HEAD")
        if expected and actual and expected != actual: findings.append({"name": name, "check": "frozen-head", "detail": "mismatch"})
        if repo.is_dir():
            runtime_rows.extend({"name": name, **x} for x in evaluate_runtime_policy(repo, rows.get(name, {}).get("project_type", "agent" if name.startswith("agent-") else "skill")))
    for row in runtime_rows:
        if row["status"] != "pass": findings.append({"name": row["name"], "check": "runtime", "detail": f"{row['runtime']}: {row['status']}"})
    total = len(assets)
    good = total - len({x["name"] for x in findings})
    return redact({"assets": {"numerator": good, "denominator": total}, "runtime": {"numerator": sum(x["status"] == "pass" for x in runtime_rows), "denominator": total * 5}, "findings": findings, "runtime_rows": runtime_rows})


def main() -> int:
    p = argparse.ArgumentParser()
    for key in ("inventory", "assignments", "interfaces", "workspace", "output"): p.add_argument(f"--{key}", required=True, type=Path)
    p.add_argument("--mode", choices=("audit", "enforce"), default="audit")
    a = p.parse_args(); result = audit(a.inventory, a.assignments, a.interfaces, a.workspace)
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if a.mode == "enforce" and result["findings"] else 0


if __name__ == "__main__": raise SystemExit(main())
