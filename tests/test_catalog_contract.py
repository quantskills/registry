import copy
import json
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from catalog_contract import (canonical_json, github_description, load_taxonomy,
                              validate_asset_semantics, validate_frontmatter_schema)


class CatalogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = load_taxonomy(ROOT)
        cls.schema = ROOT / "schema" / "frontmatter.schema.json"
        cls.valid = yaml.safe_load((ROOT / "tests" / "fixtures" / "declarations" / "valid-structured.yml").read_text(encoding="utf-8"))

    def test_canonical_json_and_description_are_exact(self):
        self.assertEqual(canonical_json({"b": "中", "a": 1}), b'{"a":1,"b":"\xe4\xb8\xad"}')
        self.assertEqual(github_description(self.valid), self.valid["quantSkills"]["summary_zh"] + "｜" + self.valid["quantSkills"]["summary_en"])

    def test_schema_errors_are_deterministic_and_structured(self):
        issues = validate_frontmatter_schema({}, self.schema)
        self.assertTrue(issues)
        self.assertEqual(issues, sorted(issues, key=lambda item: (item["path"], item["detail"])))
        self.assertTrue(all(set(("level", "check", "path", "detail")) <= set(issue) for issue in issues))

    def test_semantics_detect_cross_field_and_language_errors(self):
        frontmatter = copy.deepcopy(self.valid)
        qs = frontmatter["quantSkills"]
        qs["catalog"]["subcategory"] = "03.a-share-equity"
        qs["workflow"]["primary_stage"] = "execution"
        qs["repository_url"] = "https://example.invalid/x"
        qs["summary_en"] = "QuantSkills factor Skill repository"
        qs["interface"]["envelope"]["version"] = "2.0.0"
        details = [issue["detail"] for issue in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)]
        self.assertTrue(any("subcategory" in detail for detail in details))
        self.assertTrue(any("primary_stage" in detail for detail in details))
        self.assertTrue(any("canonical" in detail for detail in details))
        self.assertTrue(any("generic" in detail for detail in details))
        self.assertTrue(any("major version 1" in detail for detail in details))

    def test_malformed_envelope_version_is_a_semantic_issue(self):
        frontmatter = copy.deepcopy(self.valid)
        frontmatter["quantSkills"]["interface"]["envelope"]["version"] = "1.invalid"
        details = [issue["detail"] for issue in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)]
        self.assertTrue(any("major version 1" in detail for detail in details))

    def test_missing_classification_never_falls_back(self):
        frontmatter = copy.deepcopy(self.valid)
        frontmatter["quantSkills"].pop("catalog")
        issues = validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)
        self.assertIn("待迁移", issues[0]["detail"])

    def test_claims_and_repository_name_restating_are_rejected_but_disclaimers_are_allowed(self):
        frontmatter = copy.deepcopy(self.valid)
        frontmatter["quantSkills"]["summary_en"] = "skill-factor-grouped-wrapper"
        self.assertTrue(validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy))
        for claim in ("保证收益", "稳赚", "无风险", "官方认证", "生产可用", "guaranteed return", "risk-free", "officially certified", "production-ready"):
            with self.subTest(claim=claim):
                frontmatter["quantSkills"]["summary_en"] = f"This product is {claim}."
                self.assertTrue(any("prohibited" in item["detail"] for item in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)))
        for disclaimer in ("不构成投资建议", "Research output, not investment advice, for factor evaluation."):
            with self.subTest(disclaimer=disclaimer):
                frontmatter["quantSkills"]["summary_en"] = disclaimer
                self.assertFalse(any("prohibited" in item["detail"] for item in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)))

    def test_community_claims_are_rejected_but_explicit_negatives_are_allowed(self):
        frontmatter = copy.deepcopy(self.valid)
        prohibited = (
            "official", "certified", "verified", "endorsed", "production-ready",
            "guaranteed returns", "risk-free", "safe strategy", "investment advice",
            "官方", "认证", "已验证", "背书", "生产可用", "保证收益", "稳赚",
            "无风险", "安全策略", "构成投资建议",
        )
        for claim in prohibited:
            with self.subTest(claim=claim):
                frontmatter["quantSkills"]["summary_en"] = f"This product is {claim}."
                self.assertTrue(any("prohibited" in item["detail"] for item in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)))
        for disclaimer in ("not investment advice", "not official", "does not guarantee returns", "并非官方", "不构成投资建议"):
            with self.subTest(disclaimer=disclaimer):
                frontmatter["quantSkills"]["summary_en"] = disclaimer
                self.assertFalse(any("prohibited" in item["detail"] for item in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)))

    def test_2_1_native_license_runtime_and_invocation_semantics(self):
        frontmatter = copy.deepcopy(self.valid)
        frontmatter["quantSkills"]["schema_version"] = "2.1.0"
        frontmatter["license"] = "GPL-3.0-only"
        frontmatter["supported-runtimes"] = list(frontmatter["quantSkills"]["platforms"])
        self.assertFalse(validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy))
        frontmatter["license"] = "MIT"
        self.assertTrue(any("root license" in item["detail"] for item in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)))
        frontmatter["license"] = "GPL-3.0-only"
        frontmatter["supported-runtimes"] = ["codex"]
        frontmatter["user-invocable"] = False
        frontmatter["disable-model-invocation"] = True
        details = [item["detail"] for item in validate_asset_semantics(frontmatter, "skill-factor-grouped-wrapper", "SKILL.md", self.taxonomy)]
        self.assertTrue(any("exactly match" in item for item in details))
        self.assertTrue(any("unreachable" in item for item in details))


if __name__ == "__main__":
    unittest.main()
