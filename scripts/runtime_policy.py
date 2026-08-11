#!/usr/bin/env python3
"""Portable runtime coverage policy with local-link safety checks."""
from __future__ import annotations

import re
from pathlib import Path

RUNTIMES = ("Cursor", "Claude Code", "Codex", "Hermes", "OpenClaw")
LINK = re.compile(r"\[[^]]*\]\(([^)\s]+)")


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


def evaluate_runtime_policy(root: Path, project_type: str) -> list[dict[str, object]]:
    canonical = "SKILL.md" if project_type == "skill" else "AGENTS.md"
    canonical_files = _files(root, (canonical,))
    cursor = _files(root, ("agents/cursor-rule.mdc",))
    if (root / ".cursor/rules").is_dir():
        cursor += [p.relative_to(root).as_posix() for p in sorted((root / ".cursor/rules").glob("*.mdc"))]
    loaders = {
        "Cursor": cursor,
        "Claude Code": _files(root, ("CLAUDE.md",)),
        "Codex": _files(root, ("agents/openai",)),
        "Hermes": _files(root, ("agents/portable-loader.md", "HERMES.md")),
        "OpenClaw": _files(root, ("agents/portable-loader.md", "OPENCLAW.md")),
    }
    rows = []
    for runtime in RUNTIMES:
        evidence = sorted(set(canonical_files + loaders[runtime]))
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
        else:
            status, detail = ("pass", "portable or native loader present") if loaders[runtime] else ("needs-review", "runtime-specific loader not found")
        if issues:
            status, detail = ("fail" if status == "pass" else status), "; ".join(issues)
        rows.append({"runtime": runtime, "status": status, "evidence": evidence, "detail": detail})
    return rows
