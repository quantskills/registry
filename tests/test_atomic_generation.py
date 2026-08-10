import tempfile
import unittest
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_registry
from verify_catalog_artifacts import verify


class AtomicGenerationTests(unittest.TestCase):
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
        snapshot.update({"contract_mode": "audit", "interface_diagnostics": [], "envelope": envelope, "profiles": profiles, "adapters": adapters, "provider_mappings": mappings, "core_lineage": build_registry.load_core_lineage()})
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
