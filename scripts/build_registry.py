#!/usr/bin/env python3
"""Build deterministic public registry artifacts from one catalog snapshot."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from catalog_contract import canonical_json, load_taxonomy, validate_asset_semantics, validate_frontmatter_schema
from validate_skill import declaration_info, parse_frontmatter, validate
from verify_catalog_artifacts import verify
from catalog_projection import public_registry_projection
from compatibility import _parse_range, build_compatibility_edges
from interface_catalog import load_contract_catalogs, load_core_lineage

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


def shallow_clone(name: str, destination: Path, expected_sha: str = "") -> str:
    import subprocess
    subprocess.run(["git", "clone", "--depth", "1", "--quiet", f"https://github.com/{ORG}/{name}.git", str(destination)], check=True)
    clone_sha = subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if expected_sha and clone_sha != expected_sha:
        raise ValueError(f"default branch changed during frozen build for {name}")
    return clone_sha


def load_inventory(path: Path = INVENTORY_PATH) -> dict:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema_version") != "1.0.0" or not isinstance(inventory.get("assets"), list) or set(_inventory_names(inventory.get("resources", []))) != set(RESOURCE_NAMES):
        raise ValueError("invalid catalog inventory")
    return inventory


def _inventory_names(records: list) -> list[str]:
    return [record["name"] if isinstance(record, dict) else record for record in records]


def repositories_from_frozen_inventory(inventory: dict) -> list[dict]:
    records = inventory.get("assets", []) + inventory.get("resources", [])
    if not all(isinstance(record, dict) and isinstance(record.get("name"), str) for record in records):
        raise ValueError("invalid frozen repository inventory")
    return [{"name": record["name"], "html_url": f"https://github.com/{ORG}/{record['name']}", "head_sha": record.get("head_sha", ""), "declaration_url": (record.get("declaration") or {}).get("url", "")} for record in records]


def frozen_frontmatter(repo: dict) -> dict | None:
    """Read exactly the declaration URL closed by a frozen inventory record."""
    url = repo.get("declaration_url")
    if not url:
        return None
    raw = url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
    response = requests.get(raw, timeout=30)
    response.raise_for_status()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / ("AGENTS.md" if repo["name"].startswith("agent-") else "SKILL.md")
        path.write_text(response.text, encoding="utf-8")
        return parse_frontmatter(path)


def apply_approved_assignments(entries: list[dict], assignments_path: Path) -> None:
    """Apply only reviewed catalog facts; never infer interfaces from migration candidates."""
    with Path(assignments_path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_name = {row.get("name"): row for row in rows}
    names = {entry["name"] for entry in entries}
    if set(by_name) != names or any(row.get("review_status") != "approved" for row in rows):
        raise ValueError("approved assignments do not close the frozen asset inventory")
    for entry in entries:
        row = by_name[entry["name"]]
        stages = row.get("workflow_stages", "").split("|")
        values = (row.get("category"), row.get("subcategory"), row.get("primary_stage"), row.get("summary_zh"), row.get("summary_en"))
        if not all(isinstance(value, str) and value.strip() for value in values) or not all(stages):
            raise ValueError(f"invalid approved assignment for {entry['name']}")
        entry["catalog"] = {"category": row["category"], "subcategory": row["subcategory"]}
        entry["workflow"] = {"primary_stage": row["primary_stage"], "workflow_stages": stages}
        entry["category"], entry["subcategory"], entry["stage"] = row["category"], row["subcategory"], row["primary_stage"]
        entry["summary_zh"], entry["summary_en"] = row["summary_zh"], row["summary_en"]


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
    def rejected(field: str) -> bool:
        prefix = f"{qs_path}.{field}"
        return any(path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[") for path in paths)

    entry["project_type"] = entry["project_type"] if entry["project_type"] in {"skill", "agent"} and f"{qs_path}.project_type" not in paths else ("agent" if name.startswith("agent-") else "skill")
    entry["declaration_file"] = "AGENTS.md" if entry["project_type"] == "agent" else "SKILL.md"
    entry["description"] = entry["description"] if isinstance(entry["description"], str) and "$.description" not in paths else ""
    entry["status"] = entry["status"] if entry["status"] in {"draft", "active", "stable", "deprecated"} and not rejected("status") else "draft"
    entry["validation_level"] = entry["validation_level"] if entry["validation_level"] in {"listed", "runnable", "verified"} and not rejected("validation_level") else "listed"
    entry["maintainer_type"] = entry["maintainer_type"] if entry["maintainer_type"] in {"official", "community"} and not rejected("maintainer_type") else "community"
    entry["license"] = entry["license"] if isinstance(entry["license"], str) and entry["license"] and not rejected("license") else "GPL-3.0-only"
    entry["tags"] = entry["tags"] if isinstance(entry["tags"], list) and all(isinstance(item, str) for item in entry["tags"]) and not rejected("tags") else []
    entry["requires"] = entry["requires"] if isinstance(entry["requires"], list) and all(isinstance(item, str) for item in entry["requires"]) and not rejected("requires") else []
    entry["platforms"] = entry["platforms"] if isinstance(entry["platforms"], list) and all(isinstance(item, str) for item in entry["platforms"]) and not rejected("platforms") else []
    entry["summary_zh"] = entry["summary_zh"] if isinstance(entry["summary_zh"], str) and not rejected("summary_zh") else "unknown"
    entry["summary_en"] = entry["summary_en"] if isinstance(entry["summary_en"], str) and not rejected("summary_en") else "unknown"
    if rejected("catalog") and name not in {"skill-template", "agent-template"}:
        entry["catalog"] = {"category": "unknown", "subcategory": "unknown"}
    if rejected("workflow") and name not in {"skill-template", "agent-template"}:
        entry["workflow"] = {"primary_stage": "unknown", "workflow_stages": []}
    if rejected("catalog") and name in {"skill-template", "agent-template"}:
        entry["catalog"] = {"category": "10", "subcategory": f"10.{name}"}
    if rejected("workflow") and name in {"skill-template", "agent-template"}:
        entry["workflow"] = {"primary_stage": "orchestration", "workflow_stages": ["orchestration"]}
    if rejected("interface"):
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
    expected = set(_inventory_names(inventory["assets"])) | set(_inventory_names(inventory["resources"]))
    if set(names) != expected:
        raise ValueError("catalog inventory mismatch")
    resources_by_name = {repo["name"]: {"name": repo["name"], "url": repo.get("html_url") or repo.get("url") or f"https://github.com/{ORG}/{repo['name']}"} for repo in repos if repo["name"] in RESOURCE_NAMES}
    entries = []
    frozen_assets = [repo for repo in repos if repo["name"] not in RESOURCE_NAMES and repo.get("declaration_url")]
    if frozen_assets and len(frozen_assets) == len([repo for repo in repos if repo["name"] not in RESOURCE_NAMES]):
        def frozen_entry(repo: dict) -> dict:
            name = repo["name"]
            frontmatter = frozen_frontmatter(repo)
            if name != "skill-pandadata-warehouse":
                frontmatter = {"description": (frontmatter or {}).get("description", "")}
            entry = _entry_from_frontmatter(name, frontmatter or {"description": repo.get("description", "")}, repo["head_sha"], contract_mode, validation_date)
            entry["health"] = "frozen-declaration-only"
            return entry
        with ThreadPoolExecutor(max_workers=16) as executor:
            entries = list(executor.map(frozen_entry, frozen_assets))
        return sorted(entries, key=lambda entry: entry["name"]), [resources_by_name[name] for name in RESOURCE_NAMES]
    for repo in (repo for repo in repos if repo["name"] not in RESOURCE_NAMES):
        name = repo["name"]
        if "frontmatter" in repo:
            entries.append(_entry_from_frontmatter(name, repo["frontmatter"], repo.get("commit_sha", ""), contract_mode, validation_date))
            continue
        if repo.get("declaration_url"):
            frontmatter = frozen_frontmatter(repo)
            # The migration matrix is approved for catalog facts, not endpoint publication.
            # Only the merged Warehouse declaration is an active public contract in this release.
            if name != "skill-pandadata-warehouse":
                frontmatter = {"description": (frontmatter or {}).get("description", "")}
            entry = _entry_from_frontmatter(name, frontmatter or {"description": repo.get("description", "")}, repo["head_sha"], contract_mode, validation_date)
            entry["health"] = "frozen-declaration-only"
            entries.append(entry)
            continue
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / name
            clone_sha = shallow_clone(name, directory, repo.get("head_sha", ""))
            kind, declaration = declaration_info(directory)
            frontmatter = parse_frontmatter(directory / declaration) if declaration else None
            report = validate(directory, set(names), contract_mode)
            if not frontmatter and contract_mode != "audit":
                raise ValueError(f"invalid declaration for {name}")
            entry = _entry_from_frontmatter(name, frontmatter or {"description": repo.get("description", "")}, clone_sha, contract_mode, validation_date)
            entry["health"] = report.health
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry["name"]), [resources_by_name[name] for name in RESOURCE_NAMES]


def _stable_snapshot(snapshot: dict) -> dict:
    if isinstance(snapshot, dict):
        return {key: _stable_snapshot(value) for key, value in snapshot.items() if key not in {"snapshot_id", "generated_at", "validated_at", "scan_time", "last_validated"}}
    if isinstance(snapshot, list):
        return [_stable_snapshot(value) for value in snapshot]
    return snapshot


_ENFORCE_ASSETS = {
    "skill-pandadata-warehouse", "skill-factor-mining-pandaai", "skill-factor-grouped-wrapper",
    "skill-portfolio-optimize", "skill-backtest", "skill-ssquant-ai-trader",
}


def _catalogs(profiles: dict | None, adapters: dict | None, envelope: dict | None, provider_mappings: dict | None) -> tuple[dict, dict, dict, dict]:
    canonical_envelope, canonical_profiles, canonical_adapters, canonical_mappings = load_contract_catalogs()
    supplied = (profiles, adapters, envelope, provider_mappings)
    canonical = (canonical_profiles, canonical_adapters, canonical_envelope, canonical_mappings)
    if any(value is not None for value in supplied) and any(value is None for value in supplied):
        raise ValueError("all interface catalogs must be supplied together")
    if any(value is not None and canonical_json(value) != canonical_json(expected) for value, expected in zip(supplied, canonical)):
        raise ValueError("untrusted interface catalog")
    return canonical_envelope, canonical_profiles, canonical_adapters, canonical_mappings


def _interface_diagnostics(entry: dict, envelope: dict, profiles: dict) -> list[dict]:
    interface = entry.get("interface")
    if not isinstance(interface, dict) or interface.get("mode") not in {"structured", "hybrid"}:
        return []
    known = {(item["id"], item["version"]) for item in profiles["items"]}
    if interface.get("envelope") != {"name": envelope["name"], "version": "1.0.0"}:
        return [{"code": "interface-envelope", "path": "$.interface.envelope"}]
    diagnostics: list[dict] = []
    outputs, inputs = interface.get("outputs", []), interface.get("inputs", [])
    if not isinstance(outputs, list):
        diagnostics.append({"code": "interface-output", "path": "$.interface.outputs"}); outputs = []
    if not isinstance(inputs, list):
        diagnostics.append({"code": "interface-input", "path": "$.interface.inputs"}); inputs = []
    for index, item in enumerate(outputs):
        if not isinstance(item, dict) or set(item) != {"profile", "version"} or (item.get("profile"), item.get("version")) not in known:
            diagnostics.append({"code": "interface-output", "path": f"$.interface.outputs[{index}]"})
    for index, item in enumerate(inputs):
        if (not isinstance(item, dict) or set(item) != {"profile", "version_range", "required"}
                or not isinstance(item.get("required"), bool) or item.get("profile") not in {profile for profile, _ in known}
                or _parse_range(item.get("version_range")) is None):
            diagnostics.append({"code": "interface-input", "path": f"$.interface.inputs[{index}]"})
    return diagnostics



def build_snapshot(entries: list[dict], resources: list[dict], taxonomy: dict, profiles: dict | None = None, adapters: dict | None = None, envelope: dict | None = None, provider_mappings: dict | None = None, *, contract_mode: str = "audit", core_lineage: dict | None = None) -> dict:
    if contract_mode not in {"audit", "enforce"}:
        raise ValueError("contract_mode must be 'audit' or 'enforce'")
    names = [entry.get("name") for entry in entries]
    if not entries or len(names) != len(set(names)) or any(not name for name in names):
        raise ValueError("assets must be nonempty and unique")
    resource_names = sorted(resource.get("name") for resource in resources)
    if resource_names != sorted(RESOURCE_NAMES):
        raise ValueError("closed organization resource inventory is incomplete")
    envelope, profiles, adapters, provider_mappings = _catalogs(profiles, adapters, envelope, provider_mappings)
    canonical_lineage = load_core_lineage()
    if core_lineage is not None and canonical_json(core_lineage) != canonical_json(canonical_lineage):
        raise ValueError("untrusted core lineage")
    diagnostics = [diagnostic for entry in entries for diagnostic in _interface_diagnostics(entry, envelope, profiles)]
    valid_entries = [entry for entry in entries if not _interface_diagnostics(entry, envelope, profiles)]
    edges = build_compatibility_edges(valid_entries, adapters["items"])
    # Asset-set gating only controls smoke-fixture projection; compatibility edges remain declaration-derived.
    closed_chain = not diagnostics and set(names) == _ENFORCE_ASSETS
    if contract_mode == "enforce":
        if not closed_chain:
            raise ValueError("enforce requires the approved core asset set")
    snapshot = {
        "schema_version": "1.0.0", "taxonomy_version": taxonomy.get("schema_version"), "contract_mode": contract_mode,
        "taxonomy": taxonomy, "assets": sorted(entries, key=lambda entry: entry["name"]),
        "resources": sorted(resources, key=lambda resource: resource["name"]),
        "envelope": {"version": envelope["version"], "name": envelope["name"], "items": sorted(envelope["items"], key=canonical_json)},
        "profiles": {"version": profiles["version"], "items": sorted(profiles["items"], key=canonical_json)},
        "adapters": {"version": adapters["version"], "items": sorted(adapters["items"], key=canonical_json)},
        "provider_mappings": {"version": provider_mappings["version"], "items": sorted(provider_mappings["items"], key=canonical_json)},
        "core_lineage": canonical_lineage if closed_chain else {"version": "1.0.0", "scope": "schema-smoke-only", "artifacts": []}, "interface_diagnostics": sorted(diagnostics, key=canonical_json),
        "compatibility_edges": edges,
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
    parser.add_argument("--inventory", type=Path, help="Frozen inventory; pins all declaration reads to default-branch HEADs.")
    parser.add_argument("--assignments", type=Path, help="Reviewed migration assignments CSV.")
    args = parser.parse_args()
    previous_path = ROOT / "registry.json"
    previous = {row["name"]: row for row in json.loads(previous_path.read_text(encoding="utf-8"))} if previous_path.exists() else {}
    inventory = load_inventory(args.inventory) if args.inventory else None
    repos = repositories_from_frozen_inventory(inventory) if inventory else list_asset_repos()
    entries, resources = collect_entries(repos, previous, args.contract_mode, inventory=inventory, validation_date=dt.date.today().isoformat())
    if args.assignments:
        apply_approved_assignments(entries, args.assignments)
    envelope, profiles, adapters, mappings = load_contract_catalogs()
    snapshot = build_snapshot(entries, resources, load_taxonomy(ROOT), profiles, adapters, envelope, mappings, contract_mode=args.contract_mode)
    promote_artifacts(render_artifacts(snapshot))
    print(f"published snapshot {snapshot['snapshot_id']} ({len(entries)} assets)")


if __name__ == "__main__":
    main()
