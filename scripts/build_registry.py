#!/usr/bin/env python3
"""Build deterministic public registry artifacts from one catalog snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import datetime as dt
from pathlib import Path

import requests

from catalog_contract import canonical_json, load_taxonomy, validate_asset_semantics, validate_frontmatter_schema
from validate_skill import declaration_info, parse_frontmatter, validate
from verify_catalog_artifacts import verify
from catalog_projection import public_registry_projection

ROOT = Path(__file__).resolve().parent.parent
ORG = os.environ.get("QS_ORG", "quantskills")
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"} if TOKEN else {}
RESOURCE_NAMES = (".github", "join", "quantskills", "registry")
INVENTORY_PATH = ROOT / "catalog-inventory.v1.json"


def gh(method: str, url: str, **kwargs):
    response = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json() if response.text else {}


def list_asset_repos() -> list[dict]:
    repos, page = [], 1
    while batch := gh("GET", f"{API}/orgs/{ORG}/repos", params={"per_page": 100, "page": page}):
        repos.extend(repo for repo in batch if (repo["name"].startswith(("skill-", "agent-")) or repo["name"] in RESOURCE_NAMES) and not repo.get("archived") and not repo.get("private"))
        page += 1
    return repos


def head_sha(repo: dict) -> str:
    return gh("GET", f"{API}/repos/{ORG}/{repo['name']}/commits/{repo['default_branch']}")["sha"]


def shallow_clone(name: str, destination: Path) -> str:
    import subprocess
    subprocess.run(["git", "clone", "--depth", "1", "--quiet", f"https://github.com/{ORG}/{name}.git", str(destination)], check=True)
    return subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def load_inventory(path: Path = INVENTORY_PATH) -> dict:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema_version") != "1.0.0" or not isinstance(inventory.get("assets"), list) or sorted(inventory.get("resources", [])) != sorted(RESOURCE_NAMES):
        raise ValueError("invalid catalog inventory")
    return inventory


def _entry_from_frontmatter(name: str, frontmatter: dict, commit_sha: str = "", contract_mode: str = "enforce", validation_date: str = "") -> dict:
    qs = frontmatter.get("quantSkills") or {}
    catalog, workflow, interface = qs.get("catalog") or {}, qs.get("workflow") or {}, qs.get("interface") or {}
    project_type = qs.get("project_type") or ("agent" if name.startswith("agent-") else "skill")
    issues = validate_frontmatter_schema(frontmatter, ROOT / "schema" / "frontmatter.schema.json")
    issues += validate_asset_semantics(frontmatter, name, "AGENTS.md" if project_type == "agent" else "SKILL.md", load_taxonomy(ROOT))
    missing_v2 = not isinstance(catalog.get("category"), str) or not isinstance(catalog.get("subcategory"), str) or not isinstance(workflow.get("primary_stage"), str) or not isinstance(workflow.get("workflow_stages"), list) or not isinstance(interface, dict) or not interface.get("mode") or bool(issues)
    if missing_v2:
        if contract_mode != "audit":
            raise ValueError(f"invalid declaration for {name}: contract validation failed")
        if not isinstance(catalog.get("category"), str) or not isinstance(catalog.get("subcategory"), str):
            catalog = {"category": "10", "subcategory": f"10.{name}"} if name in {"skill-template", "agent-template"} else {"category": "unknown", "subcategory": "unknown"}
        if not isinstance(workflow.get("primary_stage"), str) or not isinstance(workflow.get("workflow_stages"), list):
            workflow = {"primary_stage": "orchestration", "workflow_stages": ["orchestration"]} if name in {"skill-template", "agent-template"} else {"primary_stage": "unknown", "workflow_stages": []}
        if not isinstance(interface, dict) or not interface.get("mode"):
            interface = {"mode": "unknown", "reason": "pending-v2-migration"}
    entry = {
        "name": name, "url": f"https://github.com/{ORG}/{name}", "description": frontmatter.get("description", ""),
        "project_type": project_type, "declaration_file": "AGENTS.md" if project_type == "agent" else "SKILL.md",
        "catalog": catalog, "workflow": workflow, "interface": interface,
        "category": catalog["category"], "subcategory": catalog["subcategory"], "stage": workflow["primary_stage"],
        "tags": qs.get("tags", []), "platforms": qs.get("platforms", []), "status": qs.get("status", "active"),
        "requires": qs.get("requires", []), "summary_zh": qs.get("summary_zh", "unknown") if qs.get("summary_zh") else "unknown", "summary_en": qs.get("summary_en", "unknown") if qs.get("summary_en") else "unknown",
        "license": qs.get("license", "GPL-3.0-only"), "validation_level": qs.get("validation_level", "listed"),
        "maintainer_type": qs.get("maintainer_type", "community"), "last_validated": validation_date, "commit_sha": commit_sha,
        **({"migration_state": "pending-v2", "migration_issues": [{"code": issue["check"], "path": issue["path"]} for issue in issues] or [{"code": "missing-v2", "path": "$.quantSkills"}]} if missing_v2 else {}),
    }
    if missing_v2:
        _normalize_audit_entry(entry, name, issues)
    return entry


def _normalize_audit_entry(entry: dict, name: str, issues: list[dict]) -> None:
    """Keep only independently schema-valid public facts in an audit migration row."""
    paths = {issue["path"] for issue in issues}
    qs_path = "$.quantSkills"
    entry["project_type"] = entry["project_type"] if entry["project_type"] in {"skill", "agent"} and f"{qs_path}.project_type" not in paths else ("agent" if name.startswith("agent-") else "skill")
    entry["declaration_file"] = "AGENTS.md" if entry["project_type"] == "agent" else "SKILL.md"
    entry["description"] = entry["description"] if isinstance(entry["description"], str) else ""
    entry["status"] = entry["status"] if entry["status"] in {"draft", "active", "stable", "deprecated"} and f"{qs_path}.status" not in paths else "draft"
    entry["validation_level"] = entry["validation_level"] if entry["validation_level"] in {"listed", "runnable", "verified"} and f"{qs_path}.validation_level" not in paths else "listed"
    entry["maintainer_type"] = entry["maintainer_type"] if entry["maintainer_type"] in {"official", "community"} and f"{qs_path}.maintainer_type" not in paths else "community"
    entry["license"] = entry["license"] if isinstance(entry["license"], str) and entry["license"] and f"{qs_path}.license" not in paths else "GPL-3.0-only"
    entry["tags"] = entry["tags"] if isinstance(entry["tags"], list) and all(isinstance(item, str) for item in entry["tags"]) else []
    entry["requires"] = entry["requires"] if isinstance(entry["requires"], list) and all(isinstance(item, str) for item in entry["requires"]) else []
    entry["platforms"] = entry["platforms"] if isinstance(entry["platforms"], list) and all(isinstance(item, str) for item in entry["platforms"]) else []
    entry["summary_zh"] = entry["summary_zh"] if isinstance(entry["summary_zh"], str) and f"{qs_path}.summary_zh" not in paths else "unknown"
    entry["summary_en"] = entry["summary_en"] if isinstance(entry["summary_en"], str) and f"{qs_path}.summary_en" not in paths else "unknown"
    if any(path.startswith(f"{qs_path}.catalog") for path in paths) and name not in {"skill-template", "agent-template"}:
        entry["catalog"] = {"category": "unknown", "subcategory": "unknown"}
    if any(path.startswith(f"{qs_path}.workflow") for path in paths) and name not in {"skill-template", "agent-template"}:
        entry["workflow"] = {"primary_stage": "unknown", "workflow_stages": []}
    if any(path.startswith(f"{qs_path}.interface") for path in paths):
        entry["interface"] = {"mode": "unknown", "reason": "pending-v2-migration"}
    entry["category"], entry["subcategory"] = entry["catalog"]["category"], entry["catalog"]["subcategory"]
    entry["stage"] = entry["workflow"]["primary_stage"]


def collect_entries(repos: list[dict], previous: dict, contract_mode: str, inventory: dict | None = None, validation_date: str = "") -> tuple[list[dict], list[dict]]:
    """Collect entries without writing artifacts; fixtures inject ``frontmatter`` directly."""
    if contract_mode not in {"audit", "enforce"}:
        raise ValueError("contract_mode must be 'audit' or 'enforce'")
    names = [repo.get("name") for repo in repos]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise ValueError("duplicate or empty asset name")
    inventory = inventory or load_inventory()
    expected = set(inventory["assets"]) | set(inventory["resources"])
    if set(names) != expected:
        raise ValueError("catalog inventory mismatch")
    resources_by_name = {repo["name"]: {"name": repo["name"], "url": repo.get("html_url") or repo.get("url") or f"https://github.com/{ORG}/{repo['name']}"} for repo in repos if repo["name"] in RESOURCE_NAMES}
    entries = []
    for repo in (repo for repo in repos if repo["name"] not in RESOURCE_NAMES):
        name = repo["name"]
        if "frontmatter" in repo:
            entries.append(_entry_from_frontmatter(name, repo["frontmatter"], repo.get("commit_sha", ""), contract_mode, validation_date))
            continue
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / name
            clone_sha = shallow_clone(name, directory)
            kind, declaration = declaration_info(directory)
            frontmatter = parse_frontmatter(directory / declaration) if declaration else None
            report = validate(directory, set(names), contract_mode)
            if report.health == "quarantined" or not frontmatter:
                raise ValueError(f"invalid declaration for {name}")
            entry = _entry_from_frontmatter(name, frontmatter, clone_sha, contract_mode, validation_date)
            entry["health"] = report.health
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry["name"]), [resources_by_name[name] for name in RESOURCE_NAMES]


def _stable_snapshot(snapshot: dict) -> dict:
    if isinstance(snapshot, dict):
        return {key: _stable_snapshot(value) for key, value in snapshot.items() if key not in {"snapshot_id", "generated_at", "validated_at", "scan_time", "last_validated"}}
    if isinstance(snapshot, list):
        return [_stable_snapshot(value) for value in snapshot]
    return snapshot


def build_snapshot(entries: list[dict], resources: list[dict], taxonomy: dict, profiles: dict, adapters: dict) -> dict:
    names = [entry.get("name") for entry in entries]
    if not entries or len(names) != len(set(names)) or any(not name for name in names):
        raise ValueError("assets must be nonempty and unique")
    resource_names = sorted(resource.get("name") for resource in resources)
    if resource_names != sorted(RESOURCE_NAMES):
        raise ValueError("closed organization resource inventory is incomplete")
    snapshot = {
        "schema_version": "1.0.0", "taxonomy_version": taxonomy.get("schema_version"),
        "taxonomy": taxonomy, "assets": sorted(entries, key=lambda entry: entry["name"]),
        "resources": sorted(resources, key=lambda resource: resource["name"]),
        "profiles": {"version": profiles.get("version", "1.0.0"), "items": sorted(profiles.get("items", []), key=canonical_json)},
        "adapters": {"version": adapters.get("version", "1.0.0"), "items": sorted(adapters.get("items", []), key=canonical_json)},
        "compatibility_edges": [],
    }
    snapshot["snapshot_id"] = "sha256:" + hashlib.sha256(canonical_json(_stable_snapshot(snapshot))).hexdigest()
    return snapshot


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _replace_marked(text: str, body: str) -> str:
    start, end = "<!-- registry-snapshot:start -->", "<!-- registry-snapshot:end -->"
    if start not in text or end not in text:
        raise ValueError("missing registry snapshot markers")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return f"{before}{start}\n{body}\n{end}{after}"


def render_artifacts(snapshot: dict) -> dict[Path, bytes]:
    projection = public_registry_projection(snapshot)
    index = "# quantskills Asset Directory\n\n" + "\n".join(f"- [{entry['name']}]({entry['url']}): {entry['summary_en']}" for entry in projection) + "\n"
    llms = "# quantskills\n\n" + "\n".join(f"- [{entry['name']}]({entry['url']}): {entry['summary_en']}" for entry in projection) + "\n"
    marketplace = {"name": "quantskills", "owner": {"name": "quantskills", "url": f"https://github.com/{ORG}"}, "plugins": [{"name": entry["name"].removeprefix("skill-").removeprefix("agent-"), "source": {"source": "github", "repo": f"{ORG}/{entry['name']}"}, "description": entry["summary_en"], "type": entry["project_type"], "category": entry["category"]} for entry in projection]}
    assets = len(projection)
    outputs = {ROOT / "catalog.snapshot.json": _json_bytes(snapshot), ROOT / "registry.json": _json_bytes(projection), ROOT / "INDEX.md": index.encode(), ROOT / "llms.txt": llms.encode(), ROOT / ".claude-plugin" / "marketplace.json": _json_bytes(marketplace)}
    for readme in (ROOT / "README.md", ROOT / "README.en.md"):
        text = _replace_marked(readme.read_text(encoding="utf-8"), f"Catalog snapshot: `{snapshot['snapshot_id']}`; public assets: {assets}.")
        text = re.sub(r"public_assets-[^\"/]+-blue", f"public_assets-{assets}-blue", text, count=1)
        outputs[readme] = text.encode("utf-8")
    return outputs


def _validate_staged(outputs: dict[Path, bytes], staged: dict[Path, Path]) -> None:
    if any(hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest() for destination, data in outputs.items() for path in [staged[destination]]):
        raise ValueError("staged artifact hash mismatch")
    if ROOT / "catalog.snapshot.json" not in staged or ROOT / "registry.json" not in staged:
        return
    readmes = tuple(staged[path] for path in (ROOT / "README.md", ROOT / "README.en.md") if path in staged)
    if len(readmes) != 2:
        raise ValueError("staged README artifacts are required")
    verify(staged[ROOT / "catalog.snapshot.json"], staged[ROOT / "registry.json"], readmes)


def promote_artifacts(outputs: dict[Path, bytes]) -> None:
    """Stage every output and restore all prior destinations on controlled replacement failure."""
    previous = {destination: destination.read_bytes() if destination.exists() else None for destination in outputs}
    with tempfile.TemporaryDirectory(dir=ROOT, prefix=".catalog-stage-") as temporary:
        stage_root = Path(temporary)
        staged = {}
        for index, (destination, data) in enumerate(sorted(outputs.items(), key=lambda item: str(item[0]))):
            staged_path = stage_root / str(index)
            staged_path.write_bytes(data)
            staged[destination] = staged_path
        _validate_staged(outputs, staged)
        try:
            for destination in sorted(outputs, key=str):
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged[destination], destination)
        except Exception:
            for destination, old in previous.items():
                if old is None:
                    if destination.exists():
                        destination.unlink()
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(old)
            raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-mode", choices=("audit", "enforce"), default="audit")
    parser.add_argument("--full", action="store_true", help="Compatibility switch; catalog scans are always full-inventory.")
    args = parser.parse_args()
    previous_path = ROOT / "registry.json"
    previous = {row["name"]: row for row in json.loads(previous_path.read_text(encoding="utf-8"))} if previous_path.exists() else {}
    entries, resources = collect_entries(list_asset_repos(), previous, args.contract_mode, validation_date=dt.date.today().isoformat())
    snapshot = build_snapshot(entries, resources, load_taxonomy(ROOT), {"version": "1.0.0", "items": []}, {"version": "1.0.0", "items": []})
    promote_artifacts(render_artifacts(snapshot))
    print(f"published snapshot {snapshot['snapshot_id']} ({len(entries)} assets)")


if __name__ == "__main__":
    main()
