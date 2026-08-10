import unittest
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).parents[1]
GUIDES = ("CATALOG_CONTRACT_zh.md", "CATALOG_CONTRACT_en.md")
RUNTIMES = {"cursor", "claude-code", "codex", "hermes", "openclaw"}
INTERFACE_MODES = {"structured", "hybrid", "natural-language", "not-applicable"}
NA_REASONS = {"natural-language-only", "report-only", "orchestration-only"}


class ContractDocumentationTests(unittest.TestCase):
    def test_each_guide_states_the_complete_operational_contract(self):
        for name in GUIDES:
            with self.subTest(guide=name):
                text = (ROOT / "docs" / name).read_text(encoding="utf-8")
                for token in ("2.0.0", "10", "61", "14", "five workflow display groups", *RUNTIMES, *INTERFACE_MODES, *NA_REASONS, "audit", "enforce", "registry.json", "catalog.snapshot.json", "snapshot_id"):
                    self.assertIn(token, text)
                for token in ("07", "08", "uncategorized", "unknown", "待迁移"):
                    self.assertIn(token, text)
                self.assertRegex(text, r"(?is)(never silently mapped|不得静默 fallback).{0,160}(07|08|uncategorized)")
                self.assertRegex(text, r"(?is)summary_zh.{0,80}summary_en.{0,200}(only after validation|仅在验证后)")

    def test_readmes_link_both_contract_guides_and_drop_legacy_category_enum(self):
        for name in ("README.md", "README.en.md"):
            with self.subTest(readme=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("docs/CATALOG_CONTRACT_zh.md", text)
                self.assertIn("docs/CATALOG_CONTRACT_en.md", text)
                self.assertNotIn("14 enums — skill side", text)
                self.assertNotIn("14 个枚举：skill 类", text)

    def test_workflow_keeps_audit_non_publishing_and_manual_enforce_publishing(self):
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "nightly-scan.yml").read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))
        dispatch = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(dispatch["full"]["type"], "boolean")
        self.assertIs(dispatch["full"]["default"], False)
        self.assertEqual(dispatch["contract_mode"]["type"], "choice")
        self.assertEqual(set(dispatch["contract_mode"]["options"]), {"audit", "enforce"})
        self.assertEqual(dispatch["contract_mode"]["default"], "audit")
        steps = workflow["jobs"]["scan"]["steps"]
        normal_build = next(step for step in steps if step.get("name") == "Build registry")
        full_build = next(step for step in steps if step.get("name") == "Build registry (full compatibility)")
        publish = next(step for step in steps if step.get("name") == "Commit artifacts")
        final_validation = next(step for step in steps if step.get("name") == "Final enforce validation")
        normal_condition = "${{ github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.full == false) }}"
        full_condition = "${{ github.event_name == 'workflow_dispatch' && inputs.full == true }}"
        self.assertEqual(normal_build["if"], normal_condition)
        self.assertEqual(full_build["if"], full_condition)
        self.assertIn("--contract-mode \"$CONTRACT_MODE\"", normal_build["run"])
        self.assertIn("--contract-mode \"$CONTRACT_MODE\"", full_build["run"])
        self.assertNotIn("--full", normal_build["run"])
        self.assertIn("--full", full_build["run"])
        for build in (normal_build, full_build):
            self.assertEqual(build["env"]["GITHUB_TOKEN"], "${{ secrets.QS_READ_TOKEN }}")
        cases = (("schedule", False, (True, False)), ("workflow_dispatch", False, (True, False)), ("workflow_dispatch", True, (False, True)))
        for event, full, expected in cases:
            actual = (
                event == "schedule" or (event == "workflow_dispatch" and full is False),
                event == "workflow_dispatch" and full is True,
            )
            self.assertEqual(actual, expected, (event, full))
            self.assertEqual(sum(actual), 1, (event, full))
        self.assertIn("github.event_name == 'workflow_dispatch'", publish["if"])
        self.assertIn("inputs.contract_mode == 'enforce'", publish["if"])
        self.assertEqual(final_validation["if"], publish["if"])
        self.assertIn("--contract-mode enforce", final_validation["run"])

    def test_builder_retains_full_flag_as_a_compatible_cli_switch(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_registry.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--full", result.stdout)


if __name__ == "__main__":
    unittest.main()
