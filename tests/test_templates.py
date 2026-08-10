import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from catalog_contract import load_taxonomy, validate_asset_semantics, validate_frontmatter_schema
from validate_skill import validate


class CanonicalTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = Path(os.environ.get("QS_SKILL_TEMPLATE_PATH", ROOT.parent / "skill-template"))
        cls.agent = Path(os.environ.get("QS_AGENT_TEMPLATE_PATH", ROOT.parent / "agent-template"))
        cls.taxonomy = load_taxonomy(ROOT)
        cls.schema = ROOT / "schema" / "frontmatter.schema.json"

    def frontmatter(self, path):
        return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])

    def assert_healthy(self, repo):
        report = validate(repo, set(), contract_mode="enforce")
        self.assertEqual(report.health, "healthy", report.items)

    def assert_example_valid(self, repo, name, declaration):
        example = yaml.safe_load((repo / "references" / "declaration-example.yml").read_text(encoding="utf-8"))
        self.assertEqual(example["name"], name)
        self.assertFalse(validate_frontmatter_schema(example, self.schema))
        self.assertFalse(validate_asset_semantics(example, name, declaration, self.taxonomy))

    def test_roots_are_enforced_contract_projects_not_examples(self):
        self.assert_healthy(self.skill)
        self.assert_healthy(self.agent)
        skill = self.frontmatter(self.skill / "SKILL.md")["quantSkills"]
        agent = self.frontmatter(self.agent / "AGENTS.md")["quantSkills"]
        self.assertEqual((skill["repository"], skill["catalog"], skill["interface"]),
                         ("skill-template", {"category": "10", "subcategory": "10.skill-template"},
                          {"mode": "not-applicable", "reason": "orchestration-only"}))
        self.assertEqual((agent["repository"], agent["catalog"], agent["interface"]),
                         ("agent-template", {"category": "10", "subcategory": "10.agent-template"},
                          {"mode": "not-applicable", "reason": "orchestration-only"}))

    def test_runtime_adapters_are_thin_pointers_to_canonical_roots(self):
        expected = {
            self.skill: {"SKILL.md": "#", "agents/cursor-rule.mdc": "SKILL.md", "agents/portable-loader.md": "SKILL.md", "agents/openai.yaml": "SKILL.md"},
            self.agent: {"AGENTS.md": "#", "CLAUDE.md": "AGENTS.md", ".cursor/rules/quantskills-agent.mdc": "AGENTS.md", "agents/portable-loader.md": "AGENTS.md", "agents/openai.yaml": "AGENTS.md"},
        }
        for repo, adapters in expected.items():
            for relative, canonical in adapters.items():
                with self.subTest(repo=repo.name, adapter=relative):
                    path = repo / relative
                    self.assertTrue(path.is_file())
                    self.assertIn(canonical, path.read_text(encoding="utf-8"))

    def test_copy_ready_examples_validate_independently(self):
        self.assert_example_valid(self.skill, "skill-example-factor-review", "SKILL.md")
        self.assert_example_valid(self.agent, "agent-example-research-orchestrator", "AGENTS.md")

    def test_skill_qsh_form_is_optional_and_independent_from_contract(self):
        copy = Path(tempfile.mkdtemp()) / "skill-template"
        self.addCleanup(shutil.rmtree, copy.parent)
        shutil.copytree(self.skill, copy)
        skill = copy / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        start = text.index("```json qsh-form")
        end = text.index("```", start + 3) + 3
        skill.write_text(text[:start] + text[end:], encoding="utf-8")
        self.assert_healthy(copy)


if __name__ == "__main__":
    unittest.main()
