import tempfile
import unittest
import json
import copy
import hashlib
import os
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_registry
from verify_catalog_artifacts import verify


class AtomicGenerationTests(unittest.TestCase):
    def _sealed(self, snapshot):
        snapshot["snapshot_id"] = "sha256:" + hashlib.sha256(build_registry.canonical_json(build_registry._stable_snapshot(snapshot))).hexdigest()
        return snapshot

    def test_verifier_rejects_self_consistent_trusted_catalog_bypasses_before_promotion(self):
        """Each tamper recomputes public projection and ID, so self-hashes cannot hide it."""
        taxonomy = build_registry.load_taxonomy(ROOT)
        envelope, profiles, adapters, mappings = build_registry.load_contract_catalogs()
        names = (("skill-pandadata-warehouse", ("market-bar",), ()), ("skill-factor-mining-pandaai", ("factor-panel",), ("market-bar",)), ("skill-factor-grouped-wrapper", ("ranked-factor-set",), ("factor-panel",)), ("skill-portfolio-optimize", ("portfolio-target",), ("ranked-factor-set",)), ("skill-backtest", ("backtest-result", "evaluation-result"), ("portfolio-target",)), ("skill-ssquant-ai-trader", ("execution-plan",), ("evaluation-result",)))
        def asset(name, outputs, inputs):
            return {"name": name, "url": f"https://github.com/quantskills/{name}", "description": "fixture", "project_type": "skill", "declaration_file": "SKILL.md", "tags": [], "platforms": [], "status": "active", "requires": [], "summary_zh": "fixture", "summary_en": "fixture", "license": "GPL-3.0-only", "validation_level": "verified", "maintainer_type": "community", "commit_sha": "fixture", "catalog": {"category": "02", "subcategory": "02.factor-evaluation"}, "category": "02", "subcategory": "02.factor-evaluation", "workflow": {"primary_stage": "evaluation", "workflow_stages": ["evaluation"]}, "stage": "evaluation", "last_validated": "2026-08-10", "interface": {"mode": "structured", "envelope": {"name": "quantskills-envelope", "version": "1.0.0"}, "inputs": [{"profile": item, "version_range": ">=1.0.0 <2.0.0", "required": True} for item in inputs], "outputs": [{"profile": item, "version": "1.0.0"} for item in outputs], "adapters": []}}
        baseline = build_registry.build_snapshot([asset(*row) for row in names], [{"name": name, "url": f"https://github.com/quantskills/{name}"} for name in (".github", "join", "quantskills", "registry")], taxonomy, profiles, adapters, envelope, mappings, contract_mode="enforce")
        fake = {"id": "fake-adapter", "source": {"profile": "market-bar", "version": "1.0.0"}, "target": {"profile": "factor-panel", "version": "1.0.0"}, "implementation": {"repository": "registry", "path": "scripts/compatibility.py"}, "lossless": True, "validation_status": "validated", "evidence": {"fixture_sha256": "sha256:" + "0" * 64, "test_command": "fixture", "validated_at": "2026-08-10"}, "envelope_major": 1}
        mutations = (
            lambda value: (value.pop("envelope"), value.pop("provider_mappings")),
            lambda value: value.update(compatibility_edges=[]),
            lambda value: value["profiles"]["items"][0].update(schema="wrong.schema.json"),
            lambda value: value["provider_mappings"]["items"][0]["evidence"].update(raw_sha256="sha256:" + "0" * 64),
            lambda value: value["adapters"]["items"].append(copy.deepcopy(fake)),
            lambda value: value["core_lineage"]["artifacts"][0].update(artifact_sha256="sha256:" + "0" * 64),
            lambda value: value["assets"].append(copy.deepcopy(value["assets"][0])),
            lambda value: value["resources"].append(copy.deepcopy(value["resources"][0])),
            lambda value: value["resources"][0].update(url="https://evil.example/.github"),
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            base = Path(temporary)
            sp, rp = base / "catalog.snapshot.json", base / "registry.json"
            readmes = (base / "README.md", base / "README.en.md")
            sp.write_text(json.dumps(baseline), encoding="utf-8"); rp.write_text(json.dumps(build_registry.public_registry_projection(baseline)), encoding="utf-8")
            for readme in readmes: readme.write_text(f"<!-- registry-snapshot:start -->\n`{baseline['snapshot_id']}`\n<!-- registry-snapshot:end -->", encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts" / "verify_catalog_artifacts.py"), str(sp), str(rp), "--readme", str(readmes[0]), "--readme", str(readmes[1]), "--expected-contract-mode", "enforce"]
            self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 0)
            self.assertEqual(subprocess.run(["node", str(ROOT / "scripts" / "validate-registry.mjs"), "--contract-mode", "enforce", str(rp)], capture_output=True, text=True).returncode, 0)
            audit = copy.deepcopy(baseline); audit["contract_mode"] = "audit"; self._sealed(audit)
            sp.write_text(json.dumps(audit), encoding="utf-8"); rp.write_text(json.dumps(build_registry.public_registry_projection(audit)), encoding="utf-8")
            for readme in readmes: readme.write_text(f"<!-- registry-snapshot:start -->\n`{audit['snapshot_id']}`\n<!-- registry-snapshot:end -->", encoding="utf-8")
            self.assertNotEqual(subprocess.run(command, capture_output=True, text=True).returncode, 0)
            self.assertEqual(subprocess.run(["node", str(ROOT / "scripts" / "validate-registry.mjs"), "--contract-mode", "enforce", str(rp)], capture_output=True, text=True).returncode, 0)
            for mutate in mutations:
                snapshot = copy.deepcopy(baseline); mutate(snapshot); self._sealed(snapshot)
                sp.write_text(json.dumps(snapshot), encoding="utf-8"); rp.write_text(json.dumps(build_registry.public_registry_projection(snapshot)), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify(sp, rp)
                for readme in readmes: readme.write_text(f"<!-- registry-snapshot:start -->\n`{snapshot['snapshot_id']}`\n<!-- registry-snapshot:end -->", encoding="utf-8")
                first = base / "first.json"; first.write_bytes(b"old")
                original_root, build_registry.ROOT = build_registry.ROOT, base
                original_replace, calls = build_registry.os.replace, 0
                def count_replace(source, destination):
                    nonlocal calls
                    calls += 1
                    return original_replace(source, destination)
                build_registry.os.replace = count_replace
                try:
                    with self.assertRaises(ValueError): build_registry.promote_artifacts({first: b"replacement", sp: sp.read_bytes(), rp: rp.read_bytes(), readmes[0]: readmes[0].read_bytes(), readmes[1]: readmes[1].read_bytes()})
                finally:
                    build_registry.ROOT, build_registry.os.replace = original_root, original_replace
                self.assertEqual(first.read_bytes(), b"old")
                self.assertEqual(calls, 0)
            sp.write_text(json.dumps(baseline), encoding="utf-8"); rp.write_text(json.dumps(build_registry.public_registry_projection(baseline)), encoding="utf-8")
            readmes[0].write_text(f"<!-- registry-snapshot:start -->\n`{baseline['snapshot_id']}`\n<!-- registry-snapshot:end -->\n<!-- registry-snapshot:start -->\n`{baseline['snapshot_id']}`\n<!-- registry-snapshot:end -->", encoding="utf-8")
            with self.assertRaises(ValueError): verify(sp, rp, readmes)
    def test_promotion_failure_restores_all_destinations(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            tmp = Path(tmp)
            first, second = tmp / "first.json", tmp / "second.json"
            first.write_bytes(b"old-first")
            outputs = {first: b"new-first", second: b"new-second"}
            original_replace = build_registry.os.replace
            calls = 0
            def fail_second(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected replacement failure")
                return original_replace(src, dst)
            build_registry.os.replace = fail_second
            try:
                with self.assertRaises(OSError):
                    build_registry.promote_artifacts(outputs)
            finally:
                build_registry.os.replace = original_replace
            self.assertEqual(first.read_bytes(), b"old-first")
            self.assertFalse(second.exists())

    def test_production_collection_uses_clone_head_not_remote_head(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            temp = Path(tmp)
            original_clone, original_head, original_validate = build_registry.shallow_clone, build_registry.head_sha, build_registry.validate
            def fake_clone(name, destination):
                destination.mkdir()
                (destination / "SKILL.md").write_text("---\ndescription: local\nquantSkills:\n  project_type: skill\n  catalog: {category: '02', subcategory: '02.factor-evaluation'}\n  workflow: {primary_stage: evaluation, workflow_stages: [evaluation]}\n  interface: {mode: not-applicable}\n---\n", encoding="utf-8")
                return "local-clone-sha"
            build_registry.shallow_clone = fake_clone
            build_registry.head_sha = lambda repo: self.fail("remote HEAD must not be read after clone")
            build_registry.validate = lambda *args: type("Report", (), {"health": "healthy"})()
            repos = [{"name": "skill-alpha"}, {"name": ".github"}, {"name": "join"}, {"name": "quantskills"}, {"name": "registry"}]
            try:
                entries, _ = build_registry.collect_entries(repos, {}, "audit", inventory={"assets": ["skill-alpha"], "resources": [".github", "join", "quantskills", "registry"]})
            finally:
                build_registry.shallow_clone, build_registry.head_sha, build_registry.validate = original_clone, original_head, original_validate
            self.assertEqual(entries[0]["commit_sha"], "local-clone-sha")

    def test_verifier_rejects_corrupt_id_asset_set_and_readme_marker(self):
        snapshot = {"schema_version": "1.0.0", "taxonomy_version": "1.0.0", "taxonomy": {"schema_version": "1.0.0", "categories": {}, "workflow_stages": []}, "assets": [{"name": "skill-a", "url": "https://github.com/quantskills/skill-a", "description": "x", "project_type": "skill", "declaration_file": "SKILL.md", "tags": [], "platforms": [], "status": "active", "requires": [], "summary_zh": "中文说明", "summary_en": "Natural language asset", "license": "GPL-3.0-only", "validation_level": "listed", "maintainer_type": "community", "commit_sha": "", "catalog": {"category": "02", "subcategory": "02.factor-evaluation"}, "workflow": {"primary_stage": "evaluation", "workflow_stages": ["evaluation"]}, "interface": {"mode": "natural-language"}, "last_validated": "2026-08-10"}], "resources": [{"name": name, "url": f"https://github.com/quantskills/{name}"} for name in [".github", "join", "quantskills", "registry"]], "profiles": {"version": "1.0.0", "items": []}, "adapters": {"version": "1.0.0", "items": []}, "compatibility_edges": []}
        envelope, profiles, adapters, mappings = build_registry.load_contract_catalogs()
        snapshot["taxonomy"] = build_registry.load_taxonomy(ROOT)
        snapshot["assets"][0].update({"category": "02", "subcategory": "02.factor-evaluation", "stage": "evaluation"})
        snapshot.update({"contract_mode": "audit", "interface_diagnostics": [], "envelope": envelope, "profiles": profiles, "adapters": adapters, "provider_mappings": mappings, "core_lineage": {"version": "1.0.0", "artifacts": []}})
        snapshot["snapshot_id"] = "sha256:" + build_registry.hashlib.sha256(build_registry.canonical_json(build_registry._stable_snapshot(snapshot))).hexdigest()
        row = {"name": "skill-a", "url": "https://github.com/quantskills/skill-a", "description": "x", "project_type": "skill", "declaration_file": "SKILL.md", "category": "02", "subcategory": "02.factor-evaluation", "stage": "evaluation", "tags": [], "platforms": [], "status": "active", "requires": [], "summary_zh": "中文说明", "summary_en": "Natural language asset", "license": "GPL-3.0-only", "last_validated": "2026-08-10", "validation_level": "listed", "maintainer_type": "community", "commit_sha": "", "catalog": snapshot["assets"][0]["catalog"], "workflow": snapshot["assets"][0]["workflow"], "interface": {"mode": "natural-language"}, "snapshot_id": snapshot["snapshot_id"]}
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp); sp, rp, readme = root / "catalog.snapshot.json", root / "registry.json", root / "README.md"
            sp.write_text(json.dumps(snapshot), encoding="utf-8"); rp.write_text(json.dumps([row]), encoding="utf-8")
            readme.write_text(f"<!-- registry-snapshot:start -->\n`{snapshot['snapshot_id']}`\n<!-- registry-snapshot:end -->", encoding="utf-8")
            verify(sp, rp, (readme,))
            snapshot["snapshot_id"] = "sha256:" + "0" * 64; sp.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(ValueError): verify(sp, rp, (readme,))


if __name__ == "__main__":
    unittest.main()
