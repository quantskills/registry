#!/usr/bin/env python3
"""Generate review-only migration proposals without changing source assets."""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

import yaml

try:
    from .runtime_policy import evaluate_runtime_policy
except ImportError:  # direct script execution
    from runtime_policy import evaluate_runtime_policy

OUTPUT_FILES = ("frontmatter.proposed.yml", "declaration.diff", "readme-review.md", "runtime-gaps.json", "interface-review.json")
SECRET = re.compile(r"(?i)(?:ghp_[a-z0-9]{20,}|sk-[a-z0-9_-]{12,}|akia[0-9a-z]{16}|xox[baprs]-[a-z0-9-]{10,}|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+)")


def redact(value: object) -> object:
    if isinstance(value, str):
        return SECRET.sub("[REDACTED]", value)
    if isinstance(value, list):
        return [redact(x) for x in value]
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()}
    return value


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _dirty(repo: Path) -> bool:
    if not (repo / ".git").exists():
        return False
    result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=False)
    return bool(result.stdout.strip())


def _frontmatter(path: Path) -> tuple[dict, str | None]:
    if not path.is_file():
        return {}, "declaration missing"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return {}, None
    end = text.find("\n---", 4)
    if end < 0:
        return {}, "unterminated YAML frontmatter"
    try:
        value = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        return {}, f"malformed YAML frontmatter: {exc.__class__.__name__}"
    return (value if isinstance(value, dict) else {}), None


def generate(inventory_path: Path, assignments_path: Path, interfaces_path: Path, waves_path: Path, workspace: Path, output: Path) -> dict:
    inventory = _json(inventory_path)
    interfaces = {x["name"]: x for x in _json(interfaces_path)["items"]}
    waves = _json(waves_path)["waves"]
    with assignments_path.open(encoding="utf-8", newline="") as handle:
        assignments = {x["name"]: x for x in csv.DictReader(handle)}
    assets = sorted(inventory["assets"], key=lambda x: x["name"])
    output.mkdir(parents=True, exist_ok=True)
    report = {"assets": [], "output_files": list(OUTPUT_FILES)}
    for asset in assets:
        name = asset["name"]
        row, iface = assignments.get(name, {}), interfaces.get(name, {})
        repo = workspace / name
        declaration = asset.get("declaration", {}).get("file") or ("AGENTS.md" if name.startswith("agent-") else "SKILL.md")
        current, error = _frontmatter(repo / declaration)
        dirty = _dirty(repo)
        target = output / name
        target.mkdir(parents=True, exist_ok=True)
        if set(p.name for p in target.iterdir()) - set(OUTPUT_FILES):
            raise ValueError(f"refusing output directory with undeclared files: {target}")
        proposal = {
            "catalog": {k: redact(row.get(k, "")) for k in ("project_type", "category", "subcategory", "primary_stage", "workflow_stages", "summary_zh", "summary_en")},
            "interface_candidate": redact(row.get("interface_candidate", iface.get("candidate_mode", "unknown"))),
            "workflow": redact(row.get("workflow_stages", "").split("|") if row else []),
            "preserved_trigger_description": redact(current.get("description", current.get("trigger", ""))),
            "proposal_only": True,
        }
        review = []
        if not repo.is_dir(): review.append("repository missing")
        if dirty: review.append("repository dirty; no patch proposed")
        if error: review.append(error + "; no patch proposed")
        patch = "# No patch: " + ("; ".join(review) if review else "review-only proposal; apply manually") + "\n"
        (target / "frontmatter.proposed.yml").write_text(yaml.safe_dump(redact(proposal), allow_unicode=True, sort_keys=True), encoding="utf-8")
        (target / "declaration.diff").write_text(patch, encoding="utf-8")
        (target / "readme-review.md").write_text("# Review\n\n" + ("\n".join(f"- {x}" for x in review) or "- Manual review required; source was not modified.") + "\n", encoding="utf-8")
        runtime = evaluate_runtime_policy(repo, row.get("project_type", "agent")) if repo.is_dir() else []
        (target / "runtime-gaps.json").write_text(json.dumps(redact(runtime), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        interface_review = {k: redact(iface.get(k)) for k in ("candidate_mode", "detected_formats", "detected_fields", "notes", "required_maintainer_decision")}
        interface_review["waves"] = sorted(wave for wave, names in waves.items() if name in names)
        (target / "interface-review.json").write_text(json.dumps(interface_review, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["assets"].append({"name": name, "review_items": review})
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    for name in ("inventory", "assignments", "interfaces", "waves", "workspace", "output"):
        p.add_argument(f"--{name}", required=True, type=Path)
    args = p.parse_args()
    print(json.dumps(generate(args.inventory, args.assignments, args.interfaces, args.waves, args.workspace, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
