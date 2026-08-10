import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schema" / "frontmatter.schema.json"
FIXTURES = ROOT / "tests" / "fixtures" / "declarations"


def load_yaml(name):
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def leaf_errors(error):
    if not error.context:
        return [error]
    leaves = []
    for child in error.context:
        leaves.extend(leaf_errors(child))
    return leaves


class FrontmatterSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SCHEMA_PATH.open(encoding="utf-8") as handle:
            cls.validator = Draft202012Validator(json.load(handle))

    def assert_valid(self, fixture):
        errors = list(self.validator.iter_errors(load_yaml(fixture)))
        self.assertEqual(errors, [], [error.message for error in errors])

    def assert_invalid_at(self, fixture, path, message=None):
        errors = list(self.validator.iter_errors(load_yaml(fixture)))
        leaves = [error for error in errors for error in leaf_errors(error)]
        paths = {tuple(error.absolute_path) for error in leaves}
        self.assertTrue(errors, "fixture unexpectedly passed schema validation")
        self.assertIn(path, paths, [error.message for error in leaves])
        if message:
            self.assertIn(message, [error.message for error in leaves])

    def test_valid_structured_declaration(self):
        self.assert_valid("valid-structured.yml")

    def test_valid_not_applicable_declaration(self):
        self.assert_valid("valid-not-applicable.yml")

    def test_invalid_subcategory_syntax(self):
        self.assert_invalid_at(
            "invalid-subcategory.yml", ("quantSkills", "catalog", "subcategory")
        )

    def test_invalid_primary_stage_value(self):
        self.assert_invalid_at(
            "invalid-primary-stage.yml", ("quantSkills", "workflow", "primary_stage")
        )

    def test_invalid_interface_branch(self):
        self.assert_invalid_at(
            "invalid-interface.yml",
            ("quantSkills", "interface"),
            "'adapters' is a required property",
        )

    def test_invalid_summary_format(self):
        self.assert_invalid_at("invalid-summary.yml", ("quantSkills", "summary_zh"))


if __name__ == "__main__":
    unittest.main()
