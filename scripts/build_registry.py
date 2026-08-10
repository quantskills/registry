#!/usr/bin/env python3
"""Build deterministic public registry artifacts from one catalog snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import requests

from catalog_contract import canonical_json, load_taxonomy
from validate_skill import declaration_info, parse_frontmatter, validate

ROOT = Path(__file__).resolve().parent.parent
ORG = os.environ.get("QS_ORG", "quantskills")
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"} if TOKEN else {}
RESOURCE_NAMES = (".github", "join", "quantskills", "registry")


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


def _entry_from_frontmatter(name: str, frontmatter: dict, commit_sha: str = "", contract_mode: str = "enforce") -> dict:
    qs = frontmatter.get("quantSkills") or {}
    catalog, workflow, interface = qs.get("catalog") or {}, qs.get("workflow") or {}, qs.get("interface") or {}
    project_type = qs.get("project_type") or ("agent" if name.startswith("agent-") else "skill")
    missing_v2 = not isinstance(catalog.get("category"), str) or not isinstance(catalog.get("subcategory"), str) or not isinstance(workflow.get("primary_stage"), str) or not isinstance(workflow.get("workflow_stages"), list) or not isinstance(interface, dict) or not interface.get("mode")
    if missing_v2:
        if contract_mode != "audit" or name not in {"skill-template", "agent-template"}:
            raise ValueError(f"invalid declaration for {name}: missing v2 catalog/workflow/interface")
        subcategory = "10.skill-template" if name == "skill-template" else "10.agent-template"
        catalog = {"category": "10", "subcategory": subcategory}
        workflow = {"primary_stage": "orchestration", "workflow_stages": ["orchestration"]}
        interface = {"mode": "unknown", "reason": "pending-v2-migration"}
    return {
        "name": name, "url": f"https://github.com/{ORG}/{name}", "description": frontmatter.get("description", ""),
        "project_type": project_type, "declaration_file": "AGENTS.md" if project_type == "agent" else "SKILL.md",
        "catalog": catalog, "workflow": workflow, "interface": interface,
        "category": catalog["category"], "subcategory": catalog["subcategory"], "stage": workflow["primary_stage"],
        "tags": qs.get("tags", []), "platforms": qs.get("platforms", []), "status": qs.get("status", "active"),
        "requires": qs.get("requires", []), "summary_zh": qs.get("summary_zh", ""), "summary_en": qs.get("summary_en", ""),
        "license": qs.get("license", "GPL-3.0-only"), "validation_level": qs.get("validation_level", "listed"),
        "maintainer_type": qs.get("maintainer_type", "community"), "last_validated": qs.get("last_validated", ""), "commit_sha": commit_sha,
        **({"migration_state": "pending-v2"} if missing_v2 else {}),
    }


def collect_entries(repos: list[dict], previous: dict, contract_mode: str) -> tuple[list[dict], list[dict]]:
    """Collect entries without writing artifacts; fixtures inject ``frontmatter`` directly."""
    if contract_mode not in {"audit", "enforce"}:
        raise ValueError("contract_mode must be 'audit' or 'enforce'")
    names = [repo.get("name") for repo in repos]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise ValueError("duplicate or empty asset name")
    resources_by_name = {repo["name"]: {"name": repo["name"], "url": repo.get("html_url") or repo.get("url") or f"https://github.com/{ORG}/{repo['name']}"} for repo in repos if repo["name"] in RESOURCE_NAMES}
    if set(resources_by_name) != set(RESOURCE_NAMES):
        raise ValueError("closed organization resource inventory is incomplete")
    entries = []
    for repo in (repo for repo in repos if repo["name"] not in RESOURCE_NAMES):
        name = repo["name"]
        if "frontmatter" in repo:
            entries.append(_entry_from_frontmatter(name, repo["frontmatter"], repo.get("commit_sha", ""), contract_mode))
            continue
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / name
            clone_sha = shallow_clone(name, directory)
            kind, declaration = declaration_info(directory)
            frontmatter = parse_frontmatter(directory / declaration) if declaration else None
            report = validate(directory, set(names), contract_mode)
            if report.health == "quarantined" or not frontmatter:
                raise ValueError(f"invalid declaration for {name}")
            entry = _entry_from_frontmatter(name, frontmatter, clone_sha, contract_mode)
            entry["health"] = report.health
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry["name"]), [resources_by_name[name] for name in RESOURCE_NAMES]


def _stable_snapshot(snapshot: dict) -> dict:
    return {key: value for key, value in snapshot.items() if key not in {"snapshot_id", "generated_at", "validated_at", "scan_time"}}


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


def public_registry_projection(snapshot: dict) -> list[dict]:
    snapshot_id = snapshot["snapshot_id"]
    fields = ("name", "url", "description", "project_type", "declaration_file", "tags", "platforms", "status", "requires", "summary_zh", "summary_en", "license", "validation_level", "maintainer_type", "last_validated", "commit_sha")
    return [{**{field: asset.get(field, "" if field not in {"tags", "platforms", "requires"} else []) for field in fields}, "category": asset["catalog"]["category"], "subcategory": asset["catalog"]["subcategory"], "stage": asset["workflow"]["primary_stage"], "catalog": asset["catalog"], "workflow": asset["workflow"], "interface": asset["interface"], "snapshot_id": snapshot_id} for asset in snapshot["assets"]]


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
    snapshot = json.loads(staged[ROOT / "catalog.snapshot.json"].read_text(encoding="utf-8"))
    registry = json.loads(staged[ROOT / "registry.json"].read_text(encoding="utf-8"))
    if not isinstance(registry, list) or any(row.get("snapshot_id") != snapshot.get("snapshot_id") for row in registry):
        raise ValueError("staged snapshot cross-reference mismatch")


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
    args = parser.parse_args()
    previous_path = ROOT / "registry.json"
    previous = {row["name"]: row for row in json.loads(previous_path.read_text(encoding="utf-8"))} if previous_path.exists() else {}
    entries, resources = collect_entries(list_asset_repos(), previous, args.contract_mode)
    snapshot = build_snapshot(entries, resources, load_taxonomy(ROOT), {"version": "1.0.0", "items": []}, {"version": "1.0.0", "items": []})
    promote_artifacts(render_artifacts(snapshot))
    print(f"published snapshot {snapshot['snapshot_id']} ({len(entries)} assets)")


if __name__ == "__main__":
    main()
