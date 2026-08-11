#!/usr/bin/env python3
"""Write one fail-closed, local migration evidence record per asset."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from .catalog_contract import load_taxonomy, validate_asset_semantics, validate_frontmatter_schema
    from .render_migration_proposals import NAME, _frontmatter
    from .runtime_policy import evaluate_runtime_policy
except ImportError:
    from catalog_contract import load_taxonomy, validate_asset_semantics, validate_frontmatter_schema
    from render_migration_proposals import NAME, _frontmatter
    from runtime_policy import evaluate_runtime_policy


ROOT = Path(__file__).resolve().parent.parent
SHA = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_SUBJECTS = (
    "chore(catalog): adopt declaration contract v2",
    "feat(contract): expose versioned skill interface",
    "test(contract): support frozen core-chain fixture",
    "feat(template): adopt catalog contract v2",
    "feat(template): adopt agent catalog contract v2",
    "fix(template): validate declaration 2.1 bridge",
    "fix(template): normalize compatibility target path",
)
ALLOWED_AUTHORS = {("abgyjaguo", "213890245+abgyjaguo@users.noreply.github.com")}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _inventory(path: Path, name: str) -> tuple[dict, dict, str]:
    try:
        raw = path.read_bytes(); value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid inventory: {exc.__class__.__name__}") from exc
    assets = value.get("assets") if isinstance(value, dict) else None
    if not NAME.fullmatch(name) or not isinstance(assets, list):
        raise ValueError("invalid inventory or asset name")
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        raise ValueError("asset name must occur exactly once in inventory")
    return value, matches[0], "sha256:" + hashlib.sha256(raw).hexdigest()


def _contained_output(output: Path, name: str, create: bool = True) -> Path:
    if not NAME.fullmatch(name):
        raise ValueError("invalid asset name")
    if create: output.mkdir(parents=True, exist_ok=True)
    if not output.is_dir(): raise ValueError("progress directory missing")
    if output.is_symlink():
        raise ValueError("progress directory is a symlink")
    base = output.resolve(); target = output / f"{name}.json"
    if target.exists() and target.is_symlink():
        raise ValueError("progress record is a symlink")
    resolved = target.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("progress record escapes output directory")
    return target


def _migration_commit(repo: Path, frozen: str, current: str) -> dict:
    history = _git(repo, "log", "--format=%H%x00%an%x00%ae%x00%s", f"{frozen}..{current}")
    for line in history.splitlines():
        values = line.split("\x00")
        if len(values) == 4 and (values[1], values[2]) in ALLOWED_AUTHORS and values[3] in ALLOWED_SUBJECTS:
            return {"sha": values[0], "author": {"name": values[1], "email": values[2]}, "subject": values[3]}
    raise ValueError("no allowed migration commit after frozen HEAD")


def evidence(inventory: Path, name: str, repo: Path) -> dict:
    _, asset, inventory_hash = _inventory(inventory, name)
    if not repo.is_dir() or repo.is_symlink() or not (repo / ".git").exists():
        raise ValueError("repository git metadata unavailable")
    frozen = asset.get("head_sha"); current = _git(repo, "rev-parse", "--verify", "HEAD")
    if not isinstance(frozen, str) or not SHA.fullmatch(frozen) or not SHA.fullmatch(current):
        raise ValueError("frozen or current HEAD unavailable")
    result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", frozen, current], check=False)
    if result.returncode: raise ValueError("frozen HEAD is not an ancestor of current HEAD")
    if _git(repo, "status", "--porcelain"):
        raise ValueError("repository dirty")
    branch = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch or branch.startswith("remotes/"):
        raise ValueError("current branch must be local")
    declaration = asset.get("declaration", {}).get("file") if isinstance(asset.get("declaration"), dict) else None
    declaration = declaration or ("AGENTS.md" if name.startswith("agent-") else "SKILL.md")
    frontmatter, _, _, malformed = _frontmatter(repo / declaration)
    if malformed:
        raise ValueError(malformed)
    schema = validate_frontmatter_schema(frontmatter, ROOT / "schema" / "frontmatter.schema.json")
    semantic = validate_asset_semantics(frontmatter, name, declaration, load_taxonomy(ROOT))
    if schema or semantic:
        raise ValueError("declaration contract failed")
    project_type = "agent" if name.startswith("agent-") else "skill"
    runtime = evaluate_runtime_policy(repo, project_type)
    if len(runtime) != 5 or any(row["status"] != "pass" for row in runtime):
        raise ValueError("runtime policy failed")
    migration = _migration_commit(repo, frozen, current)
    return {
        "record_version": "1.0.0", "name": name, "inventory_sha256": inventory_hash,
        "before_sha": frozen, "after_sha": current,
        "declaration": {"file": declaration, "schema": schema, "semantic": semantic},
        "contract": {"schema_version": frontmatter["quantSkills"]["schema_version"]},
        "runtime": runtime, "migration_commit": migration, "warnings": [],
    }


def record(inventory: Path, name: str, repo: Path, output: Path) -> Path:
    target = _contained_output(output, name)
    value = evidence(inventory, name, repo)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    for key in ("inventory", "repo", "output"): parser.add_argument(f"--{key}", required=True, type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args(); print(record(args.inventory, args.name, args.repo, args.output)); return 0


if __name__ == "__main__": raise SystemExit(main())
