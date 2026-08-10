import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from adapters.pandadata import (
    fundamental_pit_envelope,
    futures_contract_envelope,
    market_bar_envelope,
)
from compatibility import compare_endpoints
from validate_contract import validate_contract


FIXTURES = ROOT / "tests" / "fixtures" / "pandadata"


def native_bytes(native):
    return (json.dumps(native, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def endpoint(profile, version="1.0.0", version_range=None):
    result = {"mode": "structured", "envelope": {"name": "quantskills-envelope", "version": "1.0.0"}, "profile": profile}
    result["version_range" if version_range is not None else "version"] = version_range or version
    return result


class PandaDataFidelityTests(unittest.TestCase):
    cases = (
        ("market-bar", market_bar_envelope),
        ("fundamental-pit", fundamental_pit_envelope),
        ("futures-contract", futures_contract_envelope),
    )

    def load(self, name, expected=False):
        suffix = f"expected-{name}-envelope.json" if expected else f"{name}-native.json"
        return json.loads((FIXTURES / suffix).read_text(encoding="utf-8"))

    def test_exact_contract_determinism_and_native_fidelity(self):
        for name, adapter in self.cases:
            with self.subTest(name=name):
                native = self.load(name)
                original = copy.deepcopy(native)
                envelope = adapter(native)
                self.assertEqual(native, original)
                self.assertEqual(envelope, adapter(copy.deepcopy(native)))
                self.assertEqual(envelope, self.load(name, expected=True))
                self.assertEqual(validate_contract(envelope, ROOT)["status"], "valid")
                self.assertEqual(validate_contract(envelope, ROOT)["errors"], [])
                self.assertEqual(envelope["payload"]["native"]["raw_records"], native["records"])
                self.assertEqual(envelope["meta"]["provenance"][0]["raw_sha256"], "sha256:" + hashlib.sha256(native_bytes(native)).hexdigest())
                self.assertEqual(len(envelope["payload"]["records"]), len(native["records"]))
                self.assertEqual(set(envelope["schema"]["primary_key"]), set(envelope["payload"]["records"][0]).intersection(envelope["schema"]["primary_key"]))

    def test_profile_specific_fidelity(self):
        market = market_bar_envelope(self.load("market-bar"))
        self.assertEqual(market["payload"]["records"][0]["timestamp"], "2026-08-10T09:30:00+08:00")
        self.assertEqual(market["payload"]["records"][0]["adjustment"], "none")
        self.assertEqual(market["schema"]["fields"]["volume"]["unit"], "shares")
        self.assertEqual(market["meta"]["calendar"], "SSE")
        fundamental = fundamental_pit_envelope(self.load("fundamental-pit"))
        record = fundamental["payload"]["records"][0]
        self.assertEqual((record["available_at"], record["revision"], record["vintage"]), ("2026-08-10T18:00:00+08:00", "r2", "2026Q2-prelim"))
        futures = futures_contract_envelope(self.load("futures-contract"))
        record = futures["payload"]["records"][0]
        self.assertEqual((record["contract_id"], record["continuous_series_id"], record["roll_rule"]), ("RB2610", "RB88", "volume"))
        self.assertEqual(futures["schema"]["fields"]["open_interest"]["unit"], "contracts")

    def test_malformed_and_nonfinite_values_are_stable_and_value_free(self):
        for _name, adapter in self.cases:
            with self.subTest(adapter=adapter.__name__, malformed=True):
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-object$"):
                    adapter([])
            with self.subTest(adapter=adapter.__name__, nonfinite=True):
                native = self.load(_name)
                native["records"][0]["nested"] = {"bad": math.nan}
                with self.assertRaisesRegex(ValueError, r"^pandadata-nonfinite$"):
                    adapter(native)

    def test_mappings_are_provider_only_and_lossy_is_excluded(self):
        mappings = json.loads((ROOT / "schema" / "adapters" / "pandadata-mappings.v1.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "schema" / "adapters" / "registry.v1.json").read_text(encoding="utf-8"))
        ids = [row["id"] for row in mappings["mappings"]]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(all(row["lossless"] and row["validation_status"] == "validated" for row in mappings["mappings"]))
        self.assertTrue(all(identifier not in json.dumps(registry, sort_keys=True) for identifier in ids + ["pandadata-lossy-example"]))
        self.assertEqual(compare_endpoints(endpoint("market-bar"), endpoint("market-bar", version_range="1.0.0"), registry["adapters"]), {"status": "compatible", "errors": [], "adapter_path": []})
        lossy = {"id": "pandadata-lossy-example", "lossless": False, "validation_status": "rejected"}
        self.assertFalse(lossy["lossless"] and lossy["validation_status"] == "validated")


if __name__ == "__main__":
    unittest.main()
