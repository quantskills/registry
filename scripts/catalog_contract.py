"""Small, deterministic validation helpers for catalog declaration v2."""
from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


def _issue(check: str, path: str, detail: str, level: str = "fail") -> dict:
    return {"level": level, "check": check, "path": path, "detail": detail}


def load_taxonomy(root: Path) -> dict:
    """Read the one normative taxonomy file and reject malformed taxonomy data."""
    data = json.loads((root / "schema" / "taxonomy.v1.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("categories"), dict) or not isinstance(data.get("workflow_stages"), list):
        raise ValueError("taxonomy.v1.json must contain object categories and array workflow_stages")
    return data


def _json_path(parts: object) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def validate_frontmatter_schema(frontmatter: dict, schema_path: Path) -> list[dict]:
    """Return schema errors in a stable order without raising on invalid input."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(frontmatter))
        version = ((frontmatter.get("quantSkills") or {}).get("schema_version")
                   if isinstance(frontmatter, dict) else None)
        if schema_path.name == "frontmatter.schema.json" and version in {"2.0.0", "2.1.0"}:
            version_schema = json.loads(schema_path.with_name(f"frontmatter.v{version[:3]}.schema.json").read_text(encoding="utf-8"))
            errors.extend(Draft202012Validator(version_schema).iter_errors(frontmatter))
        return [
            _issue("contract-schema", _json_path(error.absolute_path), error.message)
            for error in sorted(errors, key=lambda error: (_json_path(error.absolute_path), error.message))
        ]
    except (OSError, json.JSONDecodeError) as exc:
        return [_issue("contract-schema", "$", f"schema unavailable: {exc.__class__.__name__}")]


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def github_description(frontmatter: dict) -> str:
    qs = frontmatter.get("quantSkills") or {}
    return f"{qs.get('summary_zh', '')}｜{qs.get('summary_en', '')}"


_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\([^)]*\)")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_EN_PROHIBITED = (
    "official", "certified", "verified", "endorsed", "production-ready",
    "guaranteed return", "guaranteed returns", "risk-free", "safe strategy", "investment advice",
)
_ZH_PROHIBITED = (
    "官方", "认证", "已验证", "背书", "生产可用", "保证收益", "稳赚",
    "无风险", "安全策略", "构成投资建议",
)


def _generic_summary(summary: str, repo_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", summary.lower()).strip()
    repo_words = re.sub(r"[^a-z0-9]+", " ", repo_name.lower()).strip()
    if normalized == repo_words:
        return True
    return bool(re.fullmatch(r"quantskills(?: [a-z0-9]+){0,3} skill repository", normalized))


def _has_prohibited_claim(summary: str) -> bool:
    lower = summary.lower()
    for phrase in _EN_PROHIBITED:
        for match in re.finditer(rf"\b{re.escape(phrase)}\b", lower):
            prefix = lower[max(0, match.start() - 48):match.start()]
            if re.search(r"\b(?:not|no|never|does not|doesn't|is not|are not)(?:[\s-]+[a-z]+){0,3}[\s-]*$", prefix):
                continue
            return True
    for phrase in _ZH_PROHIBITED:
        index = lower.find(phrase)
        if index >= 0 and not any(marker in lower[max(0, index - 4):index] for marker in ("不", "非")):
            return True
    return False


def validate_asset_semantics(frontmatter: dict, repo_name: str, declaration_file: str, taxonomy: dict) -> list[dict]:
    """Validate relationships that the declaration schema intentionally cannot express."""
    qs = frontmatter.get("quantSkills") or {}
    catalog = qs.get("catalog") or {}
    workflow = qs.get("workflow") or {}
    interface = qs.get("interface") or {}
    issues: list[dict] = []
    category, subcategory = catalog.get("category"), catalog.get("subcategory")
    categories = taxonomy.get("categories") if isinstance(taxonomy, dict) else {}
    if not category or not subcategory or category not in categories:
        issues.append(_issue("contract-semantic", "$.quantSkills.catalog", "待迁移：missing or unknown catalog classification"))
    elif subcategory not in {item.get("id") for item in categories[category].get("subcategories", [])}:
        issues.append(_issue("contract-semantic", "$.quantSkills.catalog.subcategory", "subcategory does not belong to declared category"))
    stages = workflow.get("workflow_stages") or []
    if workflow.get("primary_stage") not in stages:
        issues.append(_issue("contract-semantic", "$.quantSkills.workflow.primary_stage", "primary_stage must be included in workflow_stages"))
    expected_type = "skill" if repo_name.startswith("skill-") else "agent" if repo_name.startswith("agent-") else None
    declared_type = {"SKILL.md": "skill", "AGENTS.md": "agent"}.get(declaration_file)
    expected_file = {"skill": "SKILL.md", "agent": "AGENTS.md"}.get(expected_type)
    if (expected_type and (qs.get("project_type") != expected_type or declaration_file != expected_file)) or (declared_type and qs.get("project_type") != declared_type):
        issues.append(_issue("contract-semantic", "$.quantSkills.project_type", "project_type and declaration file must match repository prefix"))
    if qs.get("repository") != repo_name:
        issues.append(_issue("contract-semantic", "$.quantSkills.repository", "repository must equal filesystem repository name"))
    if qs.get("repository_url") != f"https://github.com/quantskills/{qs.get('repository', '')}":
        issues.append(_issue("contract-semantic", "$.quantSkills.repository_url", "repository_url must be the canonical quantskills GitHub URL"))
    if "license" in frontmatter and frontmatter.get("license") != qs.get("license"):
        issues.append(_issue("contract-semantic", "$.license", "root license must equal quantSkills.license"))
    native_runtimes = frontmatter.get("supported-runtimes")
    if native_runtimes is not None and set(native_runtimes) != set(qs.get("platforms") or []):
        issues.append(_issue("contract-semantic", "$.supported-runtimes", "supported-runtimes must exactly match quantSkills.platforms"))
    if qs.get("project_type") == "agent":
        for field in ("allowed-tools", "user-invocable", "disable-model-invocation"):
            if field in frontmatter:
                issues.append(_issue("contract-semantic", f"$.{field}", "Skill permission key is not allowed for agents"))
    if frontmatter.get("user-invocable") is False and frontmatter.get("disable-model-invocation") is True:
        issues.append(_issue("contract-semantic", "$", "invocation is unreachable when user and model invocation are both disabled"))
    if len(github_description(frontmatter)) > 350:
        issues.append(_issue("contract-semantic", "$.quantSkills", "generated GitHub description exceeds 350 Unicode code points"))
    for field in ("summary_zh", "summary_en"):
        summary = qs.get(field)
        if not isinstance(summary, str):
            continue
        path = f"$.quantSkills.{field}"
        if "\n" in summary or "\r" in summary or _MARKDOWN_LINK.search(summary):
            issues.append(_issue("contract-semantic", path, "summary must not contain newlines or Markdown links"))
        if _generic_summary(summary, repo_name):
            issues.append(_issue("contract-semantic", path, "summary is generic repository-name-only copy"))
        if _has_prohibited_claim(summary):
            issues.append(_issue("contract-semantic", path, "summary contains a prohibited claim"))
    if interface.get("mode") in {"structured", "hybrid"}:
        if not interface.get("inputs") and not interface.get("outputs"):
            issues.append(_issue("contract-semantic", "$.quantSkills.interface", "structured or hybrid interface needs an input or output"))
        envelope = interface.get("envelope") or {}
        version_match = _SEMVER.fullmatch(envelope.get("version", "")) if isinstance(envelope.get("version"), str) else None
        if envelope.get("name") != "quantskills-envelope" or not version_match or int(version_match.group(1)) != 1:
            issues.append(_issue("contract-semantic", "$.quantSkills.interface.envelope", "structured or hybrid interface requires quantskills-envelope major version 1"))
    return issues
