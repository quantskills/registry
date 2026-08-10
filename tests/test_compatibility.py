import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compatibility import build_compatibility_edges, compare_endpoints, parse_semver, version_satisfies


def endpoint(profile, version=None, version_range=None, major=1, mode="structured"):
    result = {"mode": mode, "envelope": {"name": "quantskills-envelope", "version": f"{major}.0.0"}, "profile": profile}
    if version is not None:
        result["version"] = version
    if version_range is not None:
        result["version_range"] = version_range
    return result


def adapter(identifier, source, target, **changes):
    value = {"id": identifier, "source": {"profile": source, "version": "1.0.0"}, "target": {"profile": target, "version": "1.0.0"}, "implementation": {"repository": "registry", "path": "scripts/compatibility.py"}, "lossless": True, "validation_status": "validated", "evidence": {"fixture_sha256": "sha256:" + "0" * 64, "test_command": "python -m unittest", "validated_at": "2026-08-10"}, "envelope_major": 1}
    value.update(changes)
    return value


class CompatibilityTests(unittest.TestCase):
    def test_strict_semver_and_ranges(self):
        matrix = json.loads((ROOT / "tests/fixtures/compatibility/matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))
        for value in (1, "1.2", "01.2.3", "1.2.3 ", "v1.2.3", "1.2.3-beta"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): parse_semver(value)
        for value in matrix["accepted_ranges"]:
            self.assertTrue(version_satisfies("1.0.0", value))
        for value in ("", "1.0", "1.0.0, <2.0.0", "=1.0.0", *matrix["rejected_ranges"]):
            self.assertFalse(version_satisfies("1.2.3", value))

    def test_status_matrix_and_value_free_errors(self):
        cases = (
            (endpoint("market-bar", "1.0.0"), endpoint("market-bar", version_range=">=1.0.0 <2.0.0"), [], "compatible", []),
            (endpoint("market-bar", "1.0.0"), endpoint("market-bar", version_range=">1.0.0"), [], "incompatible", []),
            (endpoint("market-bar", "1.0.0"), endpoint("factor-panel", version_range="1.0.0"), [adapter("market-factor", "market-bar", "factor-panel")], "adapter-required", ["market-factor"]),
            (endpoint("market-bar", "1.0.0"), endpoint("factor-panel", version_range="1.0.0"), [adapter("pending", "market-bar", "factor-panel", validation_status="pending")], "unknown", []),
            (endpoint("market-bar", "1.0.0"), endpoint("factor-panel", version_range="1.0.0"), [adapter("lossy", "market-bar", "factor-panel", lossless=False)], "incompatible", []),
            (endpoint("market-bar", "1.0.0", major=1), endpoint("market-bar", version_range="1.0.0", major=2), [], "unknown", []),
            (endpoint("missing", "1.0.0"), endpoint("market-bar", version_range="1.0.0"), [], "unknown", []),
            (endpoint("market-bar", "1.0.0", mode="natural-language"), endpoint("market-bar", version_range="1.0.0"), [], "not-applicable", []),
        )
        for output, input_, adapters, status, path in cases:
            with self.subTest(status=status):
                result = compare_endpoints(output, input_, adapters)
                self.assertEqual(set(result), {"status", "errors", "adapter_path"})
                self.assertEqual(result["status"], status)
                self.assertEqual(result["adapter_path"], path)
                if result["errors"]:
                    self.assertTrue(all(set(item) == {"code", "path"} for item in result["errors"]))

    def test_cycle_and_deterministic_edges(self):
        adapters = [adapter("z-back", "factor-panel", "market-bar"), adapter("a-forward", "market-bar", "factor-panel")]
        result = compare_endpoints(endpoint("market-bar", "1.0.0"), endpoint("factor-panel", version_range="1.0.0"), adapters)
        self.assertEqual(result["adapter_path"], ["a-forward"])
        assets = [{"name": "producer", "interface": {"mode": "structured", "envelope": {"name": "quantskills-envelope", "version": "1.0.0"}, "outputs": [{"profile": "market-bar", "version": "1.0.0"}]}}, {"name": "consumer", "interface": {"mode": "hybrid", "envelope": {"name": "quantskills-envelope", "version": "1.0.0"}, "inputs": [{"profile": "factor-panel", "version_range": "1.0.0", "required": True}]}}]
        edges = build_compatibility_edges(list(reversed(assets)), list(reversed(adapters)))
        self.assertEqual(edges, [{"adapter_path": ["a-forward"], "consumer": "consumer", "input": {"profile": "factor-panel", "required": True, "version_range": "1.0.0"}, "producer": "producer", "output": {"profile": "market-bar", "version": "1.0.0"}, "status": "adapter-required"}])


if __name__ == "__main__":
    unittest.main()
