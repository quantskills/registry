"""Deterministic compatibility using only local canonical contract facts."""
from __future__ import annotations

import json
import re
from heapq import heappop, heappush
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[1]
_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROW_KEYS = {"id", "source", "target", "implementation", "lossless", "validation_status", "evidence", "envelope_major"}


def parse_semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or _SEMVER.fullmatch(value) is None:
        raise ValueError("invalid semver")
    return tuple(map(int, value.split(".")))  # type: ignore[return-value]


def _parse_range(value: object) -> list[tuple[str, tuple[int, int, int]]] | None:
    if not isinstance(value, str) or not value or value.strip() != value:
        return None
    parts = value.split(" ")
    if any(not part for part in parts): return None
    exact = [part for part in parts if _SEMVER.fullmatch(part)]
    if exact:
        return [("", parse_semver(exact[0]))] if len(parts) == 1 else None
    result = []
    seen = set()
    for part in parts:
        match = re.fullmatch(r"(>=|>|<=|<)(.+)", part)
        if match is None or part in seen: return None
        seen.add(part)
        try: result.append((match.group(1), parse_semver(match.group(2))))
        except ValueError: return None
    return result


def version_satisfies(version: str, version_range: str) -> bool:
    try: actual = parse_semver(version)
    except ValueError: return False
    clauses = _parse_range(version_range)
    if clauses is None: return False
    return all(op == "" and actual == target or op == ">=" and actual >= target or op == ">" and actual > target or op == "<=" and actual <= target or op == "<" and actual < target for op, target in clauses)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate key")
        result[key] = value
    return result


def _safe(relative: Path) -> Path | None:
    try:
        if relative.is_absolute() or ".." in relative.parts: return None
        resolved = (_ROOT / relative).resolve()
        return resolved if resolved.is_relative_to(_ROOT) else None
    except (OSError, ValueError): return None


def _indexes() -> tuple[set[tuple[str, str]], set[tuple[str, int]]] | None:
    try:
        ep, pp = _safe(Path("schema/envelope/index.json")), _safe(Path("schema/profiles/index.json"))
        if ep is None or pp is None or not ep.is_file() or not pp.is_file(): return None
        envelope = json.loads(ep.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs)
        profiles = json.loads(pp.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs)
        if set(envelope) != {"name", "versions"} or envelope.get("name") != "quantskills-envelope" or not isinstance(envelope["versions"], dict): return None
        majors = set()
        for version, filename in envelope["versions"].items():
            if parse_semver(version)[0] < 0 or filename != f"{version}.schema.json" or _safe(Path("schema/envelope") / filename) is None: return None
            majors.add((envelope["name"], parse_semver(version)[0]))
        if not isinstance(profiles, dict) or set(profiles) != {"profiles"} or not isinstance(profiles["profiles"], list): return None
        known = set()
        for row in profiles["profiles"]:
            if not isinstance(row, dict) or not _ID.fullmatch(row.get("id", "")) or not isinstance(row.get("version"), str) or parse_semver(row["version"]) is None or row.get("kind") not in {"base", "result"}: return None
            path = Path(row.get("schema", "")); expected = Path(row["kind"]) / row["id"] / f"{row['version']}.schema.json"
            if path != expected or _safe(Path("schema/profiles") / path) is None or (row["id"], row["version"]) in known: return None
            known.add((row["id"], row["version"]))
        return known, majors
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError): return None


def _result(status: str, errors: list[dict] | None = None, adapter_path: list[str] | None = None) -> dict:
    unique = {(item.get("code"), item.get("path")) for item in errors or [] if isinstance(item, dict) and set(item) == {"code", "path"}}
    return {"status": status, "errors": [{"code": code, "path": path} for code, path in sorted(unique)], "adapter_path": adapter_path or []}


def _endpoint(value: object, input_: bool, known: set[tuple[str, str]], envelope_majors: set[tuple[str, int]]) -> tuple[tuple[str, str, int] | None, str | None]:
    if not isinstance(value, dict): return None, "endpoint"
    if value.get("mode") in {"natural-language", "not-applicable"}: return None, "not-applicable"
    envelope = value.get("envelope")
    if value.get("mode") not in {"structured", "hybrid"} or not isinstance(envelope, dict) or set(envelope) != {"name", "version"}: return None, "endpoint"
    try: major = parse_semver(envelope["version"])[0]
    except (KeyError, ValueError): return None, "envelope"
    if (envelope.get("name"), major) not in envelope_majors: return None, "envelope"
    profile, version = value.get("profile"), value.get("version_range" if input_ else "version")
    if not isinstance(profile, str) or _ID.fullmatch(profile) is None: return None, "profile"
    if input_:
        if _parse_range(version) is None or not any(item[0] == profile for item in known): return None, "range"
    else:
        if (profile, version) not in known: return None, "profile"
    return (profile, version, major), None


def _validate_adapters(adapters: object, known: set[tuple[str, str]]) -> list[tuple[dict | None, dict | None]]:
    if not isinstance(adapters, list): return [(None, {"code": "adapters", "path": "/adapters"})]
    result, ids, edges = [], set(), set()
    for index, row in enumerate(sorted(adapters, key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "")):
        path = f"/adapters/{index}"
        if not isinstance(row, dict) or set(row) != _ROW_KEYS or not _ID.fullmatch(row.get("id", "")) or row["id"] in ids:
            result.append((None, {"code": "adapter", "path": path})); continue
        ids.add(row["id"])
        source, target, impl, evidence = row["source"], row["target"], row["implementation"], row["evidence"]
        edge = (source.get("profile"), source.get("version"), target.get("profile"), target.get("version")) if isinstance(source, dict) and isinstance(target, dict) else None
        complete = edge is not None and edge not in edges and (edge[0], edge[1]) in known and (edge[2], edge[3]) in known and isinstance(impl, dict) and set(impl) == {"repository", "path"} and impl.get("repository") == "registry" and isinstance(impl.get("path"), str) and isinstance(evidence, dict) and set(evidence) == {"fixture_sha256", "test_command", "validated_at"} and re.fullmatch(r"sha256:[0-9a-f]{64}", evidence.get("fixture_sha256", "")) and isinstance(evidence.get("test_command"), str) and bool(evidence["test_command"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", evidence.get("validated_at", "")) and row.get("envelope_major") == 1
        if edge: edges.add(edge)
        implementation = _safe(Path(impl["path"])) if complete else None
        if not complete or implementation is None or not implementation.is_file(): result.append((None, {"code": "adapter", "path": path}))
        elif row.get("lossless") is True and row.get("validation_status") == "validated": result.append((row, None))
        elif row.get("lossless") is False: result.append((None, None))
        else: result.append((None, {"code": "adapter-evidence", "path": path}))
    return result


def compare_endpoints(output: dict, input_: dict, adapters: list[dict]) -> dict:
    indexes = _indexes()
    if indexes is None: return _result("unknown", [{"code": "canonical-index", "path": "/schema"}])
    known, majors = indexes
    out, out_error = _endpoint(output, False, known, majors); inn, in_error = _endpoint(input_, True, known, majors)
    if out_error == "not-applicable" or in_error == "not-applicable": return _result("not-applicable")
    if out_error or in_error: return _result("unknown", [{"code": "endpoint", "path": "/output" if out_error else "/input"}])
    assert out and inn
    start, wanted = out[:2], inn[:2]
    if out[2] != inn[2]: return _result("incompatible")
    rows = _validate_adapters(adapters, known); graph, invalid = {}, {}
    for row, error in rows:
        if row: graph.setdefault((row["source"]["profile"], row["source"]["version"]), []).append(row)
        elif error:
            index = int(error["path"].split("/")[2]) if error["path"].count("/") >= 2 else -1
            ordered = sorted(adapters, key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "") if isinstance(adapters, list) else []
            source = ordered[index].get("source") if 0 <= index < len(ordered) and isinstance(ordered[index], dict) else None
            if isinstance(source, dict): invalid.setdefault((source.get("profile"), source.get("version")), []).append(error)
    queue, visited = [((), start)], set()
    while queue:
        route, node = heappop(queue)
        if node in visited: continue
        visited.add(node)
        if node[0] == wanted[0] and version_satisfies(node[1], wanted[1]): return _result("compatible" if not route else "adapter-required", adapter_path=list(route))
        relevant = invalid.get(node, [])
        if relevant: return _result("unknown", relevant)
        for row in sorted(graph.get(node, []), key=lambda item: item["id"]):
            target = (row["target"]["profile"], row["target"]["version"])
            if target not in visited: heappush(queue, (route + (row["id"],), target))
    return _result("incompatible")


def build_compatibility_edges(assets: list[dict], adapters: list[dict]) -> list[dict]:
    edges = []
    for producer in assets if isinstance(assets, list) else []:
        pi = producer.get("interface") if isinstance(producer, dict) else None
        for consumer in assets if isinstance(assets, list) else []:
            ci = consumer.get("interface") if isinstance(consumer, dict) else None
            if not isinstance(pi, dict) or not isinstance(ci, dict): continue
            for output in pi.get("outputs", []) if isinstance(pi.get("outputs", []), list) else []:
                for input_ in ci.get("inputs", []) if isinstance(ci.get("inputs", []), list) else []:
                    result = compare_endpoints({**output, "mode": pi.get("mode"), "envelope": pi.get("envelope")}, {**input_, "mode": ci.get("mode"), "envelope": ci.get("envelope")}, adapters)
                    if result["status"] in {"compatible", "adapter-required"}: edges.append({"producer": producer.get("name"), "consumer": consumer.get("name"), "output": {"profile": output.get("profile"), "version": output.get("version")}, "input": {"profile": input_.get("profile"), "version_range": input_.get("version_range"), "required": input_.get("required")}, "status": result["status"], "adapter_path": result["adapter_path"]})
    return [json.loads(item) for item in sorted({json.dumps(edge, sort_keys=True, separators=(",", ":")) for edge in edges})]
