"""Deterministic semantic checks shared by versioned data contracts."""
from __future__ import annotations

from datetime import datetime
import re

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$")


def _issue(code: str, path: str) -> dict:
    return {"code": code, "path": path}


def _strict_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return True


def envelope_semantic_issues(document: object) -> list[dict]:
    """Return stable, value-free Envelope v1 semantic issues."""
    if not isinstance(document, dict):
        return [_issue("envelope-object", "/")]
    issues: list[dict] = []
    meta = document.get("meta")
    if isinstance(meta, dict) and not _strict_rfc3339(meta.get("generated_at")):
        issues.append(_issue("envelope-rfc3339", "/meta/generated_at"))
    schema = document.get("schema")
    if isinstance(schema, dict):
        fields = schema.get("fields")
        primary_key = schema.get("primary_key")
        if isinstance(fields, dict) and isinstance(primary_key, list):
            issues.extend(
                _issue("envelope-primary-key", f"/schema/primary_key/{index}")
                for index, key in enumerate(primary_key)
                if isinstance(key, str) and key not in fields
            )
    return issues
