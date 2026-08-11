#!/usr/bin/env python3
"""Read-only migration coverage audit; never contacts or writes source repos."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:
    from .render_migration_proposals import _dirty, _frontmatter, redact
    from .runtime_policy import evaluate_runtime_policy
except ImportError:  # direct script execution
    from render_migration_proposals import _dirty, _frontmatter, redact
    from runtime_policy import evaluate_runtime_policy


def audit(inventory: Path, assignments: Path, interfaces: Path, workspace: Path) -> dict:
    assets = json.loads(inventory.read_text(encoding="utf-8"))["assets"]
    interface_names = {x["name"] for x in json.loads(interfaces.read_text(encoding="utf-8"))["items"]}
    with assignments.open(encoding="utf-8", newline="") as handle:
        rows = {x["name"]: x for x in csv.DictReader(handle)}
    findings, runtime_rows = [], []
    for asset in sorted(assets, key=lambda x: x["name"]):
        name, repo = asset["name"], workspace / asset["name"]
        declaration = asset.get("declaration", {}).get("file") or ("AGENTS.md" if name.startswith("agent-") else "SKILL.md")
        _, malformed = _frontmatter(repo / declaration)
        if not repo.is_dir(): findings.append({"name": name, "check": "repository", "detail": "missing"})
        if _dirty(repo): findings.append({"name": name, "check": "git", "detail": "dirty"})
        if malformed: findings.append({"name": name, "check": "declaration", "detail": malformed})
        if name not in rows: findings.append({"name": name, "check": "assignment", "detail": "missing"})
        if name not in interface_names: findings.append({"name": name, "check": "interface", "detail": "missing"})
        runtime_rows.extend([{"name": name, **x} for x in evaluate_runtime_policy(repo, rows.get(name, {}).get("project_type", "agent"))] if repo.is_dir() else [])
    total = len(assets)
    return redact({"assets": {"numerator": total - len({x["name"] for x in findings}), "denominator": total}, "runtime": {"numerator": sum(x["status"] == "pass" for x in runtime_rows), "denominator": total * 5}, "findings": findings, "runtime_rows": runtime_rows})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", required=True, type=Path); p.add_argument("--assignments", required=True, type=Path)
    p.add_argument("--interfaces", required=True, type=Path); p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--mode", choices=("audit", "enforce"), default="audit"); p.add_argument("--output", required=True, type=Path)
    args = p.parse_args(); result = audit(args.inventory, args.assignments, args.interfaces, args.workspace)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if args.mode == "enforce" and result["findings"] else 0


if __name__ == "__main__": raise SystemExit(main())
