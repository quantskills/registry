import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from contract_runtime import envelope_semantic_issues

SCHEMA = ROOT / "schema" / "envelope" / "1.0.0.schema.json"
FIXTURES = ROOT / "tests" / "fixtures" / "envelope"


class EnvelopeSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def document(self):
        return json.loads((FIXTURES / "valid-market-bar.json").read_text(encoding="utf-8"))

    def paths(self, document):
        return {tuple(error.absolute_path) for error in self.validator.iter_errors(document)}

    def test_canonical_contract_and_market_bar_fixture(self):
        document = self.document()
        self.assertEqual(self.paths(document), set())
        self.assertEqual(document["$contract"], {"envelope": "quantskills-envelope", "envelope_version": "1.0.0", "profile": "market-bar", "profile_version": "1.0.0"})
        self.assertEqual(document["schema"]["primary_key"], ["instrument_id", "timestamp"])
        self.assertTrue(set(("instrument_id", "timestamp", "open", "high", "low", "close", "volume", "frequency", "adjustment", "calendar")) <= set(document["payload"]["records"][0]))

    def test_old_contract_and_provenance_shapes_are_rejected_at_exact_paths(self):
        document = self.document(); document["$contract"] = {"name": "quantskills-envelope", "version": "1.0.0"}
        self.assertIn(("$contract",), self.paths(document))
        document = self.document(); document["meta"]["provenance"] = {"provider": "x"}
        self.assertIn(("meta", "provenance"), self.paths(document))
        document = self.document(); document["meta"]["provenance"][0].pop("raw_sha256")
        self.assertIn(("meta", "provenance", 0), self.paths(document))

    def test_rich_meta_native_quality_and_units(self):
        document = self.document()
        self.assertEqual(self.paths(document), set())
        self.assertIn("as_of", document["meta"])
        self.assertEqual(document["quality"], {"status": "pass", "checks": [], "warnings": []})
        self.assertNotIn("unit", document["schema"]["fields"]["open"])
        document["schema"]["fields"]["close"]["unit"] = ""
        self.assertIn(("schema", "fields", "close", "unit"), self.paths(document))
        for native in ({"raw_ref": "fixture://x"}, {"raw_records": [{"provider_field": 1}]}):
            document = self.document(); document["payload"]["native"] = native
            self.assertEqual(self.paths(document), set())

    def test_strict_dates_semantics_and_closed_root(self):
        for field in ("generated_at", "as_of"):
            document = self.document(); document["meta"][field] = "2026-99-99T09:30:00Z"
            self.assertIn(f"/meta/{field}", {issue["path"] for issue in envelope_semantic_issues(document)})
        document = self.document(); document["schema"]["primary_key"] = ["missing"]
        self.assertEqual(envelope_semantic_issues(document), [{"code": "envelope-primary-key", "path": "/schema/primary_key/0"}])
        document = self.document(); document["extra"] = True
        self.assertIn((), self.paths(document))

    def test_invalid_fixture_paths_and_index(self):
        for fixture, path in (("missing-contract.json", ()), ("bad-timezone.json", ("meta", "generated_at")), ("short-sha256.json", ("meta", "provenance", 0, "raw_sha256"))):
            with self.subTest(fixture=fixture):
                self.assertIn(path, self.paths(json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))))
        index = json.loads((ROOT / "schema" / "envelope" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["versions"]["1.0.0"], "1.0.0.schema.json")
        self.assertTrue((ROOT / "schema" / "envelope" / index["versions"]["1.0.0"]).is_file())


if __name__ == "__main__":
    unittest.main()
