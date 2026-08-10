import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_registry import build_snapshot, load_contract_catalogs, render_artifacts


class InterfaceCatalogSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = json.loads((ROOT / "schema" / "taxonomy.v1.json").read_text(encoding="utf-8"))
        self.resources = [{"name": name, "url": f"https://github.com/quantskills/{name}"} for name in (".github", "join", "quantskills", "registry")]
        self.envelope, self.profiles, self.adapters, self.mappings = load_contract_catalogs()

    def asset(self, name, outputs=(), inputs=(), lineage=None):
        value = {"name": name, "url": f"https://github.com/quantskills/{name}", "description": "Synthetic closed-chain declaration for deterministic offline contract verification.", "project_type": "skill", "declaration_file": "SKILL.md", "tags": ["fixture"], "platforms": ["codex"], "status": "active", "requires": [], "summary_zh": "合成核心链契约夹具", "summary_en": "Synthetic core-chain contract fixture.", "license": "GPL-3.0-only", "validation_level": "verified", "maintainer_type": "community", "commit_sha": "fixture", "catalog": {"category": "02", "subcategory": "02.factor-evaluation"}, "workflow": {"primary_stage": "evaluation", "workflow_stages": ["evaluation"]}, "last_validated": "2026-08-10", "interface": {"mode": "structured", "envelope": {"name": "quantskills-envelope", "version": "1.0.0"}, "inputs": [{"profile": p, "version_range": ">=1.0.0 <2.0.0", "required": True} for p in inputs], "outputs": [{"profile": p, "version": "1.0.0"} for p in outputs], "adapters": []}}
        if lineage:
            value["lineage"] = {"source_mapping_id": lineage}
        return value

    def chain(self):
        return [
            self.asset("skill-pandadata-warehouse", ("market-bar",), lineage="pandadata-market-bar-v1"),
            self.asset("skill-factor-mining-pandaai", ("factor-panel",), ("market-bar",)),
            self.asset("skill-factor-grouped-wrapper", ("ranked-factor-set",), ("factor-panel",)),
            self.asset("skill-portfolio-optimize", ("portfolio-target",), ("ranked-factor-set",)),
            self.asset("skill-backtest", ("backtest-result", "evaluation-result"), ("portfolio-target",)),
            self.asset("skill-ssquant-ai-trader", ("execution-plan",), ("evaluation-result",)),
        ]

    def test_red_core_chain_requires_enriched_catalogs_and_is_deterministic(self):
        snapshot = build_snapshot(self.chain(), self.resources, self.taxonomy, self.profiles, self.adapters, self.envelope, self.mappings)
        self.assertEqual(set(snapshot), {"schema_version", "taxonomy_version", "taxonomy", "assets", "resources", "envelope", "profiles", "adapters", "provider_mappings", "compatibility_edges", "snapshot_id"})
        self.assertEqual([(edge["producer"], edge["consumer"]) for edge in snapshot["compatibility_edges"]], [("skill-portfolio-optimize", "skill-backtest"), ("skill-factor-mining-pandaai", "skill-factor-grouped-wrapper"), ("skill-pandadata-warehouse", "skill-factor-mining-pandaai"), ("skill-factor-grouped-wrapper", "skill-portfolio-optimize"), ("skill-backtest", "skill-ssquant-ai-trader")])
        shuffled = build_snapshot(list(reversed(self.chain())), list(reversed(self.resources)), self.taxonomy, self.profiles, self.adapters, self.envelope, self.mappings)
        self.assertEqual(snapshot["snapshot_id"], shuffled["snapshot_id"])
        self.assertEqual(render_artifacts(snapshot), render_artifacts(shuffled))

    def test_red_invalid_mapping_or_chain_link_rejects_before_render(self):
        before = build_snapshot(self.chain(), self.resources, self.taxonomy, self.profiles, self.adapters, self.envelope, self.mappings)
        broken = self.chain(); broken[0]["lineage"]["source_mapping_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "lineage"):
            build_snapshot(broken, self.resources, self.taxonomy, self.profiles, self.adapters, self.envelope, self.mappings)
        incomplete = self.chain(); incomplete.pop(2)
        snapshot = build_snapshot(incomplete, self.resources, self.taxonomy, self.profiles, self.adapters, self.envelope, self.mappings)
        self.assertNotEqual(snapshot["compatibility_edges"], before["compatibility_edges"])


if __name__ == "__main__":
    unittest.main()
