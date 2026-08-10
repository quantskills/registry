"""Deterministic, declaration-only interface compatibility."""
from __future__ import annotations

import json
import re
from heapq import heappop, heappush
from pathlib import Path


_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_PROFILE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROOT = Path(__file__).resolve().parents[1]


def parse_semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or _SEMVER.fullmatch(value) is None:
        raise ValueError("invalid semantic version")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def version_satisfies(version: str, version_range: str) -> bool:
    try:
        actual = parse_semver(version)
    except ValueError:
        return False
    if not isinstance(version_range, str) or not version_range or version_range.strip() != version_range:
        return False
    clauses = version_range.split(" ")
    if any(not clause or "," in clause for clause in clauses):
        return False
    for clause in clauses:
        match = re.fullmatch(r"(>=|>|<=|<)?((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))", clause)
        if match is None:
            return False
        operator, text = match.groups()
        target = parse_semver(text)
        if operator is None and actual != target:
            return False
        if operator == ">=" and actual < target or operator == ">" and actual <= target or operator == "<=" and actual > target or operator == "<" and actual >= target:
            return False
    return True


def _result(status: str, errors: list[dict] | None = None, path: list[str] | None = None) -> dict:
    errors = errors or []
    unique = {(item["code"], item["path"]) for item in errors if set(item) == {"code", "path"}}
    return {"status": status, "errors": [{"code": code, "path": path} for code, path in sorted(unique)], "adapter_path": path or []}


def _profiles() -> set[tuple[str, str]]:
    try:
        data = json.loads((_ROOT / "schema" / "profiles" / "index.json").read_text(encoding="utf-8"))
        return {(item["id"], item["version"]) for item in data["profiles"] if isinstance(item, dict)}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _endpoint(value: object, input_: bool) -> tuple[tuple[str, str, int] | None, str | None]:
    if not isinstance(value, dict): return None, "endpoint"
    if value.get("mode") in {"natural-language", "not-applicable"}: return None, "not-applicable"
    if value.get("mode") not in {"structured", "hybrid"}: return None, "mode"
    envelope = value.get("envelope")
    if not isinstance(envelope, dict) or envelope.get("name") != "quantskills-envelope": return None, "envelope"
    try: major = parse_semver(envelope.get("version"))[0]
    except ValueError: return None, "envelope"
    profile, version = value.get("profile"), value.get("version_range" if input_ else "version")
    if not isinstance(profile, str) or _PROFILE.fullmatch(profile) is None: return None, "profile"
    if input_:
        if not _valid_range(version): return None, "range"
        if not any(item[0] == profile for item in _profiles()): return None, "profile"
        return (profile, version, major), None
    try: parse_semver(version)
    except ValueError: return None, "version"
    if (profile, version) not in _profiles(): return None, "profile"
    return (profile, version, major), None


def _valid_range(value: object) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value: return False
    return all(re.fullmatch(r"(>=|>|<=|<)?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", item) for item in value.split(" "))


def _adapter(value: object) -> tuple[dict | None, bool]:
    if not isinstance(value, dict): return None, False
    try:
        identifier, source, target, impl, evidence = value["id"], value["source"], value["target"], value["implementation"], value["evidence"]
        valid = (_PROFILE.fullmatch(identifier) and value.get("lossless") is True and value.get("validation_status") == "validated" and value.get("envelope_major") == 1 and isinstance(source, dict) and isinstance(target, dict) and (source.get("profile"), source.get("version")) in _profiles() and (target.get("profile"), target.get("version")) in _profiles() and isinstance(impl, dict) and impl.get("repository") == "registry" and isinstance(impl.get("path"), str) and isinstance(evidence, dict) and re.fullmatch(r"sha256:[0-9a-f]{64}", evidence.get("fixture_sha256", "")) and isinstance(evidence.get("test_command"), str) and evidence["test_command"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", evidence.get("validated_at", "")))
        path = Path(impl["path"])
        resolved = ( _ROOT / path).resolve()
        valid = bool(valid and not path.is_absolute() and ".." not in path.parts and resolved.is_file() and resolved.is_relative_to(_ROOT))
        return (value if valid else None), bool(valid)
    except (KeyError, TypeError, ValueError, OSError): return None, False


def compare_endpoints(output: dict, input_: dict, adapters: list[dict]) -> dict:
    out, out_error = _endpoint(output, False); inn, in_error = _endpoint(input_, True)
    if out_error == "not-applicable" or in_error == "not-applicable": return _result("not-applicable")
    if out_error or in_error: return _result("unknown", [{"code": "endpoint", "path": "/output" if out_error else "/input"}])
    assert out and inn
    profile, version, major = out; wanted, version_range, input_major = inn
    if major != input_major: return _result("incompatible")
    if profile == wanted: return _result("compatible" if version_satisfies(version, version_range) else "incompatible")
    valid, incomplete = [], False
    for row in adapters if isinstance(adapters, list) else []:
        item, ok = _adapter(row)
        if item: valid.append(item)
        elif isinstance(row, dict) and isinstance(row.get("source"), dict) and row["source"].get("profile") == profile:
            incomplete = incomplete or row.get("lossless") is not False
    queue = [((), (profile, version))]; visited = set()
    graph = {}
    for row in valid:
        graph.setdefault((row["source"]["profile"], row["source"]["version"]), []).append(row)
    while queue:
        route, node = heappop(queue)
        if node in visited: continue
        visited.add(node)
        for row in sorted(graph.get(node, []), key=lambda item: item["id"]):
            target = (row["target"]["profile"], row["target"]["version"]); next_route = route + (row["id"],)
            if target[0] == wanted and version_satisfies(target[1], version_range): return _result("adapter-required", path=list(next_route))
            if target not in visited: heappush(queue, (next_route, target))
    return _result("unknown" if incomplete else "incompatible")


def build_compatibility_edges(assets: list[dict], adapters: list[dict]) -> list[dict]:
    edges = []
    for producer in assets:
        interface = producer.get("interface") if isinstance(producer, dict) else None
        if not isinstance(interface, dict) or interface.get("mode") not in {"structured", "hybrid"}: continue
        for consumer in assets:
            target = consumer.get("interface") if isinstance(consumer, dict) else None
            if not isinstance(target, dict) or target.get("mode") not in {"structured", "hybrid"}: continue
            for output in interface.get("outputs", []):
                for input_ in target.get("inputs", []):
                    result = compare_endpoints({**output, "mode": interface["mode"], "envelope": interface.get("envelope")}, {**input_, "mode": target["mode"], "envelope": target.get("envelope")}, adapters)
                    if result["status"] in {"compatible", "adapter-required"}: edges.append({"producer": producer.get("name"), "consumer": consumer.get("name"), "output": {"profile": output.get("profile"), "version": output.get("version")}, "input": {"profile": input_.get("profile"), "version_range": input_.get("version_range"), "required": input_.get("required")}, "status": result["status"], "adapter_path": result["adapter_path"]})
    return sorted({json.dumps(edge, sort_keys=True): edge for edge in edges}.values(), key=lambda edge: json.dumps(edge, sort_keys=True))
