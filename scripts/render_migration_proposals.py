#!/usr/bin/env python3
"""Generate contained, review-only migration proposals; never alter assets."""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import subprocess
from pathlib import Path

import yaml

try:
    from .runtime_policy import evaluate_runtime_policy
except ImportError:
    from runtime_policy import evaluate_runtime_policy

OUTPUT_FILES = ("frontmatter.proposed.yml", "declaration.diff", "readme-review.md", "runtime-gaps.json", "interface-review.json")
NAME = re.compile(r"^(?:skill|agent)-[a-z0-9]+(?:-[a-z0-9]+)*$")
SECRET = re.compile(r"(?i)(?:ghp_[a-z0-9]{20,}|sk-[a-z0-9_-]{12,}|akia[0-9a-z]{16}|xox[baprs]-[a-z0-9-]{10,}|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+)")


def redact(value: object) -> object:
    if isinstance(value, str): return SECRET.sub("[REDACTED]", value)
    if isinstance(value, list): return [redact(x) for x in value]
    if isinstance(value, dict): return {str(k): redact(v) for k, v in value.items()}
    return value


def _json(path: Path) -> object: return json.loads(path.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> str:
    if not (repo / ".git").exists(): return ""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout.strip()


def _dirty(repo: Path) -> bool: return bool(_git(repo, "status", "--porcelain"))


def _frontmatter(path: Path) -> tuple[dict, str, str, str | None]:
    if not path.is_file(): return {}, "", "", "declaration missing"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"): return {}, "", text, "declaration has no YAML frontmatter"
    end = text.find("\n---", 4)
    if end < 0: return {}, "", text, "unterminated YAML frontmatter"
    yaml_text, body = text[4:end], text[end + 4:]
    try: value = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc: return {}, "", body, f"malformed YAML frontmatter: {exc.__class__.__name__}"
    if not isinstance(value, dict): return {}, "", body, "YAML frontmatter must be a mapping"
    return value, text, body, None


def _proposal(current: dict, row: dict, iface: dict, name: str) -> dict:
    mode = row.get("interface_candidate") or iface.get("candidate_mode", "unknown")
    interface = {"mode": mode}
    if mode == "not-applicable": interface["reason"] = iface.get("notes", "maintainer review required")
    elif mode == "natural-language": interface["reason"] = "natural-language interface; maintainer review required"
    else: interface["profile_review_required"] = True
    result = dict(current)
    result["quantSkills"] = {
        "schema_version": "2.0.0", "organization": "quantskills", "organization_url": "https://github.com/quantskills",
        "repository": name, "repository_url": f"https://github.com/quantskills/{name}", "project_type": row["project_type"],
        "license": "GPL-3.0-only", "maintainer": "abgyjaguo",
        "catalog": {k: row[k] for k in ("category", "subcategory", "primary_stage", "summary_zh", "summary_en")},
        "workflow": row["workflow_stages"].split("|"),
        "platforms": ["Cursor", "Claude Code", "Codex", "Hermes", "OpenClaw"],
        "status": "proposal", "validation": "maintainer-review-required", "maintainer_type": "human", "interface": interface,
    }
    return redact(result)


def _target(output: Path, name: str) -> Path:
    if not NAME.fullmatch(name): raise ValueError(f"invalid asset name: {name}")
    base = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    target = output / name
    if target.exists() and target.is_symlink(): raise ValueError(f"symlink output directory: {target}")
    target.mkdir(exist_ok=True)
    resolved = target.resolve()
    if resolved != base and base not in resolved.parents: raise ValueError(f"output escapes caller directory: {target}")
    entries = list(target.iterdir())
    if any(entry.is_symlink() for entry in entries): raise ValueError(f"symlink output entry: {target}")
    if {x.name for x in entries} - set(OUTPUT_FILES): raise ValueError(f"refusing output directory with undeclared files: {target}")
    return target


def generate(inventory_path: Path, assignments_path: Path, interfaces_path: Path, waves_path: Path, workspace: Path, output: Path) -> dict:
    assets = _json(inventory_path)["assets"]
    with assignments_path.open(encoding="utf-8", newline="") as handle: assignments = {x["name"]: x for x in csv.DictReader(handle)}
    interfaces = {x["name"]: x for x in _json(interfaces_path)["items"]}; waves = _json(waves_path)["waves"]
    names = [x.get("name", "") for x in assets]
    if len(set(names)) != len(names) or any(not NAME.fullmatch(x) for x in names): raise ValueError("invalid asset name")
    if set(assignments) != set(names) or set(interfaces) != set(names):
        raise ValueError("inventory, assignment, and interface names must join exactly")
    report = {"assets": [], "output_files": list(OUTPUT_FILES)}
    for asset in sorted(assets, key=lambda x: x["name"]):
        name, repo, row, iface = asset["name"], workspace / asset["name"], assignments.get(asset["name"]), interfaces.get(asset["name"])
        declaration = asset.get("declaration", {}).get("file") or ("AGENTS.md" if name.startswith("agent-") else "SKILL.md")
        current, old, body, error = _frontmatter(repo / declaration); review = []
        if not repo.is_dir(): review.append("repository missing")
        if _dirty(repo): review.append("repository dirty; no patch proposed")
        if error: review.append(error + "; no patch proposed")
        if not row: review.append("assignment missing; no patch proposed")
        elif row.get("review_status") != "approved": review.append("assignment not approved; no patch proposed")
        if not iface: review.append("interface audit missing; no patch proposed")
        expected = asset.get("head_sha")
        actual = _git(repo, "rev-parse", "HEAD")
        if expected and actual and expected != actual: review.append("frozen HEAD mismatch; no patch proposed")
        target = _target(output, name)
        clean = not review
        proposed = _proposal(current, row, iface, name) if clean else {}
        proposed_yaml = yaml.safe_dump(proposed, allow_unicode=True, sort_keys=False)
        proposed_text = "---\n" + proposed_yaml + "---" + body if clean else "# No proposal generated\n"
        diff = "".join(difflib.unified_diff(redact(old).splitlines(True), redact(proposed_text).splitlines(True), fromfile=declaration, tofile=declaration)) if clean else "# No patch: " + "; ".join(review) + "\n"
        target.joinpath("frontmatter.proposed.yml").write_text(proposed_yaml, encoding="utf-8")
        target.joinpath("declaration.diff").write_text(diff, encoding="utf-8")
        target.joinpath("readme-review.md").write_text("# Review\n\n" + ("\n".join(f"- {redact(x)}" for x in review) or "- Actionable proposal generated; apply manually.") + "\n", encoding="utf-8")
        runtime = evaluate_runtime_policy(repo, row["project_type"] if row else ("agent" if name.startswith("agent-") else "skill")) if repo.is_dir() else []
        target.joinpath("runtime-gaps.json").write_text(json.dumps(redact(runtime), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ir = {k: iface.get(k) for k in ("candidate_mode", "detected_formats", "detected_fields", "notes", "required_maintainer_decision")} if iface else {}
        ir["waves"] = sorted(w for w, members in waves.items() if name in members)
        target.joinpath("interface-review.json").write_text(json.dumps(redact(ir), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report["assets"].append({"name": name, "review_items": review})
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    for key in ("inventory", "assignments", "interfaces", "waves", "workspace", "output"): p.add_argument(f"--{key}", required=True, type=Path)
    a = p.parse_args(); print(json.dumps(generate(a.inventory, a.assignments, a.interfaces, a.waves, a.workspace, a.output), ensure_ascii=False, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
