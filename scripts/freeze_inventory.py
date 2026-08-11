#!/usr/bin/env python3
"""Freeze the public QuantSkills inventory from GitHub without remote writes."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_NAMES = (".github", "join", "quantskills", "registry")
EXPECTED = {"skill": 149, "agent": 9, "resource": 4}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _record(request, base: str, org: str, repo: dict) -> dict:
    name, branch = repo["name"], repo["default_branch"]
    head = request(f"{base}/repos/{org}/{name}/commits/{quote(branch, safe='')}")["sha"]
    record = {"name": name, "default_branch": branch, "head_sha": head, "description": repo.get("description") or "", "topics": sorted(repo.get("topics") or [])}
    if name.startswith(("skill-", "agent-")):
        declaration = "SKILL.md" if name.startswith("skill-") else "AGENTS.md"
        request(f"{base}/repos/{org}/{name}/contents/{declaration}?ref={quote(head, safe='')}")
        record["declaration"] = {"file": declaration, "url": f"https://github.com/{org}/{name}/blob/{head}/{declaration}"}
    return record


def freeze_inventory(request, api_base: str, organization: str, expected: dict | None = None) -> dict:
    repos, page = [], 1
    while True:
        batch = request(f"{api_base}/orgs/{organization}/repos?type=all&per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ValueError("GitHub response is not a repository list")
        repos.extend(batch)
        if not batch:
            break
        page += 1
    selected = [repo for repo in repos if isinstance(repo, dict) and not repo.get("archived") and not repo.get("fork") and not repo.get("private") and (repo.get("name", "").startswith(("skill-", "agent-")) or repo.get("name") in RESOURCE_NAMES)]
    grouped = {"skill": [repo for repo in selected if repo["name"].startswith("skill-")], "agent": [repo for repo in selected if repo["name"].startswith("agent-")], "resource": [repo for repo in selected if repo["name"] in RESOURCE_NAMES]}
    counts = {key: len(value) for key, value in grouped.items()}
    if counts != (expected or EXPECTED):
        raise ValueError(f"unexpected repository counts: {counts}")
    if {repo["name"] for repo in grouped["resource"]} != set(RESOURCE_NAMES):
        raise ValueError("required resources are not closed")
    selected_records = grouped["skill"] + grouped["agent"] + [next(repo for repo in grouped["resource"] if repo["name"] == name) for name in RESOURCE_NAMES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
        records = list(executor.map(lambda repo: _record(request, api_base, organization, repo), selected_records))
    by_name = {record["name"]: record for record in records}
    body = {"schema_version": "1.0.0", "organization": organization, "assets": sorted((by_name[repo["name"]] for repo in grouped["skill"] + grouped["agent"]), key=lambda item: item["name"]), "resources": [by_name[name] for name in RESOURCE_NAMES]}
    body["sha256"] = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    return body


def freeze_repositories(repositories: list[dict], organization: str, head_lookup, expected: dict | None = None) -> dict:
    """Freeze already-listed public repositories, closing each default branch at its SHA."""
    selected = [repo for repo in repositories if isinstance(repo, dict) and not repo.get("archived", repo.get("isArchived")) and not repo.get("fork", repo.get("isFork")) and not repo.get("private", repo.get("isPrivate", repo.get("visibility") != "PUBLIC")) and (repo.get("name", "").startswith(("skill-", "agent-")) or repo.get("name") in RESOURCE_NAMES)]
    grouped = {"skill": [repo for repo in selected if repo["name"].startswith("skill-")], "agent": [repo for repo in selected if repo["name"].startswith("agent-")], "resource": [repo for repo in selected if repo["name"] in RESOURCE_NAMES]}
    counts = {key: len(value) for key, value in grouped.items()}
    if counts != (expected or EXPECTED):
        raise ValueError(f"unexpected repository counts: {counts}")
    if {repo["name"] for repo in grouped["resource"]} != set(RESOURCE_NAMES):
        raise ValueError("required resources are not closed")
    def record(repo: dict) -> dict:
        name = repo["name"]
        branch = repo.get("default_branch") or ((repo.get("defaultBranchRef") or {}).get("name"))
        if not isinstance(branch, str) or not branch:
            raise ValueError("missing default branch")
        head = head_lookup(name, branch)
        if not isinstance(head, str) or len(head) != 40:
            raise ValueError("missing target HEAD")
        repository_topics = repo.get("repositoryTopics")
        topic_nodes = repository_topics.get("nodes", []) if isinstance(repository_topics, dict) else (repository_topics if isinstance(repository_topics, list) else [])
        topics = repo.get("topics") or [row.get("topic", {}).get("name") if isinstance(row, dict) else row for row in topic_nodes]
        value = {"name": name, "default_branch": branch, "head_sha": head, "description": repo.get("description") or "", "topics": sorted(item for item in topics if isinstance(item, str))}
        if name.startswith(("skill-", "agent-")):
            declaration = "SKILL.md" if name.startswith("skill-") else "AGENTS.md"
            value["declaration"] = {"file": declaration, "url": f"https://github.com/{organization}/{name}/blob/{head}/{declaration}"}
        return value
    targets = grouped["skill"] + grouped["agent"] + [next(repo for repo in grouped["resource"] if repo["name"] == name) for name in RESOURCE_NAMES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
        records = list(executor.map(record, targets))
    by_name = {record["name"]: record for record in records}
    body = {"schema_version": "1.0.0", "organization": organization, "assets": sorted((by_name[repo["name"]] for repo in grouped["skill"] + grouped["agent"]), key=lambda item: item["name"]), "resources": [by_name[name] for name in RESOURCE_NAMES]}
    body["sha256"] = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    return body


def _command(args: list[str]) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30).stdout
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise ValueError("GitHub command failed") from error


def _gh_repositories(organization: str) -> list[dict]:
    try:
        value = json.loads(_command(["gh", "repo", "list", organization, "--limit", "1000", "--json", "name,defaultBranchRef,isArchived,isFork,visibility,description,repositoryTopics"]))
    except json.JSONDecodeError as error:
        raise ValueError("GitHub command returned invalid JSON") from error
    if not isinstance(value, list):
        raise ValueError("GitHub command returned invalid repository list")
    return value


def _head(organization: str, name: str, branch: str) -> str:
    output = _command(["git", "ls-remote", f"https://github.com/{organization}/{name}.git", f"refs/heads/{branch}"])
    fields = output.strip().split()
    return fields[0] if len(fields) == 2 and fields[1] == f"refs/heads/{branch}" else ""


def _request(url: str) -> object:
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            if attempt == 2:
                raise ValueError("GitHub request failed") from error
            time.sleep(0.25 * (attempt + 1))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, default=ROOT / "migration" / "inventory-2026-08-11.json"); parser.add_argument("--sha256-output", type=Path, default=ROOT / "migration" / "inventory-2026-08-11.sha256"); parser.add_argument("--api-base", default="https://api.github.com"); parser.add_argument("--organization", default="quantskills")
    args = parser.parse_args()
    try:
        inventory = freeze_repositories(_gh_repositories(args.organization), args.organization, lambda name, branch: _head(args.organization, name, branch))
    except ValueError as error:
        parser.exit(1, f"freeze failed: {error}\n")
    payload = json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    digest = inventory["sha256"] + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    args.sha256_output.write_text(digest, encoding="utf-8")
    print(f"frozen {len(inventory['assets'])} assets and {len(inventory['resources'])} resources: {inventory['sha256']}")


if __name__ == "__main__":
    main()
