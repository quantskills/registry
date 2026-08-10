import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_contract import validate_contract


class CoreChainContractsTests(unittest.TestCase):
    def test_closed_core_chain_artifacts_are_valid_and_safe(self):
        root = ROOT / "tests/fixtures/e2e/core-chain"
        lineage = json.loads((root / "lineage.json").read_text(encoding="utf-8"))["artifacts"]
        self.assertEqual([item["producer"] for item in lineage], ["skill-pandadata-warehouse", "skill-factor-mining-pandaai", "skill-factor-grouped-wrapper", "skill-portfolio-optimize", "skill-backtest", "skill-backtest", "skill-ssquant-ai-trader"])
        self.assertEqual(lineage[0]["source_mapping_id"], "pandadata-market-bar-v1")
        known = {}
        for item in lineage:
            raw = (root / item["file"]).read_bytes()
            document = json.loads(raw)
            self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(), item["artifact_sha256"])
            self.assertEqual(validate_contract(document, ROOT)["status"], "valid")
            self.assertEqual(document["$contract"]["profile"], item["profile"])
            self.assertEqual(document["meta"]["producer"], item["producer"])
            for input_ in item["inputs"]:
                self.assertIn(input_["id"], known)
                self.assertEqual(input_["artifact_sha256"], known[input_["id"]]["artifact_sha256"])
            known[item["id"]] = item
        self.assertEqual(lineage[0]["provenance"]["raw_sha256"], "sha256:4522f0923640a466e91ec61e1e7a988b384511e82637f6b54cd6febae154087f")
        execution = json.loads((root / "07-execution-plan.json").read_text(encoding="utf-8"))
        self.assertFalse(execution["payload"]["records"][0]["live_submission_allowed"])


if __name__ == "__main__":
    unittest.main()
