import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
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

    def test_ci_workflows_use_sibling_contract_layout_and_compatibility_bridge(self):
        template_workflows = {
            self.skill: self.skill / ".github" / "workflows" / "validate.yml",
            self.agent: self.agent / ".github" / "workflows" / "validate.yml",
        }
        for repo, path in template_workflows.items():
            with self.subTest(repo=repo.name):
                workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
                steps = workflow["jobs"]["validate"]["steps"]
                checkouts = [step for step in steps if step.get("uses") == "actions/checkout@v4"]
                self.assertEqual(checkouts[0]["with"]["path"], repo.name)
                self.assertEqual(checkouts[1]["with"], {"repository": "quantskills/registry", "path": "contract-registry"})
                commands = "\n".join(step.get("run", "") for step in steps)
                self.assertIn("contract-registry/scripts/validate_skill.py", commands)
                self.assertIn(f"{repo.name} --contract-mode enforce", commands)
                self.assertIn("--help", commands)
                self.assertIn("else", commands)
                self.assertIn("requirements-dev.txt", commands)
                self.assertIn("PyYAML", commands)
                self.assertIn("validate-registry-compat.py", commands)
                self.assertNotIn("validate_skill.py .", commands)
                self.assertNotIn(f"{repo.name}/contract-registry", commands)
                if repo == self.skill:
                    self.assertIn(f"validate-qsh-form.mjs {repo.name}/SKILL.md", commands)

        registry = yaml.safe_load((ROOT / ".github" / "workflows" / "validate-registry.yml").read_text(encoding="utf-8"))
        steps = registry["jobs"]["validate"]["steps"]
        checkouts = [step for step in steps if step.get("uses") == "actions/checkout@v4"]
        self.assertEqual(checkouts[1]["with"]["path"], ".contract/skill-template")
        self.assertEqual(checkouts[2]["with"]["path"], ".contract/agent-template")
        test_step = next(step for step in steps if step.get("name") == "Run Python tests")
        self.assertEqual(test_step["env"], {
            "QS_SKILL_TEMPLATE_PATH": "${{ github.workspace }}/.contract/skill-template",
            "QS_AGENT_TEMPLATE_PATH": "${{ github.workspace }}/.contract/agent-template",
        })

    def test_sibling_contract_layout_does_not_scan_dependency_files(self):
        layout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, layout)
        target = layout / "skill-template"
        shutil.copytree(self.skill, target)
        dependency = layout / "contract-registry"
        dependency.mkdir()
        (dependency / "bad.md").write_text("[missing](missing.md)\nAKIA1234567890ABCDEF", encoding="utf-8")
        script = ROOT / "scripts" / "validate_skill.py"
        sibling = subprocess.run([sys.executable, str(script), str(target), "--contract-mode", "enforce"], text=True, capture_output=True, check=False)
        self.assertEqual(sibling.returncode, 0, sibling.stdout + sibling.stderr)
        self.assertEqual(sibling.stdout.splitlines()[0], "health: healthy")

        nested = Path(tempfile.mkdtemp()) / "skill-template"
        self.addCleanup(shutil.rmtree, nested.parent)
        shutil.copytree(self.skill, nested)
        nested_dependency = nested / ".contract" / "registry"
        nested_dependency.mkdir(parents=True)
        (nested_dependency / "bad.md").write_text("[missing](missing.md)\nAKIA1234567890ABCDEF", encoding="utf-8")
        recursive = subprocess.run([sys.executable, str(script), ".", "--contract-mode", "enforce"], cwd=nested, text=True, capture_output=True, check=False)
        self.assertNotEqual(recursive.returncode, 0)
        self.assertIn("secrets", recursive.stdout)

    def test_legacy_base_runner_enforces_v2_facts_and_known_warning_allowlist(self):
        base = "2e766e820250705a65d40e08c8bea9beb187134b"
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", base], capture_output=True, check=True)
        layout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, layout)
        legacy = layout / "contract-registry"
        with zipfile.ZipFile(BytesIO(archive.stdout)) as source:
            source.extractall(legacy)
        self.assertFalse((legacy / "requirements-dev.txt").exists())
        validator = legacy / "scripts" / "validate_skill.py"

        for source, declaration in ((self.skill, "SKILL.md"), (self.agent, "AGENTS.md")):
            with self.subTest(repo=source.name):
                target = layout / source.name
                shutil.copytree(source, target)
                runner = target / "scripts" / "validate-registry-compat.py"
                legacy_result = subprocess.run([sys.executable, str(runner), str(validator), str(target)], text=True, capture_output=True, check=False)
                self.assertEqual(legacy_result.returncode, 0, legacy_result.stdout + legacy_result.stderr)
                current_result = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_skill.py"), str(target), "--contract-mode", "enforce"], text=True, capture_output=True, check=False)
                self.assertEqual(current_result.returncode, 0, current_result.stdout + current_result.stderr)

                frontmatter = self.frontmatter(target / declaration)
                frontmatter["quantSkills"]["schema_version"] = "1.0.0"
                (target / declaration).write_text("---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
                mutated = subprocess.run([sys.executable, str(runner), str(validator), str(target)], text=True, capture_output=True, check=False)
                self.assertNotEqual(mutated.returncode, 0)

                shutil.rmtree(target)
                shutil.copytree(source, target)
                frontmatter = self.frontmatter(target / declaration)
                frontmatter["description"] = "short"
                (target / declaration).write_text("---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
                warned = subprocess.run([sys.executable, str(runner), str(validator), str(target)], text=True, capture_output=True, check=False)
                self.assertNotEqual(warned.returncode, 0)


if __name__ == "__main__":
    unittest.main()
