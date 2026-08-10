#!/usr/bin/env python3
"""Read-only deterministic health checks for QuantSkills asset repositories."""
from __future__ import annotations

import argparse
import json
import py_compile
import re
import sys
from pathlib import Path

from catalog_contract import load_taxonomy, validate_asset_semantics, validate_frontmatter_schema

try:
    import yaml
except ImportError:
    sys.exit("missing dependency: pip install pyyaml")


DECLARATION_BY_TYPE = {"skill": "SKILL.md", "agent": "AGENTS.md"}
MAX_FILE_WARN = 2 * 1024 * 1024
MAX_FILE_FAIL = 10 * 1024 * 1024
DATA_EXT_WATCHLIST = {".csv", ".parquet", ".json", ".jsonl", ".xlsx", ".db", ".sqlite", ".zip", ".gz"}
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub PAT"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "API secret key pattern"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)\)")
BACKTICK_PATH_RE = re.compile(r"`((?:\.\./)+[\w./\-]+|(?:scripts|references|collectors|validation|agents)/[\w./\-]+)`")


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, level: str, check: str, detail: str, path: str = "") -> None:
        self.items.append({"level": level, "check": check, "path": path, "detail": detail})

    @property
    def health(self) -> str:
        levels = {item["level"] for item in self.items}
        return "quarantined" if "fail" in levels else "warning" if "warn" in levels else "healthy"


def declaration_info(repo: Path) -> tuple[str | None, str | None]:
    if repo.name.startswith("agent-"):
        return "agent", "AGENTS.md"
    if repo.name.startswith("skill-"):
        return "skill", "SKILL.md"
    if (repo / "AGENTS.md").is_file() and not (repo / "SKILL.md").is_file():
        return "agent", "AGENTS.md"
    if (repo / "SKILL.md").is_file():
        return "skill", "SKILL.md"
    return None, None


def parse_frontmatter(declaration_md: Path) -> dict | None:
    text = declaration_md.read_text(encoding="utf-8", errors="replace")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None


def check_required_files(repo: Path, declaration_file: str | None, rep: Report) -> None:
    if not declaration_file:
        rep.add("fail", "required-files", "missing declaration file SKILL.md or AGENTS.md")
    for name in (declaration_file, "README.md", "LICENSE"):
        if name and not (repo / name).is_file():
            rep.add("fail", "required-files", f"missing required file {name}", name)


def _contract_level(contract_mode: str) -> str:
    return "fail" if contract_mode == "enforce" else "warn"


def check_frontmatter(repo: Path, asset_type: str | None, declaration_file: str | None, rep: Report, contract_mode: str = "audit") -> dict:
    if not declaration_file or not (repo / declaration_file).is_file():
        return {}
    frontmatter = parse_frontmatter(repo / declaration_file)
    if frontmatter is None:
        rep.add("fail", "frontmatter", "missing or invalid YAML frontmatter", declaration_file)
        return {}
    if not frontmatter.get("name"):
        rep.add("fail", "frontmatter", "frontmatter missing name", "$.name")
    description = str(frontmatter.get("description") or "")
    if len(description) < 60 or "use when" not in description.lower():
        rep.add("warn", "frontmatter", "description is too short or lacks a 'Use when' trigger", "$.description")
    root = Path(__file__).resolve().parent.parent
    for issue in validate_frontmatter_schema(frontmatter, root / "schema" / "frontmatter.schema.json"):
        rep.add(_contract_level(contract_mode), issue["check"], issue["detail"], issue["path"])
    try:
        taxonomy = load_taxonomy(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        rep.add("fail", "contract-taxonomy", f"taxonomy unavailable: {exc.__class__.__name__}", "$")
    else:
        for issue in validate_asset_semantics(frontmatter, repo.name, declaration_file, taxonomy):
            rep.add(_contract_level(contract_mode), issue["check"], issue["detail"], issue["path"])
    return frontmatter


def check_path_references(repo: Path, rep: Report) -> None:
    for markdown in repo.rglob("*.md"):
        if ".git" in markdown.parts:
            continue
        refs = {target: "link" for target in LINK_RE.findall(markdown.read_text(encoding="utf-8", errors="replace")) if not target.startswith(("http://", "https://", "mailto:"))}
        refs.update({target: refs.get(target, "mention") for target in BACKTICK_PATH_RE.findall(markdown.read_text(encoding="utf-8", errors="replace"))})
        for ref, kind in sorted(refs.items()):
            clean = ref.split("#", 1)[0].strip()
            if not clean:
                continue
            resolved = (markdown.parent / clean).resolve()
            if not resolved.exists() and (repo / clean).resolve().exists():
                resolved = (repo / clean).resolve()
            try:
                resolved.relative_to(repo.resolve())
                inside = True
            except ValueError:
                inside = False
            if not inside:
                rep.add("warn", "path-refs", f"{markdown.relative_to(repo)} references a path outside the repository: {ref}")
            elif not resolved.exists():
                rep.add("fail" if kind == "link" else "warn", "path-refs", f"{markdown.relative_to(repo)} references a missing path: {ref}")


def check_git_hygiene(repo: Path, rep: Report) -> None:
    for file in repo.rglob("*"):
        if ".git" in file.parts or not file.is_file():
            continue
        size = file.stat().st_size
        if size > MAX_FILE_FAIL:
            rep.add("fail", "git-hygiene", f"{file.relative_to(repo)} exceeds 10MB")
        elif size > MAX_FILE_WARN and file.suffix.lower() in DATA_EXT_WATCHLIST:
            rep.add("warn", "git-hygiene", f"{file.relative_to(repo)} is a data file over 2MB")


def check_secrets(repo: Path, rep: Report) -> None:
    for file in repo.rglob("*"):
        if ".git" in file.parts or not file.is_file() or file.stat().st_size > MAX_FILE_WARN:
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                rep.add("fail", "secrets", f"{file.relative_to(repo)} appears to contain {label}")


def check_quant_risk_disclosures(repo: Path, fm: dict, declaration_file: str | None, rep: Report, contract_mode: str = "audit") -> None:
    qs = (fm or {}).get("quantSkills") or {}
    stages = set((qs.get("workflow") or {}).get("workflow_stages") or [])
    catalog = qs.get("catalog") or {}
    risk_tokens = {"factor", "strategy", "backtest", "signal", "trading", "execution"}
    metadata = [repo.name, catalog.get("category", ""), catalog.get("subcategory", ""), *(qs.get("tags") or [])]
    metadata_tokens = {token for value in metadata if isinstance(value, str) for token in re.findall(r"[a-z0-9]+", value.lower())}
    if not stages & {"factor-generation", "factor-screening", "portfolio-construction", "backtesting", "execution"} and not metadata_tokens & risk_tokens:
        return
    concepts = {"data source": ("数据来源", "data source"), "assumptions": ("假设", "assumption"), "parameters": ("参数", "parameter"), "limitations": ("限制", "limitation"), "risk boundary": ("风险", "risk")}
    level = _contract_level(contract_mode)
    for name in ("README.md", declaration_file):
        text = (repo / name).read_text(encoding="utf-8", errors="replace").lower() if name and (repo / name).is_file() else ""
        for concept, tokens in concepts.items():
            if not any(token.lower() in text for token in tokens):
                rep.add(level, "quant-risk-disclosures", f"missing {concept} disclosure in {name}")
        research = any(token in text for token in ("研究", "教育", "research", "education"))
        non_advice = any(token in text for token in ("不构成任何投资建议", "不构成投资建议", "not investment advice", "does not constitute investment advice"))
        if not (research and non_advice):
            rep.add(level, "quant-risk-disclosures", f"missing research/education and non-advice disclosure in {name}")


def check_python_syntax(repo: Path, rep: Report) -> None:
    for file in repo.rglob("*.py"):
        if ".git" in file.parts:
            continue
        try:
            py_compile.compile(str(file), doraise=True)
        except py_compile.PyCompileError as exc:
            rep.add("fail", "python-syntax", f"{file.relative_to(repo)} syntax error: {exc.msg.splitlines()[0]}")


def check_requires(fm: dict, org_repos: set[str], rep: Report) -> None:
    if not org_repos:
        return
    for dependency in ((fm or {}).get("quantSkills") or {}).get("requires") or []:
        if dependency not in org_repos:
            rep.add("warn", "requires", f"requires references unknown organization repository '{dependency}'")


def validate(repo: Path, org_repos: set[str], contract_mode: str = "audit") -> Report:
    if contract_mode not in {"audit", "enforce"}:
        raise ValueError("contract_mode must be 'audit' or 'enforce'")
    repo = repo.resolve()
    rep = Report()
    asset_type, declaration_file = declaration_info(repo)
    check_required_files(repo, declaration_file, rep)
    frontmatter = check_frontmatter(repo, asset_type, declaration_file, rep, contract_mode)
    check_path_references(repo, rep)
    check_git_hygiene(repo, rep)
    check_secrets(repo, rep)
    check_quant_risk_disclosures(repo, frontmatter, declaration_file, rep, contract_mode)
    check_python_syntax(repo, rep)
    check_requires(frontmatter, org_repos, rep)
    return rep


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--org-repos", default="", help="comma-separated organization repositories for requires validation")
    parser.add_argument("--contract-mode", choices=("audit", "enforce"), default="audit")
    args = parser.parse_args()
    repo = Path(args.repo)
    if not repo.is_dir():
        sys.exit(f"directory does not exist: {repo}")
    report = validate(repo, {name.strip() for name in args.org_repos.split(",") if name.strip()}, args.contract_mode)
    if args.json:
        print(json.dumps({"health": report.health, "items": report.items}, ensure_ascii=False, indent=2))
    else:
        print(f"health: {report.health}")
        for item in report.items:
            print(f"  [{item['level']:4}] {item['check']}: {item['detail']}")
    sys.exit({"healthy": 0, "warning": 1, "quarantined": 2}[report.health])


if __name__ == "__main__":
    main()
