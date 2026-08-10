import json
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from jsonschema import Draft202012Validator
from contract_runtime import envelope_semantic_issues
SCHEMA = ROOT / "schema" / "envelope" / "1.0.0.schema.json"
FIXTURES = ROOT / "tests" / "fixtures" / "envelope"


class EnvelopeSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def errors(self, name):
        return list(self.validator.iter_errors(json.loads((FIXTURES / name).read_text(encoding="utf-8"))))

    def document(self):
        return json.loads((FIXTURES / "valid-market-bar.json").read_text(encoding="utf-8"))

    def test_valid_market_bar(self):
        self.assertEqual(self.errors("valid-market-bar.json"), [])

    def test_invalid_fixtures_report_exact_paths(self):
        for fixture, path in (("missing-contract.json", ()), ("bad-timezone.json", ("meta", "generated_at")), ("short-sha256.json", ("meta", "provenance", "digest"))):
            with self.subTest(fixture=fixture):
                self.assertIn(path, {tuple(error.absolute_path) for error in self.errors(fixture)})

    def test_root_is_closed_and_semantics_reject_primary_key_and_strict_datetimes(self):
        document = self.document(); document["extra"] = True
        self.assertIn((), {tuple(error.absolute_path) for error in self.validator.iter_errors(document)})
        for value in ("not-a-dateZ", "2026-99-99T99:99:99Z", "2026-08-10T09:30:00+99:99"):
            with self.subTest(value=value):
                document = self.document(); document["meta"]["generated_at"] = value
                self.assertIn("/meta/generated_at", {issue["path"] for issue in envelope_semantic_issues(document)})
        document = self.document(); document["schema"]["primary_key"] = ["missing"]
        self.assertIn("/schema/primary_key/0", {issue["path"] for issue in envelope_semantic_issues(document)})

    def test_schema_mutation_matrix_and_open_records(self):
        cases = [
            ("$contract", "name", "wrong", ("$contract", "name")), ("$contract", "version", "2.0.0", ("$contract", "version")),
            ("meta", "provenance", {"provider": "p"}, ("meta", "provenance")), ("payload", "native", {}, ("payload", "native")),
            ("schema", "numeric", True, ("schema", "fields", "close")), ("quality", "status", "bad", ("quality", "status")),
        ]
        for group, field, value, path in cases:
            with self.subTest(group=group, field=field):
                document = self.document()
                if group == "$contract": document["$contract"][field] = value
                elif group == "meta": document["meta"][field] = value
                elif group == "payload": document["payload"][field] = value
                elif group == "schema": document["schema"]["fields"]["close"] = {"type": "number"}
                else: document["quality"][field] = value
                self.assertIn(path, {tuple(error.absolute_path) for error in self.validator.iter_errors(document)})
        document = self.document(); document["payload"]["records"][0]["profile_specific"] = {"open": True}
        self.assertEqual(list(self.validator.iter_errors(document)), [])


if __name__ == "__main__":
    unittest.main()
