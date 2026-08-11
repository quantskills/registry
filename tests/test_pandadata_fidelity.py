import copy
import hashlib
import json
import math
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from adapters.pandadata import (
    _admit_pandadata_mappings,
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
                self.assertEqual(envelope["payload"]["native"]["raw_records"], [native])
                self.assertIsNot(envelope["payload"]["native"]["raw_records"][0], native)
                self.assertIsNot(envelope["payload"]["native"]["raw_records"][0]["records"], native["records"])
                fixture_bytes = (FIXTURES / f"{name}-native.json").read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(envelope["meta"]["provenance"][0]["raw_sha256"], "sha256:" + hashlib.sha256(fixture_bytes).hexdigest())
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

    def test_recursive_native_containers_fail_with_stable_json_error(self):
        for name, adapter in self.cases:
            with self.subTest(name=name, kind="dict"):
                native = self.load(name)
                native["cycle"] = native
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-json$"):
                    adapter(native)
            with self.subTest(name=name, kind="list"):
                native = self.load(name)
                cycle = []
                cycle.append(cycle)
                native["cycle"] = cycle
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-json$"):
                    adapter(native)

    def test_preflight_rejects_non_json_and_invalid_profile_values(self):
        for name, adapter in self.cases:
            with self.subTest(name=name, kind="tuple"):
                native = self.load(name)
                native["records"] = tuple(native["records"])
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-json$"):
                    adapter(native)
            with self.subTest(name=name, kind="huge-integer"):
                native = self.load(name)
                native["unknown"] = 2 ** 60
                with self.assertRaisesRegex(ValueError, r"^pandadata-integer-range$"):
                    adapter(native)
            with self.subTest(name=name, kind="generated-at"):
                native = self.load(name)
                native["generated_at"] += "\n"
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-shape$"):
                    adapter(native)
            with self.subTest(name=name, kind="missing"):
                native = self.load(name)
                native["records"][0].pop(next(iter(native["records"][0])))
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-shape$"):
                    adapter(native)
            with self.subTest(name=name, kind="boolean"):
                native = self.load(name)
                native["records"][0]["value" if name == "fundamental-pit" else "volume" if name == "market-bar" else "settlement"] = True
                with self.assertRaisesRegex(ValueError, r"^pandadata-native-shape$"):
                    adapter(native)

    def test_market_rejects_mixed_or_missing_volume_units(self):
        native = self.load("market-bar")
        native["records"].append(copy.deepcopy(native["records"][0]))
        native["records"][1]["source_timestamp"] = "2026-08-10T09:31:00+08:00"
        native["records"][1]["volume_unit"] = "lots"
        with self.assertRaisesRegex(ValueError, r"^pandadata-volume-unit$"):
            market_bar_envelope(native)
        native["records"][1].pop("volume_unit")
        with self.assertRaisesRegex(ValueError, r"^pandadata-native-shape$"):
            market_bar_envelope(native)

    def test_mappings_are_provider_only_and_lossy_is_excluded(self):
        mappings = json.loads((ROOT / "schema" / "adapters" / "pandadata-mappings.v1.json").read_text(encoding="utf-8"))
        registry = json.loads((ROOT / "schema" / "adapters" / "registry.v1.json").read_text(encoding="utf-8"))
        ids = [row["id"] for row in mappings["mappings"]]
        self.assertEqual(ids, sorted(ids))
        from adapters.pandadata import _admit_pandadata_mappings
        self.assertTrue(_admit_pandadata_mappings(mappings, ROOT))
        self.assertTrue(all(identifier not in json.dumps(registry, sort_keys=True) for identifier in ids + ["pandadata-lossy-example"]))
        self.assertEqual(compare_endpoints(endpoint("market-bar"), endpoint("market-bar", version_range="1.0.0"), registry["adapters"]), {"status": "compatible", "errors": [], "adapter_path": []})
        lossy = {"id": "pandadata-lossy-example", "lossless": False, "validation_status": "rejected"}
        self.assertFalse(lossy["lossless"] and lossy["validation_status"] == "validated")
        for mutate in (
            lambda document: document["mappings"][0].update({"lossless": False}),
            lambda document: document["mappings"][0]["evidence"].update({"raw_sha256": "sha256:" + "0" * 64}),
            lambda document: document["mappings"][0]["implementation"].update({"callable": "missing"}),
            lambda document: document["mappings"][0].update({"unknown": True}),
        ):
            candidate = copy.deepcopy(mappings)
            mutate(candidate)
            self.assertFalse(_admit_pandadata_mappings(candidate, ROOT))

    def test_mapping_admission_accepts_crlf_equivalent_but_rejects_content_tamper(self):
        mappings = json.loads((ROOT / "schema" / "adapters" / "pandadata-mappings.v1.json").read_text(encoding="utf-8"))
        fixture = (FIXTURES / "market-bar-native.json").resolve()
        canonical_bytes = fixture.read_bytes().replace(b"\r\n", b"\n")
        crlf_bytes = canonical_bytes.replace(b"\n", b"\r\n")
        original_read_bytes = Path.read_bytes

        def read_bytes(path, *args, **kwargs):
            return crlf_bytes if Path(path).resolve() == fixture else original_read_bytes(path, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", read_bytes):
            self.assertTrue(_admit_pandadata_mappings(mappings, ROOT))

        tampered = json.loads(canonical_bytes.decode("utf-8"))
        tampered["records"][0]["close"] += 0.01
        tampered_bytes = (json.dumps(tampered, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        tampered_crlf = tampered_bytes.replace(b"\n", b"\r\n")

        def read_tampered_bytes(path, *args, **kwargs):
            return tampered_crlf if Path(path).resolve() == fixture else original_read_bytes(path, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", read_tampered_bytes):
            self.assertFalse(_admit_pandadata_mappings(mappings, ROOT))

    def test_mapping_admission_rejects_closed_world_mutations(self):
        mappings = json.loads((ROOT / "schema" / "adapters" / "pandadata-mappings.v1.json").read_text(encoding="utf-8"))

        def rejected(candidate):
            try:
                accepted = _admit_pandadata_mappings(candidate, ROOT)
            except BaseException as exc:  # admission must be fail-closed, never leak a probe exception
                self.fail(f"mapping admission raised {type(exc).__name__}")
            self.assertFalse(accepted)

        source_dataset = copy.deepcopy(mappings)
        source_dataset["mappings"][0]["source"]["dataset"] = "bars-daily"
        rejected(source_dataset)

        empty_fields = copy.deepcopy(mappings)
        empty_fields["mappings"][0]["fields"] = {}
        rejected(empty_fields)

        fake_field = copy.deepcopy(mappings)
        fake_field["mappings"][0]["fields"] = {"not_a_native_field": "not_a_record_field"}
        rejected(fake_field)

        newline_id = copy.deepcopy(mappings)
        newline_id["mappings"][0]["id"] += "\n"
        rejected(newline_id)

        wrong_callable = copy.deepcopy(mappings)
        wrong_callable["mappings"][0]["implementation"]["callable"] = "market_bar_envelope"
        rejected(wrong_callable)

        fixture = FIXTURES / "market-bar-native.json"
        original_fixture_bytes = fixture.read_bytes()
        native = json.loads(original_fixture_bytes.decode("utf-8"))
        noncanonical_fixture_bytes = (json.dumps(native, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        noncanonical = copy.deepcopy(mappings)
        noncanonical["mappings"][2]["evidence"]["raw_sha256"] = "sha256:" + hashlib.sha256(noncanonical_fixture_bytes).hexdigest()
        original_read_bytes = Path.read_bytes
        original_read_text = Path.read_text

        def read_bytes(path, *args, **kwargs):
            return noncanonical_fixture_bytes if path.name == fixture.name else original_read_bytes(path, *args, **kwargs)

        def read_text(path, *args, **kwargs):
            return noncanonical_fixture_bytes.decode("utf-8") if path.name == fixture.name else original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", read_bytes), mock.patch.object(Path, "read_text", read_text):
            rejected(noncanonical)

        expected_path = FIXTURES / "expected-market-bar-envelope.json"
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        bad_expected = copy.deepcopy(expected)
        bad_expected["meta"]["provenance"][0]["dataset"] = "wrong-dataset"
        bad_expected_bytes = (json.dumps(bad_expected, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        bad_provenance = copy.deepcopy(mappings)
        import scripts.adapters.pandadata as module

        def fake_adapter(_native):
            return copy.deepcopy(bad_expected)

        fake_adapter.__name__ = "market_bar_envelope"
        fake_adapter.__module__ = "scripts.adapters.pandadata"
        original_module_callable = module.market_bar_envelope

        def read_bad_bytes(path, *args, **kwargs):
            return bad_expected_bytes if path.name == expected_path.name else original_read_bytes(path, *args, **kwargs)

        def read_bad_text(path, *args, **kwargs):
            return bad_expected_bytes.decode("utf-8") if path.name == expected_path.name else original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", read_bad_bytes), mock.patch.object(Path, "read_text", read_bad_text), mock.patch.object(module, "market_bar_envelope", fake_adapter):
            rejected(bad_provenance)
        self.assertIs(module.market_bar_envelope, original_module_callable)


if __name__ == "__main__":
    unittest.main()
