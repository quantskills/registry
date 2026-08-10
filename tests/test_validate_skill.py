import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_skill import validate


class ValidateSkillTests(unittest.TestCase):
    DISCLOSURE_TEXT = "Data source. Assumption. Parameter. Limitation. Risk. Research only; not investment advice."

    def make_repo(self, name="skill-example", risk=False, complete=False, declaration_file="SKILL.md"):
        directory = Path(tempfile.mkdtemp()) / name
        directory.mkdir()
        fixture = ROOT / "tests" / "fixtures" / "declarations" / "valid-structured.yml"
        frontmatter = yaml.safe_load(fixture.read_text(encoding="utf-8"))
        frontmatter["name"] = name
        frontmatter["description"] += " Use when validating a catalog-contract fixture."
        frontmatter["quantSkills"]["repository"] = name
        frontmatter["quantSkills"]["repository_url"] = f"https://github.com/quantskills/{name}"
        frontmatter["quantSkills"]["project_type"] = "agent" if declaration_file == "AGENTS.md" else "skill"
        if not risk:
            frontmatter["quantSkills"]["workflow"]["workflow_stages"] = ["reporting"]
            frontmatter["quantSkills"]["workflow"]["primary_stage"] = "reporting"
            frontmatter["quantSkills"]["tags"] = ["reporting"]
            frontmatter["quantSkills"]["catalog"] = {"category": "10", "subcategory": "10.skill-template"}
        text = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\nBody\n"
        (directory / declaration_file).write_text(text, encoding="utf-8")
        (directory / "README.md").write_text("Use when validating examples. " * 4, encoding="utf-8")
        (directory / "LICENSE").write_text("GPL", encoding="utf-8")
        if complete:
            (directory / "README.md").write_text(self.DISCLOSURE_TEXT, encoding="utf-8")
            (directory / declaration_file).write_text(text + self.DISCLOSURE_TEXT, encoding="utf-8")
        self.addCleanup(shutil.rmtree, directory.parent)
        return directory

    def rewrite_frontmatter(self, repo, mutate):
        frontmatter = yaml.safe_load((repo / "SKILL.md").read_text(encoding="utf-8").split("---\n", 2)[1])
        mutate(frontmatter)
        (repo / "SKILL.md").write_text("---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\nBody\n", encoding="utf-8")

    def test_audit_vs_enforce_and_non_triggered_template(self):
        repo = self.make_repo()
        frontmatter = (repo / "SKILL.md").read_text(encoding="utf-8").replace("summary_en: Structured workflow for factor screening and evaluation.", "summary_en: QuantSkills factor Skill repository")
        (repo / "SKILL.md").write_text(frontmatter, encoding="utf-8")
        self.assertEqual(validate(repo, set(), "audit").health, "warning")
        self.assertEqual(validate(repo, set(), "enforce").health, "quarantined")
        self.assertFalse(any(item["check"] == "quant-risk-disclosures" for item in validate(repo, set()).items))

    def test_risk_documentation_is_mode_sensitive(self):
        incomplete = self.make_repo("skill-risk-incomplete", risk=True)
        self.assertTrue(any(item["check"] == "quant-risk-disclosures" and item["level"] == "warn" for item in validate(incomplete, set(), "audit").items))
        self.assertTrue(any(item["check"] == "quant-risk-disclosures" and item["level"] == "fail" for item in validate(incomplete, set(), "enforce").items))
        complete = self.make_repo("skill-risk-complete", risk=True, complete=True)
        self.assertFalse(any(item["check"] == "quant-risk-disclosures" for item in validate(complete, set(), "enforce").items))

    def test_factor_evaluation_tag_triggers_separate_readme_and_root_disclosures(self):
        readme_complete = self.make_repo("skill-factor-readme-complete")
        self.rewrite_frontmatter(readme_complete, lambda frontmatter: frontmatter["quantSkills"].update({"tags": ["factor-evaluation"]}))
        (readme_complete / "README.md").write_text(self.DISCLOSURE_TEXT, encoding="utf-8")
        readme_items = validate(readme_complete, set(), "enforce").items
        self.assertTrue(any(item["check"] == "quant-risk-disclosures" and "SKILL.md" in item["detail"] for item in readme_items))

        root_complete = self.make_repo("skill-factor-root-complete")
        self.rewrite_frontmatter(root_complete, lambda frontmatter: frontmatter["quantSkills"].update({"tags": ["factor-evaluation"]}))
        (root_complete / "SKILL.md").write_text((root_complete / "SKILL.md").read_text(encoding="utf-8") + self.DISCLOSURE_TEXT, encoding="utf-8")
        root_items = validate(root_complete, set(), "enforce").items
        self.assertTrue(any(item["check"] == "quant-risk-disclosures" and "README.md" in item["detail"] for item in root_items))

    def test_existing_check_families_remain_available(self):
        repo = self.make_repo(risk=True)
        self.rewrite_frontmatter(repo, lambda frontmatter: frontmatter.update({"description": "short"}))
        (repo / "LICENSE").unlink()
        (repo / "broken.py").write_text("def nope(:\n", encoding="utf-8")
        (repo / "README.md").write_text("[missing](missing.md)\nAKIA1234567890ABCDEF", encoding="utf-8")
        (repo / "oversized.json").write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        checks = {item["check"] for item in validate(repo, {"other"}).items}
        self.assertTrue({"required-files", "frontmatter", "path-refs", "git-hygiene", "secrets", "quant-risk-disclosures", "python-syntax", "requires"} <= checks)

    def test_cli_relative_dot_path_matches_absolute_repository_path(self):
        script = ROOT / "scripts" / "validate_skill.py"
        for repo in (self.make_repo("skill-relative-dot"), self.make_repo("agent-relative-dot", declaration_file="AGENTS.md")):
            with self.subTest(repo=repo.name):
                relative = subprocess.run(
                    [sys.executable, str(script), ".", "--contract-mode", "enforce"],
                    cwd=repo,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                absolute = subprocess.run(
                    [sys.executable, str(script), str(repo), "--contract-mode", "enforce"],
                    cwd=repo,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(relative.returncode, 0, relative.stdout + relative.stderr)
                self.assertEqual(absolute.returncode, 0, absolute.stdout + absolute.stderr)
                self.assertEqual(relative.stdout.splitlines()[0], "health: healthy")
                self.assertEqual(absolute.stdout.splitlines()[0], "health: healthy")


if __name__ == "__main__":
    unittest.main()
