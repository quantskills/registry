import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_migration_data import COLUMNS, CORE, WAVES, validate


class MigrationDataTests(unittest.TestCase):
    digest = "sha256:" + "a" * 64
    stages = [
        ("data-ingestion", "01", "01.data-source-connectors"),
        ("data-quality", "01", "01.warehouse-cache"),
        ("feature-engineering", "02", "02.factor-generation"),
        ("factor-generation", "02", "02.factor-generation"),
        ("factor-screening", "02", "02.factor-selection"),
        ("modeling", "06", "06.statistical-ml-models"),
        ("portfolio-construction", "05", "05.portfolio-construction"),
        ("backtesting", "05", "05.backtest-engine"),
        ("evaluation", "02", "02.factor-evaluation"),
        ("risk", "04", "04.market-regime"),
        ("monitoring", "04", "04.market-regime"),
        ("execution", "05", "05.paper-live-execution"),
        ("reporting", "08", "08.daily-review"),
        ("orchestration", "09", "09.workflow-orchestration-agent"),
    ]

    def write(self, root, mutate=lambda rows, audit, waves: None, *, core=False):
        if core:
            names = sorted(CORE) + [f"skill-extra-{i}" for i in range(7)] + ["agent-a"]
        else:
            names = [f"skill-{i}" for i in range(13)] + ["agent-a"]
        # Frozen inventory assets intentionally omit project_type; the
        # validator derives it from the repository prefix.
        inventory = {"schema_version": "1.0.0", "sha256": self.digest, "assets": [{"name": name} for name in names]}
        rows = []
        for name, (stage, category, subcategory) in zip(names, self.stages):
            project_type = "agent" if name.startswith("agent-") else "skill"
            declaration = "AGENTS.md" if project_type == "agent" else "SKILL.md"
            rows.append(
                dict(
                    zip(
                        COLUMNS,
                        [
                            name,
                            project_type,
                            category,
                            subcategory,
                            stage,
                            stage,
                            "用于迁移验证的中文摘要",
                            "Useful reviewed migration summary",
                            "natural-language",
                            "approved",
                            declaration,
                        ],
                    )
                )
            )
        audit = {
            "schema_version": "1.0.0",
            "inventory_sha256": self.digest,
            "items": [],
        }
        waves = {
            "schema_version": "1.0.0",
            "inventory_sha256": self.digest,
            "waves": {wave: [] for wave in sorted(WAVES)},
        }
        for name in names:
            base = "agent-runtime" if name.startswith("agent-") else "non-structured-review"
            item_waves = [base]
            if core and name in CORE:
                waves["waves"]["core-chain"].append(name)
                item_waves.append("core-chain")
            waves["waves"][base].append(name)
            audit["items"].append(
                {
                    "name": name,
                    "declaration_readable": True,
                    "structured_io_explicit": False,
                    "candidate_mode": "natural-language",
                    "evidence_paths": [declaration],
                    "detected_formats": [],
                    "detected_fields": [],
                    "required_maintainer_decision": False,
                    "waves": sorted(item_waves),
                    "notes": "",
                }
            )
        for members in waves["waves"].values():
            members.sort()
        mutate(rows, audit, waves)
        (root / "i.json").write_text(json.dumps(inventory), encoding="utf-8")
        with (root / "a.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        (root / "x.json").write_text(json.dumps(audit), encoding="utf-8")
        (root / "w.json").write_text(json.dumps(waves), encoding="utf-8")
        return root / "i.json", root / "a.csv", root / "x.json", root / "w.json"

    def test_valid_complete_taxonomy_and_expected_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write(Path(directory))
            self.assertEqual(validate(*paths, expected_structured=0), {"assets": 14, "approved": 14, "structured": 0})

    def test_inventory_without_project_type_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write(Path(directory))
            self.assertEqual(validate(*paths)["assets"], 14)

    def test_rejects_malformed_inventory_hashes(self):
        cases = [
            lambda rows, audit, waves: audit.update(inventory_sha256="sha256:" + "b" * 63),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.write(root)
            inventory = json.loads(paths[0].read_text())
            inventory["sha256"] = "sha256:x"
            paths[0].write_text(json.dumps(inventory))
            with self.assertRaises(ValueError):
                validate(*paths)
            for mutate in cases:
                paths = self.write(root, mutate)
                with self.assertRaises(ValueError):
                    validate(*paths)
            paths = self.write(root)
            inventory = json.loads(paths[0].read_text())
            inventory["assets"][0]["head_sha"] = "bad"
            paths[0].write_text(json.dumps(inventory))
            with self.assertRaises(ValueError):
                validate(*paths)

    def test_rejects_wave_root_and_schema_errors(self):
        cases = [
            lambda rows, audit, waves: waves["waves"].pop("core-chain"),
            lambda rows, audit, waves: waves["waves"].update(extra=[]),
            lambda rows, audit, waves: audit.update(schema_version="2.0.0"),
            lambda rows, audit, waves: waves.update(schema_version="2.0.0"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in cases:
                paths = self.write(root, mutate)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    validate(*paths)

    def test_rejects_interface_field_types_and_lists(self):
        cases = [
            lambda rows, audit, waves: audit["items"][0].update(declaration_readable="true"),
            lambda rows, audit, waves: audit["items"][0].update(structured_io_explicit=1),
            lambda rows, audit, waves: audit["items"][0].update(required_maintainer_decision="no"),
            lambda rows, audit, waves: audit["items"][0].update(notes=None),
            lambda rows, audit, waves: audit["items"][0].update(evidence_paths=[]),
            lambda rows, audit, waves: audit["items"][0].update(detected_formats=["csv", "csv"]),
            lambda rows, audit, waves: audit["items"][0].update(detected_fields=["", "close"]),
            lambda rows, audit, waves: audit["items"][0].update(waves=["non-structured-review", "agent-runtime"]),
            lambda rows, audit, waves: audit["items"][0].update(waves=["non-structured-review", "non-structured-review"]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in cases:
                paths = self.write(root, mutate)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    validate(*paths)

    def test_rejects_assignment_evidence_and_candidate_enum(self):
        cases = [
            lambda rows, audit, waves: rows[0].update(evidence=""),
            lambda rows, audit, waves: rows[0].update(evidence="README.md||SKILL.md"),
            lambda rows, audit, waves: rows[0].update(evidence="SKILL.md|README.md"),
            lambda rows, audit, waves: rows[0].update(interface_candidate="not-an-interface"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in cases:
                paths = self.write(root, mutate)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    validate(*paths)

    def test_summary_language_generic_and_claim_rules(self):
        rejected = [
            lambda rows, audit, waves: rows[0].update(summary_zh="short"),
            lambda rows, audit, waves: rows[0].update(summary_zh="Useful English summary"),
            lambda rows, audit, waves: rows[0].update(summary_en="12345678"),
            lambda rows, audit, waves: rows[0].update(summary_en="short"),
            lambda rows, audit, waves: rows[0].update(summary_en="skill-0"),
            lambda rows, audit, waves: rows[0].update(summary_en="Skill repository"),
            lambda rows, audit, waves: rows[0].update(summary_en="Agent repository"),
            lambda rows, audit, waves: rows[0].update(summary_en="This is an official certified release"),
            lambda rows, audit, waves: rows[0].update(summary_en="This is a guaranteed return strategy"),
            lambda rows, audit, waves: rows[0].update(summary_en="This is a risk-free safe strategy"),
            lambda rows, audit, waves: rows[0].update(summary_en="This is investment advice"),
            lambda rows, audit, waves: rows[0].update(summary_zh="这是官方认证的生产可用策略"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in rejected:
                paths = self.write(root, mutate)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    validate(*paths)
            for disclaimer in ("This is not official investment advice", "This does not guarantee returns", "这不构成投资建议，也不是官方产品"):
                paths = self.write(root, lambda rows, audit, waves, value=disclaimer: rows[0].update(summary_en=value) if value.isascii() else rows[0].update(summary_zh=value))
                validate(*paths)

    def test_cross_links_base_wave_and_core_chain(self):
        rejected = [
            lambda rows, audit, waves: audit["items"][0].update(waves=["non-structured-review", "structured-remaining"]),
            lambda rows, audit, waves: waves["waves"]["non-structured-review"].append("skill-0"),
            lambda rows, audit, waves: waves["waves"]["agent-runtime"].remove("agent-a"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in rejected:
                paths = self.write(root, mutate)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    validate(*paths)
            paths = self.write(root, core=True)
            result = validate(*paths)
            self.assertEqual(result["assets"], 14)
            paths = self.write(root, lambda rows, audit, waves: waves["waves"]["core-chain"].append("skill-extra-0"), core=True)
            with self.assertRaises(ValueError):
                validate(*paths)
            paths = self.write(root, lambda rows, audit, waves: waves["waves"]["core-chain"].pop(), core=True)
            with self.assertRaises(ValueError):
                validate(*paths)

    def test_enforce_and_expected_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.write(root, lambda rows, audit, waves: rows[0].update(review_status="blocked"))
            validate(*paths)
            with self.assertRaises(ValueError):
                validate(*paths, enforce=True)
            with self.assertRaises(ValueError):
                validate(*paths, expected_structured=1)

    def test_cli_emits_json_on_success_and_nonzero_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.write(Path(directory))
            command = [
                sys.executable,
                str(ROOT / "scripts" / "validate_migration_data.py"),
                "--inventory",
                str(paths[0]),
                "--assignments",
                str(paths[1]),
                "--interfaces",
                str(paths[2]),
                "--waves",
                str(paths[3]),
                "--expected-structured",
                "0",
            ]
            success = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(success.returncode, 0)
            self.assertEqual(json.loads(success.stdout), {"assets": 14, "approved": 14, "structured": 0})
            failure = subprocess.run(command[:-1] + ["1"], capture_output=True, text=True, check=False)
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("unexpected structured count", failure.stderr)


if __name__ == "__main__":
    unittest.main()
