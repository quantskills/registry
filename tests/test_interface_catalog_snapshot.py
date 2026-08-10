import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_registry import build_snapshot, load_contract_catalogs, render_artifacts
from interface_catalog import admit_adapter_registry


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
        self.assertEqual(set(snapshot), {"schema_version", "taxonomy_version", "contract_mode", "interface_diagnostics", "taxonomy", "assets", "resources", "envelope", "profiles", "adapters", "provider_mappings", "core_lineage", "compatibility_edges", "snapshot_id"})
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
        self.assertTrue(snapshot["interface_diagnostics"] == [])
        self.assertNotIn(("skill-factor-mining-pandaai", "skill-factor-grouped-wrapper"), [(edge["producer"], edge["consumer"]) for edge in snapshot["compatibility_edges"]])

    def test_catalog_loader_rejects_malicious_local_catalogs_value_free(self):
        def rejected(relative, mutate):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "registry"
                shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
                path = root / relative
                mutate(path)
                with self.assertRaisesRegex(ValueError, r"^invalid interface catalog$"):
                    load_contract_catalogs(root)

        def json_mutation(callback):
            def mutate(path):
                document = json.loads(path.read_text(encoding="utf-8"))
                callback(document)
                path.write_text(json.dumps(document), encoding="utf-8")
            return mutate

        rejected("schema/envelope/index.json", lambda path: path.write_text('{"name":"quantskills-envelope","name":"evil","versions":{"1.0.0":"1.0.0.schema.json"}}', encoding="utf-8"))
        rejected("schema/envelope/index.json", json_mutation(lambda doc: doc["versions"].update({"2.0.0": "2.0.0.schema.json"})))
        def remove_envelope_const(document):
            identity = document["properties"]["$contract"]["properties"]["envelope"]
            identity.pop("const")
            identity["type"] = "string"
        rejected("schema/envelope/1.0.0.schema.json", json_mutation(remove_envelope_const))
        rejected("schema/envelope/1.0.0.schema.json", json_mutation(lambda doc: doc["properties"]["$contract"]["properties"]["envelope_version"].update({"const": "1.0.1"})))
        rejected("schema/profiles/index.json", json_mutation(lambda doc: doc["profiles"][0].update({"version": "1.0.1"})))
        rejected("schema/profiles/index.json", json_mutation(lambda doc: doc["profiles"][0].update({"schema": "base/market-bar/1.0.0.schema.json"})))
        rejected("schema/profiles/index.json", json_mutation(lambda doc: doc["profiles"][0].update({"primary_key": ["wrong"], "time_semantics": "wrong"})))
        rejected("schema/profiles/index.json", json_mutation(lambda doc: doc["profiles"].reverse()))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            outside = Path(temporary) / "outside.json"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            target = root / "schema/envelope/1.0.0.schema.json"
            outside.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            target.unlink()
            try:
                os.symlink(outside, target)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error.winerror if hasattr(error, 'winerror') else 'unsupported'}")
            with self.assertRaisesRegex(ValueError, r"^invalid interface catalog$"):
                load_contract_catalogs(root)

    def test_catalog_loader_rejects_untrusted_adapter_and_provider_rows(self):
        def rejected(relative, mutate):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "registry"
                shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
                path = root / relative
                document = json.loads(path.read_text(encoding="utf-8"))
                mutate(document)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, r"^invalid interface catalog$"):
                    load_contract_catalogs(root)

        adapter = {"id": "bad-adapter", "source": {"profile": "market-bar", "version": "1.0.0"}, "target": {"profile": "factor-panel", "version": "1.0.0"}, "implementation": {"repository": "registry", "path": "scripts/compatibility.py"}, "lossless": True, "validation_status": "validated", "evidence": {"fixture_sha256": "sha256:" + "0" * 64, "test_command": "test", "validated_at": "2026-08-10"}, "envelope_major": 1}
        for mutation in (
            lambda doc: doc["adapters"].append({**adapter, "unknown": True}),
            lambda doc: doc["adapters"].extend([adapter, {**adapter, "target": {"profile": "holdings", "version": "1.0.0"}}]),
            lambda doc: doc["adapters"].append({**adapter, "source": {"profile": "unknown", "version": "1.0.0"}}),
            lambda doc: doc["adapters"].append({**adapter, "lossless": False}),
            lambda doc: doc["adapters"].append({**adapter, "validation_status": "rejected"}),
            lambda doc: doc["adapters"].append({**adapter, "implementation": {"repository": "registry", "path": "../outside.py"}}),
        ):
            rejected("schema/adapters/registry.v1.json", mutation)
        for mutation in (
            lambda doc: doc["mappings"][0].update({"lossless": False}),
            lambda doc: doc["mappings"][0].update({"validation_status": "rejected"}),
            lambda doc: doc["mappings"][0].update({"extra": True}),
            lambda doc: doc["mappings"][0]["evidence"].update({"fixture": "C:/outside.json"}),
            lambda doc: doc["mappings"].reverse(),
        ):
            rejected("schema/adapters/pandadata-mappings.v1.json", mutation)

    def test_public_adapter_admission_is_fail_closed(self):
        self.assertTrue(admit_adapter_registry({"schema_version": "1.0.0", "adapters": []}, ROOT))
        self.assertFalse(admit_adapter_registry({"schema_version": "1.0.0", "adapters": [{"id": "bad"}]}, ROOT))


if __name__ == "__main__":
    unittest.main()
