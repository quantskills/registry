import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schema" / "envelope" / "1.0.0.schema.json"
FIXTURES = ROOT / "tests" / "fixtures" / "envelope"


class EnvelopeSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def errors(self, name):
        return list(self.validator.iter_errors(json.loads((FIXTURES / name).read_text(encoding="utf-8"))))

    def test_valid_market_bar(self):
        self.assertEqual(self.errors("valid-market-bar.json"), [])

    def test_invalid_fixtures_report_exact_paths(self):
        for fixture, path in (("missing-contract.json", ()), ("bad-timezone.json", ("meta", "generated_at")), ("short-sha256.json", ("meta", "provenance", "digest"))):
            with self.subTest(fixture=fixture):
                self.assertIn(path, {tuple(error.absolute_path) for error in self.errors(fixture)})


if __name__ == "__main__":
    unittest.main()
