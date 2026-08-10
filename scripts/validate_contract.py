"""Deterministic Envelope/Profile contract validation library and CLI."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, SchemaError

try:
    from .contract_runtime import envelope_semantic_issues, profile_semantic_issues
except ImportError:
    from contract_runtime import envelope_semantic_issues, profile_semantic_issues


_LAYER_ORDER = {"envelope": 0, "profile": 1}
_PROFILE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?![\s\S])")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?![\s\S])")


def load_profile_index(root: Path) -> dict:
    """Load the canonical profile index without applying any fallback policy."""
    return json.loads((Path(root) / "schema" / "profiles" / "index.json").read_text(encoding="utf-8"))


def resolve_profile(profile: str, version: str, index: dict) -> Path | None:
    """Return the exact relative schema path for a profile/version pair."""
    if not isinstance(index, dict) or not isinstance(index.get("profiles"), list):
        return None
    matches = [
        row
        for row in index["profiles"]
        if isinstance(row, dict)
        and row.get("id") == profile
        and row.get("version") == version
        and isinstance(row.get("schema"), str)
    ]
    if len(matches) != 1:
        return None
    return Path(matches[0]["schema"])


def _profile_index_is_valid(index: object) -> bool:
    if not isinstance(index, dict) or not isinstance(index.get("profiles"), list):
        return False
    seen: set[tuple[str, str]] = set()
    for row in index["profiles"]:
        if not isinstance(row, dict):
            return False
        profile = row.get("id")
        version = row.get("version")
        schema = row.get("schema")
        kind = row.get("kind")
        if (
            not isinstance(profile, str)
            or _PROFILE_ID.fullmatch(profile) is None
            or not isinstance(version, str)
            or _VERSION.fullmatch(version) is None
            or not isinstance(schema, str)
            or not schema
            or kind not in {"base", "result"}
            or (profile, version) in seen
        ):
            return False
        seen.add((profile, version))
    return True


def _pointer(path: object) -> str:
    if isinstance(path, str):
        return path
    tokens = [str(token).replace("~", "~0").replace("/", "~1") for token in path]
    if not tokens:
        return ""
    return "/" + "/".join(tokens)


def _diagnostic(layer: str, code: str, path: str) -> dict:
    return {"layer": layer, "code": str(code), "path": _pointer(path)}


def _canonical_diagnostics(diagnostics: list[dict]) -> list[dict]:
    unique = {
        (item.get("layer"), item.get("code"), item.get("path"))
        for item in diagnostics
        if isinstance(item, dict)
        and isinstance(item.get("layer"), str)
        and isinstance(item.get("code"), str)
        and isinstance(item.get("path"), str)
    }
    return [
        {"layer": layer, "code": code, "path": path}
        for layer, code, path in sorted(
            unique,
            key=lambda item: (_LAYER_ORDER.get(item[0], 99), item[0], item[1], item[2]),
        )
    ]


def _schema_diagnostics(layer: str, validator: Draft202012Validator, document: object) -> list[dict]:
    return [
        _diagnostic(layer, str(error.validator), _pointer(error.absolute_path))
        for error in validator.iter_errors(document)
    ]


def _semantic_diagnostics(layer: str, issues: object) -> list[dict]:
    if not isinstance(issues, list):
        return []
    return [
        _diagnostic(layer, issue.get("code"), issue.get("path"))
        for issue in issues
        if isinstance(issue, dict)
        and isinstance(issue.get("code"), str)
        and isinstance(issue.get("path"), str)
    ]


def _result(status: str, envelope: dict | None, profile: dict | None, errors: list[dict] | None = None) -> dict:
    return {
        "status": status,
        "envelope": envelope,
        "profile": profile,
        "errors": _canonical_diagnostics(errors or []),
        "warnings": [],
    }


def _identity(document: object) -> tuple[dict | None, dict | None, list[dict]]:
    if not isinstance(document, dict):
        return None, None, [_diagnostic("envelope", "contract-identity", "")]
    contract = document.get("$contract")
    if not isinstance(contract, dict):
        return None, None, [_diagnostic("envelope", "contract-identity", "/$contract")]
    values = (
        ("envelope", contract.get("envelope"), "/$contract/envelope"),
        ("envelope_version", contract.get("envelope_version"), "/$contract/envelope_version"),
        ("profile", contract.get("profile"), "/$contract/profile"),
        ("profile_version", contract.get("profile_version"), "/$contract/profile_version"),
    )
    invalid = [
        _diagnostic("envelope", "contract-identity", path)
        for _name, value, path in values
        if not isinstance(value, str) or not value
    ]
    if invalid:
        return None, None, invalid
    envelope = {"name": contract["envelope"], "version": contract["envelope_version"]}
    profile = {"id": contract["profile"], "version": contract["profile_version"]}
    return envelope, profile, []


def _safe_path(root: Path, relative: Path) -> Path | None:
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / relative).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def _read_schema(root: Path, relative: Path, layer: str) -> tuple[dict | None, list[dict]]:
    path = _safe_path(root, relative)
    if path is None or not path.is_file():
        return None, [_diagnostic(layer, f"{layer}-schema", f"/schema/{layer}")]
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError("schema must be an object")
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, json.JSONDecodeError, SchemaError):
        return None, [_diagnostic(layer, f"{layer}-schema", f"/schema/{layer}")]
    return schema, []


def _load_envelope_index(root: Path) -> tuple[dict | None, list[dict]]:
    path = Path(root) / "schema" / "envelope" / "index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None, [_diagnostic("envelope", "envelope-index", "/schema/envelope/index.json")]
    if (
        not isinstance(index, dict)
        or not isinstance(index.get("name"), str)
        or not isinstance(index.get("versions"), dict)
    ):
        return None, [_diagnostic("envelope", "envelope-index", "/schema/envelope/index.json")]
    return index, []


def validate_contract(document: dict, root: Path) -> dict:
    """Validate one document against its exact canonical Envelope and Profile schemas."""
    envelope, profile, identity_errors = _identity(document)
    if identity_errors:
        return _result("unknown", envelope, profile, identity_errors)
    assert envelope is not None and profile is not None

    envelope_index, index_errors = _load_envelope_index(root)
    if index_errors:
        return _result("unknown", envelope, profile, index_errors)
    assert envelope_index is not None
    if envelope_index["name"] != envelope["name"]:
        return _result("unknown", envelope, profile, [_diagnostic("envelope", "envelope-unknown", "/$contract/envelope")])
    envelope_versions = envelope_index["versions"]
    envelope_schema_name = envelope_versions.get(envelope["version"])
    if not isinstance(envelope_schema_name, str):
        return _result("unknown", envelope, profile, [_diagnostic("envelope", "envelope-version-unknown", "/$contract/envelope_version")])
    if _PROFILE_ID.fullmatch(profile["id"]) is None:
        return _result("unknown", envelope, profile, [_diagnostic("profile", "profile-identity", "/$contract/profile")])
    if _VERSION.fullmatch(profile["version"]) is None:
        return _result("unknown", envelope, profile, [_diagnostic("profile", "profile-version-identity", "/$contract/profile_version")])

    envelope_schema, schema_errors = _read_schema(root, Path("schema") / "envelope" / envelope_schema_name, "envelope")
    if schema_errors:
        return _result("unknown", envelope, profile, schema_errors)
    assert envelope_schema is not None
    envelope_validator = Draft202012Validator(envelope_schema, format_checker=FormatChecker())
    envelope_errors = _schema_diagnostics("envelope", envelope_validator, document)
    envelope_errors.extend(_semantic_diagnostics("envelope", envelope_semantic_issues(document)))
    if envelope_errors:
        return _result("invalid", envelope, profile, envelope_errors)

    try:
        profile_index = load_profile_index(root)
    except (OSError, ValueError, json.JSONDecodeError):
        return _result("unknown", envelope, profile, [_diagnostic("profile", "profile-index", "/schema/profiles/index.json")])
    if not _profile_index_is_valid(profile_index):
        return _result("unknown", envelope, profile, [_diagnostic("profile", "profile-index", "/schema/profiles/index.json")])
    profile_schema_name = resolve_profile(profile["id"], profile["version"], profile_index)
    if profile_schema_name is None:
        rows = profile_index.get("profiles") if isinstance(profile_index, dict) else None
        known_id = isinstance(rows, list) and any(
            isinstance(row, dict) and row.get("id") == profile["id"] for row in rows
        )
        code = "profile-version-unknown" if known_id else "profile-unknown"
        path = "/$contract/profile_version" if known_id else "/$contract/profile"
        return _result("unknown", envelope, profile, [_diagnostic("profile", code, path)])

    profile_schema, schema_errors = _read_schema(root, Path("schema") / "profiles" / profile_schema_name, "profile")
    if schema_errors:
        return _result("unknown", envelope, profile, schema_errors)
    assert profile_schema is not None
    profile_validator = Draft202012Validator(profile_schema, format_checker=FormatChecker())
    profile_errors = _schema_diagnostics("profile", profile_validator, document)
    profile_errors.extend(_semantic_diagnostics("profile", profile_semantic_issues(document)))
    if profile_errors:
        return _result("invalid", envelope, profile, profile_errors)
    return _result("valid", envelope, profile)


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _unknown_input(code: str) -> dict:
    return _result("unknown", None, None, [_diagnostic("envelope", code, "")])


def _load_document(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    document = json.loads(
        text,
        object_pairs_hook=_strict_object_pairs,
        parse_constant=_reject_constant,
    )
    if not isinstance(document, dict):
        raise ValueError("document must be a JSON object")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a canonical Envelope/Profile contract")
    parser.add_argument("document", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        document = _load_document(args.document)
    except (OSError, UnicodeError):
        result = _unknown_input("input-unreadable")
    except (ValueError, json.JSONDecodeError):
        result = _unknown_input("input-json")
    else:
        result = validate_contract(document, Path(__file__).resolve().parents[1])
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    else:
        print(result["status"])
        for error in result["errors"]:
            print(f"{error['layer']} {error['code']} {error['path']}")
    return {"valid": 0, "invalid": 1, "unknown": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
