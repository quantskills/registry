#!/usr/bin/env python3
"""Portable runtime coverage policy with local-link safety checks."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

RUNTIMES = ("Cursor", "Claude Code", "Codex", "Hermes", "OpenClaw")
LINK = re.compile(r"\[[^]]*\]\(([^)\s]+)")
FRONTMATTER = re.compile(r"\A(?:\ufeff)?---(?:\r?\n)(.*?)(?:\r?\n)---(?:\r?\n|\Z)", re.DOTALL)
WRAPPER_FIELDS = frozenset(("name", "description"))


def _files(root: Path, names: tuple[str, ...]) -> list[str]:
    return [name for name in names if (root / name).is_file()]


def _link_issues(root: Path, files: list[str]) -> list[str]:
    issues = []
    base = root.resolve()
    for name in files:
        for href in LINK.findall((root / name).read_text(encoding="utf-8", errors="replace")):
            if href.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = (root / href.split("#", 1)[0]).resolve()
            if target != base and base not in target.parents:
                issues.append(f"link escapes root: {name}")
            elif not target.exists():
                issues.append(f"link missing: {name}")
    return sorted(set(issues))


def _frontmatter(path: Path) -> tuple[dict[str, object] | None, str, str | None]:
    """Return a declaration's frontmatter, body, and a parse issue."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, "", f"cannot read {path.name}: {exc.__class__.__name__}"
    match = FRONTMATTER.match(text)
    if not match:
        return None, text, f"{path.name} has no YAML frontmatter"
    try:
        value = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, text[match.end():], f"{path.name} has malformed YAML frontmatter: {exc.__class__.__name__}"
    if not isinstance(value, dict):
        return None, text[match.end():], f"{path.name} frontmatter must be a mapping"
    return value, text[match.end():], None


def _skill_entry_issues(root: Path, path: str = "SKILL.md") -> list[str]:
    """Check the metadata needed by a native Agent Skills install entry."""
    value, _, error = _frontmatter(root / path)
    if error:
        return [error]
    assert value is not None
    issues = []
    for field in ("name", "description"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            issues.append(f"{path} frontmatter requires non-empty {field}")
    return issues


def _agent_wrapper_issues(root: Path) -> list[str]:
    """Validate the thin root SKILL.md wrapper used to install an Agent."""
    value, body, error = _frontmatter(root / "SKILL.md")
    if error:
        return [error]
    assert value is not None
    issues = []
    extra = sorted((str(key) for key in value if key not in WRAPPER_FIELDS), key=str)
    if extra:
        issues.append("SKILL.md wrapper frontmatter fields not allowed: " + ", ".join(extra))
    for field in WRAPPER_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            issues.append(f"SKILL.md wrapper frontmatter requires non-empty {field}")
    agents_target = (root / "AGENTS.md").resolve()
    local_agents_links = []
    for href in LINK.findall(body):
        if href.startswith(("http:", "https:", "mailto:", "#")):
            continue
        target = (root / href.split("#", 1)[0]).resolve()
        if target == agents_target:
            local_agents_links.append(href)
    if not local_agents_links:
        issues.append("SKILL.md wrapper must reference local AGENTS.md")
    return issues


def _detail(default: str, issues: list[str]) -> str:
    return "; ".join(issues) if issues else default


def evaluate_runtime_policy(root: Path, project_type: str) -> list[dict[str, object]]:
    canonical = "SKILL.md" if project_type == "skill" else "AGENTS.md"
    canonical_files = _files(root, (canonical,))
    cursor = []
    if (root / ".cursor/rules").is_dir():
        cursor = [p.relative_to(root).as_posix() for p in sorted((root / ".cursor/rules").glob("*.mdc"))]
    loaders = {
        "Cursor": cursor,
        "Claude Code": _files(root, ("CLAUDE.md",)),
        "Codex": _files(root, ("agents/openai.yaml",)),
        # HERMES.md and OPENCLAW.md are historical pseudo-loaders.  Native
        # discovery is based on the root SKILL.md install entry instead.
        "Hermes": [],
        "OpenClaw": [],
    }
    rows = []
    for runtime in RUNTIMES:
        evidence = sorted(set(canonical_files + loaders[runtime]))
        if project_type == "agent" and runtime in {"Hermes", "OpenClaw"} and (root / "SKILL.md").is_file():
            evidence.append("SKILL.md")
            evidence = sorted(set(evidence))
        issues = _link_issues(root, evidence)
        if not canonical_files:
            status, detail = "fail", f"missing canonical {canonical}"
        elif runtime == "Cursor":
            status, detail = ("pass", "Cursor loader present") if loaders[runtime] else ("needs-review", "runtime-specific loader not found")
        elif runtime == "Claude Code":
            if project_type == "skill" or loaders[runtime]: status, detail = "pass", "canonical or Claude loader present"
            else: status, detail = "needs-review", "agent requires CLAUDE.md"
        elif runtime == "Codex":
            status, detail = "pass", "canonical entrypoint present"
        elif runtime in {"Hermes", "OpenClaw"} and project_type == "skill":
            entry_issues = _skill_entry_issues(root)
            status, detail = ("fail", _detail("root SKILL.md install entry present", entry_issues)) if entry_issues else ("pass", "root SKILL.md install entry present")
        elif runtime in {"Hermes", "OpenClaw"}:
            wrapper = root / "SKILL.md"
            if not wrapper.is_file():
                status = "needs-review"
                detail = (
                    "agent requires root SKILL.md portable wrapper; agents/portable-loader.md is not an installable entry"
                    if (root / "agents/portable-loader.md").is_file()
                    else "agent requires root SKILL.md portable wrapper"
                )
            else:
                wrapper_issues = _agent_wrapper_issues(root)
                status, detail = ("fail", _detail("portable SKILL.md wrapper points to AGENTS.md", wrapper_issues)) if wrapper_issues else ("pass", "portable SKILL.md wrapper points to AGENTS.md")
        else:
            status, detail = ("pass", "native runtime entrypoint present") if loaders[runtime] else ("needs-review", "runtime-specific loader not found")
        if issues:
            status, detail = ("fail" if status == "pass" else status), "; ".join(issues)
        rows.append({"runtime": runtime, "status": status, "evidence": evidence, "detail": detail})
    return rows
