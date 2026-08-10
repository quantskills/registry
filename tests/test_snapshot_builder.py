import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_registry import build_snapshot, collect_entries, public_registry_projection, render_artifacts


class SnapshotBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "tests" / "fixtures" / "builder"
        cls.repos = json.loads((fixture / "repos.json").read_text(encoding="utf-8"))
        declarations = json.loads((fixture / "declarations.json").read_text(encoding="utf-8"))
        cls.repos = [{**repo, "frontmatter": declarations[repo["name"]]} if repo["name"] in declarations else repo for repo in cls.repos]
        cls.taxonomy = json.loads((ROOT / "schema" / "taxonomy.v1.json").read_text(encoding="utf-8"))

    def snapshot(self, repos=None):
        entries, resources = collect_entries(repos or self.repos, {}, "enforce")
        return build_snapshot(entries, resources, self.taxonomy, {"version": "1.0.0", "items": []}, {"version": "1.0.0", "items": []})

    def test_snapshot_is_order_independent_and_canonical(self):
        first, second = self.snapshot(), self.snapshot(list(reversed(self.repos)))
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(render_artifacts(first), render_artifacts(second))
        self.assertRegex(first["snapshot_id"], r"^sha256:[0-9a-f]{64}$")
        stable = {key: value for key, value in first.items() if key not in {"snapshot_id", "generated_at", "validated_at"}}
        digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(first["snapshot_id"], f"sha256:{digest}")

    def test_snapshot_and_projection_have_required_boundaries(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["taxonomy_version"], "1.0.0")
        self.assertEqual(snapshot["profiles"], {"version": "1.0.0", "items": []})
        self.assertEqual(snapshot["adapters"], {"version": "1.0.0", "items": []})
        self.assertEqual(snapshot["compatibility_edges"], [])
        self.assertEqual([item["name"] for item in snapshot["resources"]], [".github", "join", "quantskills", "registry"])
        self.assertEqual({item["name"] for item in snapshot["assets"] if item["catalog"]["category"] == "10"}, {"skill-template", "agent-template"})
        projection = public_registry_projection(snapshot)
        self.assertIsInstance(projection, list)
        self.assertTrue(all(row["snapshot_id"] == snapshot["snapshot_id"] for row in projection))
        self.assertTrue(all("interface" in row and "catalog" in row and "workflow" in row for row in projection))

    def test_collection_rejects_duplicate_and_invalid_declarations(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            collect_entries(self.repos + [self.repos[0]], {}, "enforce")
        broken = [{**self.repos[0], "frontmatter": {}}]
        with self.assertRaises(ValueError):
            collect_entries(broken, {}, "enforce")

    def test_audit_keeps_legacy_templates_visible_but_enforce_rejects_them(self):
        legacy = [{"name": "skill-template", "frontmatter": {"description": "Legacy template"}}, *self.repos[3:]]
        entries, _ = collect_entries(legacy, {}, "audit")
        self.assertEqual(entries[0]["catalog"]["category"], "10")
        self.assertEqual(entries[0]["migration_state"], "pending-v2")
        with self.assertRaises(ValueError):
            collect_entries(legacy, {}, "enforce")

    def test_missing_real_resource_fails_before_snapshot(self):
        with self.assertRaisesRegex(ValueError, "resource inventory"):
            collect_entries(self.repos[:-1], {}, "audit")


if __name__ == "__main__":
    unittest.main()
