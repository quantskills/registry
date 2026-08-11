#!/usr/bin/env python3
"""Portable-runtime coverage policy used by the migration proposal tools."""
from __future__ import annotations

from pathlib import Path

RUNTIMES = ("Cursor", "Claude Code", "Codex", "Hermes", "OpenClaw")


def _exists(root: Path, *names: str) -> list[str]:
    return [name for name in names if (root / name).is_file()]


def evaluate_runtime_policy(root: Path, project_type: str) -> list[dict[str, object]]:
    """Return one deterministic, evidence-bearing row per supported runtime.

    This deliberately evaluates files only; it does not create adapters or
    infer that a runtime can consume a declaration it cannot locate.
    """
    canonical = "SKILL.md" if project_type == "skill" else "AGENTS.md"
    present = _exists(root, canonical)
    rows: list[dict[str, object]] = []
    rules = {
        "Cursor": ("agents/cursor-rule.mdc", ".cursor/rules"),
        "Claude Code": (canonical, "CLAUDE.md"),
        "Codex": (canonical, "agents/openai"),
        "Hermes": ("agents/portable-loader.md", "HERMES.md"),
        "OpenClaw": ("agents/portable-loader.md", "OPENCLAW.md"),
    }
    for runtime in RUNTIMES:
        candidates = rules[runtime]
        evidence = list(present)
        if runtime == "Cursor":
            evidence += _exists(root, candidates[0])
            rule_dir = root / candidates[1]
            if rule_dir.is_dir():
                evidence += [p.relative_to(root).as_posix() for p in sorted(rule_dir.glob("*.mdc"))]
        else:
            evidence += _exists(root, *candidates[1:])
        # Claude and Codex accept the canonical entrypoint.  The other
        # runtimes require their explicitly portable/loader adapters.
        if runtime in {"Claude Code", "Codex"} and canonical in evidence:
            status, detail = "pass", "canonical entrypoint present"
        elif runtime == "Cursor" and any(x.endswith(".mdc") for x in evidence):
            status, detail = "pass", "Cursor loader present"
        elif runtime == "Hermes" and any(x in {"agents/portable-loader.md", "HERMES.md"} for x in evidence):
            status, detail = "pass", "portable or native loader present"
        elif runtime == "OpenClaw" and any(x in {"agents/portable-loader.md", "OPENCLAW.md"} for x in evidence):
            status, detail = "pass", "portable or native loader present"
        elif not canonical in evidence:
            status, detail = "fail", f"missing canonical {canonical}"
        else:
            status, detail = "needs-review", "runtime-specific loader not found"
        rows.append({"runtime": runtime, "status": status, "evidence": sorted(evidence), "detail": detail})
    return rows
