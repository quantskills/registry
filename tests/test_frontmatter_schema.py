import json
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from jsonschema import Draft202012Validator
from scripts.catalog_contract import validate_frontmatter_schema


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

    def assert_invalid_at(self, fixture, path, validator=None, message=None):
        errors = list(self.validator.iter_errors(load_yaml(fixture)))
        leaves = [error for error in errors for error in leaf_errors(error)]
        paths = {tuple(error.absolute_path) for error in leaves}
        self.assertTrue(errors, "fixture unexpectedly passed schema validation")
        self.assertIn(path, paths, [error.message for error in leaves])
        matching_errors = [error for error in leaves if tuple(error.absolute_path) == path]
        if validator:
            self.assertIn(validator, [error.validator for error in matching_errors])
        if message:
            self.assertIn(message, [error.message for error in leaves])

    def test_valid_structured_declaration(self):
        self.assert_valid("valid-structured.yml")

    def test_valid_not_applicable_declaration(self):
        self.assert_valid("valid-not-applicable.yml")

    def test_invalid_subcategory_syntax(self):
        self.assert_invalid_at(
            "invalid-subcategory.yml",
            ("quantSkills", "catalog", "subcategory"),
            validator="pattern",
        )

    def test_invalid_primary_stage_value(self):
        self.assert_invalid_at(
            "invalid-primary-stage.yml",
            ("quantSkills", "workflow", "primary_stage"),
            validator="enum",
        )

    def test_invalid_interface_branch(self):
        self.assert_invalid_at(
            "invalid-interface.yml",
            ("quantSkills", "interface"),
            validator="required",
            message="'adapters' is a required property",
        )

    def test_invalid_summary_format(self):
        self.assert_invalid_at(
            "invalid-summary.yml",
            ("quantSkills", "summary_zh"),
            validator="pattern",
        )

    def test_structured_producer_or_consumer_is_valid_but_empty_both_sides_is_not(self):
        source = load_yaml("valid-structured.yml")
        for field in ("inputs", "outputs"):
            with self.subTest(empty=field):
                declaration = copy.deepcopy(source)
                declaration["quantSkills"]["interface"][field] = []
                self.assertEqual(list(self.validator.iter_errors(declaration)), [])
        declaration = copy.deepcopy(source)
        declaration["quantSkills"]["interface"]["inputs"] = []
        declaration["quantSkills"]["interface"]["outputs"] = []
        self.assertTrue(list(self.validator.iter_errors(declaration)))

    def test_2_1_skill_native_permissions_are_closed_and_2_0_rejects_2_1(self):
        declaration = load_yaml("valid-structured.yml")
        declaration["quantSkills"]["schema_version"] = "2.1.0"
        declaration["license"] = "GPL-3.0-only"
        declaration["allowed-tools"] = ["Bash", "Read", "Write", "WebSearch", "WebFetch"]
        declaration["user-invocable"] = True
        self.assertEqual(list(self.validator.iter_errors(declaration)), [])
        old = Draft202012Validator(json.loads((ROOT / "schema" / "frontmatter.v2.0.schema.json").read_text(encoding="utf-8")))
        self.assertTrue(list(old.iter_errors(declaration)))

    def test_2_1_rejects_unknown_root_and_agent_permission_keys(self):
        declaration = load_yaml("valid-not-applicable.yml")
        declaration["quantSkills"]["schema_version"] = "2.1.0"
        declaration["unknown"] = True
        self.assertTrue(list(self.validator.iter_errors(declaration)))
        declaration.pop("unknown")
        declaration["quantSkills"]["project_type"] = "agent"
        declaration["allowed-tools"] = ["Read"]
        self.assertTrue(list(self.validator.iter_errors(declaration)))

    def test_2_0_rejects_every_2_1_only_root_field_through_public_validator(self):
        values = {
            "license": "GPL-3.0-only", "allowed-tools": ["Read"], "user-invocable": True,
            "disable-model-invocation": False, "supported-runtimes": ["codex"],
            "compatibility": "Python 3.10+", "version": "1.0.0", "author": "PandaAI",
            "metadata": {"organization": "QuantSkills"},
        }
        for field, value in values.items():
            with self.subTest(field=field):
                declaration = load_yaml("valid-structured.yml")
                declaration[field] = value
                self.assertTrue(validate_frontmatter_schema(declaration, SCHEMA_PATH))
        self.assertFalse(validate_frontmatter_schema(load_yaml("valid-structured.yml"), SCHEMA_PATH))
        declaration = load_yaml("valid-structured.yml")
        declaration["quantSkills"]["schema_version"] = "2.1.0"
        declaration.update(values)
        declaration["supported-runtimes"] = declaration["quantSkills"]["platforms"]
        self.assertFalse(validate_frontmatter_schema(declaration, SCHEMA_PATH))

    def test_version_validation_never_uses_external_schema_resolution(self):
        declaration = load_yaml("valid-structured.yml")
        declaration["quantSkills"]["schema_version"] = "2.1.0"
        with patch("urllib.request.urlopen", side_effect=AssertionError("external schema resolution")):
            self.assertFalse(validate_frontmatter_schema(declaration, SCHEMA_PATH))


if __name__ == "__main__":
    unittest.main()
