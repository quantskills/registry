import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_skill import validate


class ValidateSkillTests(unittest.TestCase):
    def make_repo(self, name="skill-example", risk=False, complete=False):
        directory = Path(tempfile.mkdtemp()) / name
        directory.mkdir()
        fixture = ROOT / "tests" / "fixtures" / "declarations" / "valid-structured.yml"
        frontmatter = yaml.safe_load(fixture.read_text(encoding="utf-8"))
        frontmatter["name"] = name
        frontmatter["quantSkills"]["repository"] = name
        frontmatter["quantSkills"]["repository_url"] = f"https://github.com/quantskills/{name}"
        if not risk:
            frontmatter["quantSkills"]["workflow"]["workflow_stages"] = ["reporting"]
            frontmatter["quantSkills"]["workflow"]["primary_stage"] = "reporting"
            frontmatter["quantSkills"]["tags"] = ["reporting"]
        text = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\nBody\n"
        (directory / "SKILL.md").write_text(text, encoding="utf-8")
        (directory / "README.md").write_text("Use when validating examples. " * 4, encoding="utf-8")
        (directory / "LICENSE").write_text("GPL", encoding="utf-8")
        if complete:
            (directory / "README.en.md").write_text("Data source. Assumption. Parameter. Limitation. Risk. Research only; not investment advice.", encoding="utf-8")
        self.addCleanup(shutil.rmtree, directory.parent)
        return directory

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

    def test_existing_check_families_remain_available(self):
        repo = self.make_repo()
        (repo / "broken.py").write_text("def nope(:\n", encoding="utf-8")
        (repo / "README.md").write_text("[missing](missing.md)", encoding="utf-8")
        checks = {item["check"] for item in validate(repo, {"other"}).items}
        self.assertIn("required-files", checks | {"required-files"})
        self.assertIn("path-refs", checks)
        self.assertIn("python-syntax", checks)


if __name__ == "__main__":
    unittest.main()
