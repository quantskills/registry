#!/usr/bin/env python3
"""Generate contained, review-only migration proposals; never alter assets."""
from __future__ import annotations

import argparse
import copy
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
ROOT_FIELDS = frozenset(("name", "description", "license", "allowed-tools", "user-invocable", "disable-model-invocation", "supported-runtimes", "compatibility", "version", "author", "metadata", "quantSkills"))
SECRET = re.compile(
    r"(?i)(?:"
    r"ghp_[a-z0-9]{20,}"
    r"|(?<![a-z0-9_-])sk_(?:live|test)_[a-z0-9]{10,}"
    r"|(?<![a-z0-9_-])sk-[a-z0-9_-]{12,}"
    r"|akia[0-9a-z]{16}"
    r"|xox[baprs]-[a-z0-9-]{10,}"
    r"|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+"
    r")"
)


def redact(value: object) -> object:
    if isinstance(value, str): return SECRET.sub("[REDACTED]", value)
    if isinstance(value, list): return [redact(x) for x in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"name", "repository"} and isinstance(item, str):
                result[key_text] = item
            else:
                result[key_text] = redact(item)
        return result
    return value


def _json(path: Path) -> object: return json.loads(path.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> str:
    if not (repo / ".git").exists(): return ""
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _dirty(repo: Path) -> bool: return bool(_git(repo, "status", "--porcelain"))


def _frontmatter(path: Path) -> tuple[dict, str, str, str | None]:
    if not path.is_file(): return {}, "", "", "declaration missing"
    text = path.read_bytes().decode("utf-8", errors="surrogateescape")
    content = text[1:] if text.startswith("\ufeff") else text
    opening = "\r\n" if content.startswith("---\r\n") else "\n" if content.startswith("---\n") else ""
    if not opening: return {}, "", text, "declaration has no YAML frontmatter"
    start = len("---") + len(opening)
    match = re.search(r"(?:\r\n|\n)---(?=(?:\r\n|\n|$))", content[start:])
    if not match: return {}, "", text, "unterminated YAML frontmatter"
    end = start + match.start()
    yaml_text, body = content[start:end], content[start + match.end():]
    try: value = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc: return {}, "", body, f"malformed YAML frontmatter: {exc.__class__.__name__}"
    if not isinstance(value, dict): return {}, "", body, "YAML frontmatter must be a mapping"
    return value, text, body, None


def _line_ending(text: str) -> str:
    position = text.find("\n")
    return "\r\n" if position > 0 and text[position - 1] == "\r" else "\n"


def _declaration_text(proposed_yaml: str, old: str, body: str) -> str:
    newline = _line_ending(old)
    bom = "\ufeff" if old.startswith("\ufeff") else ""
    yaml_text = proposed_yaml.replace("\n", newline)
    return f"{bom}---{newline}{yaml_text}---" + body


def _unified_diff(old: str, proposed: str, declaration: str) -> str:
    newline = _line_ending(old)
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{declaration}",
            tofile=f"b/{declaration}",
            lineterm=newline,
        )
    )


def _proposal(current: dict, row: dict, iface: dict, name: str) -> dict:
    mode = row.get("interface_candidate") or iface.get("candidate_mode", "unknown")
    interface = {"mode": mode}
    if mode == "not-applicable":
        reason = iface.get("notes")
        interface["reason"] = reason if reason in {"natural-language-only", "report-only", "orchestration-only"} else "natural-language-only"
    original = current.get("description")
    if isinstance(original, str) and len(original) >= 60:
        description = original
    else:
        summary = str(row["summary_en"]).strip()
        if isinstance(original, str):
            separator = "" if not original or original.endswith((" ", "\t")) else " "
            description = original + separator + summary
        else:
            description = summary
        if len(description) < 60:
            description += " This declaration records catalog metadata and interface review status."
    proposed = copy.deepcopy(current)
    proposed["name"] = name
    proposed["description"] = description
    proposed["license"] = "GPL-3.0-only"
    qs = proposed.get("quantSkills") if isinstance(proposed.get("quantSkills"), dict) else {}
    qs.update({
        "schema_version": "2.1.0", "organization": "quantskills", "organization_url": "https://github.com/quantskills",
        "repository": name, "repository_url": f"https://github.com/quantskills/{name}", "project_type": row["project_type"],
        "license": "GPL-3.0-only", "maintainer": qs.get("maintainer", "abgyjaguo"),
        "catalog": {k: row[k] for k in ("category", "subcategory")},
        "workflow": {"primary_stage": row["primary_stage"], "workflow_stages": row["workflow_stages"].split("|")},
        "summary_zh": row["summary_zh"], "summary_en": row["summary_en"],
        "platforms": ["cursor", "claude-code", "codex", "hermes", "openclaw"],
        "status": "draft", "validation_level": "listed", "maintainer_type": "community", "interface": interface,
    })
    proposed["quantSkills"] = qs
    proposed = redact(proposed)
    proposed["name"] = name
    proposed["quantSkills"]["repository"] = name
    proposed["quantSkills"]["repository_url"] = f"https://github.com/quantskills/{name}"
    return proposed


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
        if repo.is_dir() and not (repo / ".git").exists(): review.append("repository has no .git metadata; no patch proposed")
        if _dirty(repo): review.append("repository dirty; no patch proposed")
        if error: review.append(error + "; no patch proposed")
        extra = sorted((str(key) for key in current if key not in ROOT_FIELDS), key=str)
        if extra: review.append("unsupported frontmatter root fields (manual migration required): " + ", ".join(f"$.{key}" for key in extra) + "; no patch proposed")
        if isinstance(current.get("metadata"), dict): review.append("legacy metadata has no approved lossless 2.1 mapping; no patch proposed")
        for field in ("maintainer", "license"):
            value = current.get(field)
            if value is not None and value != ("abgyjaguo" if field == "maintainer" else "GPL-3.0-only"):
                review.append(f"existing {field} differs from approved value; no patch proposed")
        current_qs = current.get("quantSkills") if isinstance(current.get("quantSkills"), dict) else {}
        if current_qs.get("maintainer") not in (None, "abgyjaguo"):
            review.append("existing quantSkills.maintainer differs from approved value; no patch proposed")
        if current_qs.get("license") not in (None, "GPL-3.0-only"):
            review.append("existing quantSkills.license differs from approved value; no patch proposed")
        if old and SECRET.search(old): review.append("potential secret detected in declaration; no patch proposed")
        if not row: review.append("assignment missing; no patch proposed")
        elif row.get("review_status") != "approved": review.append("assignment not approved; no patch proposed")
        elif (row.get("interface_candidate") or (iface or {}).get("candidate_mode")) in {"structured", "hybrid"}:
            review.append("structured/hybrid candidate lacks approved Profile endpoints; no patch proposed")
        elif (row.get("interface_candidate") or (iface or {}).get("candidate_mode")) not in {"natural-language", "not-applicable"}:
            review.append("interface candidate is not declaration-valid; no patch proposed")
        if not iface: review.append("interface audit missing; no patch proposed")
        expected = asset.get("head_sha")
        actual = _git(repo, "rev-parse", "--verify", "HEAD")
        if not expected: review.append("inventory head_sha missing; no patch proposed")
        if not actual: review.append("repository HEAD cannot be resolved; no patch proposed")
        elif expected != actual: review.append("frozen HEAD mismatch; no patch proposed")
        target = _target(output, name)
        clean = not review
        proposed = _proposal(current, row, iface, name) if clean else {}
        proposed_yaml = yaml.safe_dump(proposed, allow_unicode=True, sort_keys=False)
        proposed_text = _declaration_text(proposed_yaml, old, body) if clean else "# No proposal generated\n"
        diff = _unified_diff(old, proposed_text, declaration) if clean else "# No patch: " + "; ".join(review) + "\n"
        newline = _line_ending(old) if old else "\n"
        proposed_bytes = proposed_yaml.replace("\n", newline).encode("utf-8", "surrogateescape")
        if old.startswith("\ufeff"): proposed_bytes = b"\xef\xbb\xbf" + proposed_bytes
        target.joinpath("frontmatter.proposed.yml").write_bytes(proposed_bytes)
        target.joinpath("declaration.diff").write_bytes(diff.encode("utf-8", "surrogateescape"))
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
