import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_contract import validate_contract
from interface_catalog import load_core_lineage


class CoreChainContractsTests(unittest.TestCase):
    def test_closed_core_chain_artifacts_are_valid_and_safe(self):
        root = ROOT / "tests/fixtures/e2e/core-chain"
        manifest = load_core_lineage(ROOT)
        self.assertEqual(set(manifest), {"version", "scope", "artifacts"})
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["scope"], "schema-smoke-only")
        lineage = manifest["artifacts"]
        self.assertEqual([item["file"] for item in lineage], ["01-market-bar.json", "02-factor-panel.json", "03-ranked-factor-set.json", "04-portfolio-target.json", "05-backtest-result.json", "06-evaluation-result.json", "07-execution-plan.json"])
        self.assertEqual([item["id"] for item in lineage], ["market-bar", "factor-panel", "ranking", "portfolio", "backtest", "evaluation", "execution"])
        self.assertEqual([item["producer"] for item in lineage], ["skill-pandadata-warehouse", "skill-factor-mining-pandaai", "skill-factor-grouped-wrapper", "skill-portfolio-optimize", "skill-backtest", "skill-backtest", "skill-ssquant-ai-trader"])
        self.assertEqual(lineage[0]["source_mapping_id"], "pandadata-market-bar-v1")
        self.assertEqual(lineage[0]["inputs"], [])
        self.assertEqual(lineage[0]["provenance"], {"provider": "pandadata", "dataset": "bars-daily", "raw_ref": "fixture://pandadata/market-bar/001", "raw_sha256": "sha256:4522f0923640a466e91ec61e1e7a988b384511e82637f6b54cd6febae154087f"})
        first_document = json.loads((root / lineage[0]["file"]).read_text(encoding="utf-8"))
        self.assertEqual(first_document["meta"]["provenance"], [lineage[0]["provenance"]])
        known = {}
        for index, item in enumerate(lineage):
            raw = (root / item["file"]).read_bytes()
            self.assertEqual(raw, (ROOT / "schema/core-lineage/1.0.0" / item["file"]).read_bytes())
            document = json.loads(raw)
            self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(), item["artifact_sha256"])
            self.assertEqual(validate_contract(document, ROOT)["status"], "valid")
            self.assertEqual(document["$contract"]["profile"], item["profile"])
            self.assertEqual(document["meta"]["producer"], item["producer"])
            if index:
                predecessor = lineage[index - 1]
                predecessor_sha = "sha256:" + hashlib.sha256((root / predecessor["file"]).read_bytes()).hexdigest()
                self.assertEqual(item["inputs"], [{"id": predecessor["id"], "artifact_sha256": predecessor_sha}])
                self.assertEqual(document["meta"]["provenance"][0], {"provider": predecessor["producer"], "dataset": predecessor["id"], "raw_ref": f"artifact://core-chain/{predecessor['id']}", "raw_sha256": predecessor_sha})
                if index >= 2:
                    source = document["payload"]["records"][0]["lineage"]["sources"][0]
                    self.assertEqual(source, {"profile": predecessor["profile"], "version": "1.0.0", "artifact_ref": f"artifact://core-chain/{predecessor['id']}", "sha256": predecessor_sha})
            known[item["id"]] = item
        self.assertEqual(lineage[0]["provenance"]["raw_sha256"], "sha256:4522f0923640a466e91ec61e1e7a988b384511e82637f6b54cd6febae154087f")
        execution = json.loads((root / "07-execution-plan.json").read_text(encoding="utf-8"))
        self.assertFalse(execution["payload"]["records"][0]["live_submission_allowed"])
        self.assertEqual((root / "lineage.json").read_bytes(), (ROOT / "schema/core-lineage/1.0.0/lineage.json").read_bytes())

    def test_scope_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".superpowers"))
            path = root / "schema/core-lineage/1.0.0/lineage.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.pop("scope")
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_core_lineage(root)

            manifest["scope"] = "business-closed"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_core_lineage(root)


if __name__ == "__main__":
    unittest.main()
