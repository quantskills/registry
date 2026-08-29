import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
import copy
import csv
import tempfile
import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_registry import apply_listing_policy, build_snapshot, collect_entries, public_registry_projection, render_artifacts
import build_registry


class SnapshotBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "tests" / "fixtures" / "builder"
        cls.repos = json.loads((fixture / "repos.json").read_text(encoding="utf-8"))
        declarations = json.loads((fixture / "declarations.json").read_text(encoding="utf-8"))
        cls.repos = [{**repo, "frontmatter": declarations[repo["name"]]} if repo["name"] in declarations else repo for repo in cls.repos]
        cls.taxonomy = json.loads((ROOT / "schema" / "taxonomy.v1.json").read_text(encoding="utf-8"))

    def snapshot(self, repos=None):
        repos = repos or self.repos
        inventory = {"assets": sorted(repo["name"] for repo in repos if repo["name"] not in {".github", "join", "quantskills", "registry"}), "resources": [".github", "join", "quantskills", "registry"]}
        entries, resources = collect_entries(repos, {}, "enforce", inventory=inventory, validation_date="2026-08-10")
        return build_snapshot(entries, resources, self.taxonomy)

    def test_snapshot_is_order_independent_and_canonical(self):
        first, second = self.snapshot(), self.snapshot(list(reversed(self.repos)))
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(render_artifacts(first), render_artifacts(second))
        self.assertRegex(first["snapshot_id"], r"^sha256:[0-9a-f]{64}$")
        stable = build_registry._stable_snapshot(first)
        digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(first["snapshot_id"], f"sha256:{digest}")

    def test_validation_date_is_builder_metadata_and_excluded_from_snapshot_id(self):
        first_repos = self.repos
        second_repos = self.repos
        inventory = {"assets": ["agent-template", "skill-alpha", "skill-template"], "resources": [".github", "join", "quantskills", "registry"]}
        one, resources = collect_entries(first_repos, {}, "enforce", inventory=inventory, validation_date="2026-08-10")
        two, _ = collect_entries(second_repos, {}, "enforce", inventory=inventory, validation_date="2026-08-11")
        self.assertTrue(all(entry["last_validated"] == "2026-08-10" for entry in one))
        self.assertEqual(build_snapshot(one, resources, self.taxonomy)["snapshot_id"], build_snapshot(two, resources, self.taxonomy)["snapshot_id"])

    def test_snapshot_and_projection_have_required_boundaries(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["taxonomy_version"], "1.0.0")
        self.assertEqual(snapshot["profiles"]["version"], "1.0.0")
        self.assertEqual(snapshot["adapters"], {"version": "1.0.0", "items": []})
        self.assertEqual(snapshot["provider_mappings"]["version"], "1.0.0")
        self.assertEqual(snapshot["core_lineage"]["version"], "1.0.0")
        self.assertEqual(snapshot["core_lineage"]["scope"], "schema-smoke-only")
        self.assertEqual(snapshot["compatibility_edges"], [])
        self.assertEqual([item["name"] for item in snapshot["resources"]], [".github", "join", "quantskills", "registry"])
        self.assertEqual({item["name"] for item in snapshot["assets"] if item["catalog"]["category"] == "10"}, {"skill-template", "agent-template"})
        projection = public_registry_projection(snapshot)
        self.assertIsInstance(projection, list)
        self.assertTrue(all(row["snapshot_id"] == snapshot["snapshot_id"] for row in projection))
        self.assertTrue(all("interface" in row and "catalog" in row and "workflow" in row for row in projection))

    def test_listing_policy_keeps_duplicates_in_snapshot_but_hides_them_from_public_projection(self):
        entries = [dict(entry) for entry in self.snapshot()["assets"]]
        policy = ROOT / "catalog-listing.v1.json"
        original = policy.read_text(encoding="utf-8") if policy.exists() else None
        try:
            policy.write_text(json.dumps({"schema_version": "1.0.0", "entries": [{"name": "skill-alpha", "listing_status": "unlisted_duplicate", "superseded_by": "skill-template"}]}), encoding="utf-8")
            apply_listing_policy(entries, policy)
            resources = [{"name": name, "url": f"https://github.com/quantskills/{name}"} for name in (".github", "join", "quantskills", "registry")]
            snapshot = build_snapshot(entries, resources, self.taxonomy)
            self.assertIn("skill-alpha", {asset["name"] for asset in snapshot["assets"]})
            self.assertNotIn("skill-alpha", {asset["name"] for asset in public_registry_projection(snapshot)})
        finally:
            if original is None:
                policy.unlink(missing_ok=True)
            else:
                policy.write_text(original, encoding="utf-8")
    def test_collection_rejects_duplicate_and_invalid_declarations(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            collect_entries(self.repos + [self.repos[0]], {}, "enforce", inventory={"assets": [], "resources": [".github", "join", "quantskills", "registry"]})
        broken = [{**self.repos[0], "frontmatter": {}}]
        with self.assertRaises(ValueError):
            collect_entries(broken, {}, "enforce", inventory={"assets": ["skill-alpha"], "resources": [".github", "join", "quantskills", "registry"]})

    def test_audit_keeps_legacy_templates_visible_but_enforce_rejects_them(self):
        legacy = [{"name": "skill-template", "frontmatter": {"description": "Legacy template"}}, *self.repos[3:]]
        entries, _ = collect_entries(legacy, {}, "audit", inventory={"assets": ["skill-template"], "resources": [".github", "join", "quantskills", "registry"]})
        self.assertEqual(entries[0]["catalog"]["category"], "10")
        self.assertEqual(entries[0]["migration_state"], "pending-v2")
        with self.assertRaises(ValueError):
            collect_entries(legacy, {}, "enforce", inventory={"assets": ["skill-template"], "resources": [".github", "join", "quantskills", "registry"]})

    def test_missing_real_resource_fails_before_snapshot(self):
        with self.assertRaisesRegex(ValueError, "inventory"):
            collect_entries(self.repos[:-1], {}, "audit", inventory={"assets": ["skill-alpha", "skill-template", "agent-template"], "resources": [".github", "join", "quantskills", "registry"]})

    def test_inventory_rejects_removed_or_unapproved_assets_before_rendering(self):
        with self.assertRaisesRegex(ValueError, "inventory"):
            collect_entries(self.repos[1:], {}, "audit")
        with self.assertRaisesRegex(ValueError, "inventory"):
            collect_entries(self.repos + [{"name": "skill-unapproved", "frontmatter": self.repos[0]["frontmatter"]}], {}, "audit")

    def test_audit_keeps_generic_legacy_skill_and_agent_with_migration_issues(self):
        legacy = [
            {"name": "skill-alpha", "frontmatter": {"name": "skill-alpha", "description": "old skill"}},
            {"name": "agent-alpha", "frontmatter": {"name": "agent-alpha", "description": "old agent"}},
            *self.repos[3:],
        ]
        entries, _ = collect_entries(legacy, {}, "audit", inventory={"assets": ["skill-alpha", "agent-alpha"], "resources": [".github", "join", "quantskills", "registry"]})
        self.assertEqual([entry["migration_state"] for entry in entries[:2]], ["pending-v2", "pending-v2"])
        self.assertTrue(all(entry["migration_issues"] for entry in entries[:2]))
        with self.assertRaises(ValueError):
            collect_entries(legacy, {}, "enforce", inventory={"assets": ["skill-alpha", "agent-alpha"], "resources": [".github", "join", "quantskills", "registry"]})

    def test_partial_v2_skill_and_agent_are_visible_only_in_audit(self):
        declarations = []
        for fixture, name in (("valid-structured.yml", "skill-alpha"), ("valid-not-applicable.yml", "agent-alpha")):
            declaration = yaml.safe_load((ROOT / "tests" / "fixtures" / "declarations" / fixture).read_text(encoding="utf-8"))
            declaration["name"] = name
            declaration["quantSkills"]["repository"] = name
            declaration["quantSkills"]["repository_url"] = f"https://github.com/quantskills/{name}"
            declaration["quantSkills"].pop("summary_en")
            declarations.append({"name": name, "frontmatter": declaration})
        repos = [*declarations, *self.repos[3:]]
        inventory = {"assets": ["skill-alpha", "agent-alpha"], "resources": [".github", "join", "quantskills", "registry"]}
        entries, _ = collect_entries(repos, {}, "audit", inventory=inventory)
        self.assertEqual([entry["migration_state"] for entry in entries], ["pending-v2", "pending-v2"])
        self.assertTrue(all({"code", "path"} <= set(issue) for entry in entries for issue in entry["migration_issues"]))
        with self.assertRaises(ValueError):
            collect_entries(repos, {}, "enforce", inventory=inventory)

    def test_audit_normalizes_each_invalid_public_value_without_leaking_it(self):
        base = yaml.safe_load((ROOT / "tests" / "fixtures" / "declarations" / "valid-structured.yml").read_text(encoding="utf-8"))
        base["name"] = "skill-alpha"; base["quantSkills"]["repository"] = "skill-alpha"; base["quantSkills"]["repository_url"] = "https://github.com/quantskills/skill-alpha"
        mutations = [
            lambda d: d["quantSkills"].update(project_type="bogus"), lambda d: d.update(description=1), lambda d: d["quantSkills"].update(status="bogus", validation_level="bogus", maintainer_type="bogus", license=1, tags="bogus", requires="bogus", platforms="bogus", summary_zh=1, summary_en=1),
            lambda d: d["quantSkills"]["catalog"].update(category="bogus", subcategory="bogus"), lambda d: d["quantSkills"]["workflow"].update(primary_stage="bogus", workflow_stages="bogus"), lambda d: d["quantSkills"].update(interface={"mode":"bogus"}),
        ]
        inventory = {"assets": ["skill-alpha"], "resources": [".github", "join", "quantskills", "registry"]}
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                declaration = copy.deepcopy(base); mutate(declaration)
                repos = [{"name": "skill-alpha", "frontmatter": declaration}, *self.repos[3:]]
                entries, resources = collect_entries(repos, {}, "audit", inventory=inventory)
                snapshot = build_snapshot(entries, resources, self.taxonomy)
                self.assertNotIn("bogus", json.dumps(snapshot))
                self.assertTrue(entries[0]["migration_issues"])
                with self.assertRaises(ValueError): collect_entries(repos, {}, "enforce", inventory=inventory)

    def test_audit_path_rejection_normalizes_same_type_values_and_template_facts(self):
        base = yaml.safe_load((ROOT / "tests" / "fixtures" / "declarations" / "valid-structured.yml").read_text(encoding="utf-8"))
        base["name"] = "skill-alpha"; base["quantSkills"]["repository"] = "skill-alpha"; base["quantSkills"]["repository_url"] = "https://github.com/quantskills/skill-alpha"
        cases = [
            ("short-description", "short", lambda d: d.update(description="short")),
            ("bogus-platform", "bogus-platform", lambda d: d["quantSkills"].update(platforms=["bogus-platform"])),
            ("bogus_tag", "bogus_tag", lambda d: d["quantSkills"].update(tags=["bogus_tag"])),
            ("bad-require", "bad-require", lambda d: d["quantSkills"].update(requires=["bad-require"])),
        ]
        inventory = {"assets": ["skill-alpha"], "resources": [".github", "join", "quantskills", "registry"]}
        for token, forbidden, mutate in cases:
            with self.subTest(token=token):
                declaration = copy.deepcopy(base); mutate(declaration)
                repos = [{"name": "skill-alpha", "frontmatter": declaration}, *self.repos[3:]]
                entries, resources = collect_entries(repos, {}, "audit", inventory=inventory)
                snapshot = build_snapshot(entries, resources, self.taxonomy)
                self.assertNotIn(forbidden, json.dumps(snapshot))
                self.assertTrue(entries[0]["migration_issues"])
                with self.assertRaises(ValueError): collect_entries(repos, {}, "enforce", inventory=inventory)
        template = yaml.safe_load((ROOT / "tests" / "fixtures" / "declarations" / "valid-not-applicable.yml").read_text(encoding="utf-8"))
        template["quantSkills"]["catalog"] = {"category": "bogus", "subcategory": "bogus"}; template["quantSkills"]["workflow"] = {"primary_stage": "bogus", "workflow_stages": ["bogus"]}
        repos = [{"name": "agent-template", "frontmatter": template}, *self.repos[3:]]
        entries, _ = collect_entries(repos, {}, "audit", inventory={"assets": ["agent-template"], "resources": [".github", "join", "quantskills", "registry"]})
        self.assertEqual(entries[0]["catalog"], {"category": "10", "subcategory": "10.agent-template"})
        self.assertEqual(entries[0]["workflow"]["primary_stage"], "orchestration")

    def test_builder_fixture_declarations_have_no_contract_issues(self):
        from catalog_contract import validate_asset_semantics, validate_frontmatter_schema
        schema = ROOT / "schema" / "frontmatter.schema.json"
        for name, declaration in json.loads((ROOT / "tests" / "fixtures" / "builder" / "declarations.json").read_text(encoding="utf-8")).items():
            with self.subTest(name=name):
                self.assertEqual(validate_frontmatter_schema(declaration, schema), [])
                self.assertEqual(validate_asset_semantics(declaration, name, "AGENTS.md" if name.startswith("agent-") else "SKILL.md", self.taxonomy), [])

    def test_approved_assignments_replace_only_catalog_workflow_and_summaries(self):
        entries, _ = collect_entries(self.repos, {}, "enforce", inventory={"assets": ["agent-template", "skill-alpha", "skill-template"], "resources": [".github", "join", "quantskills", "registry"]})
        interfaces = {entry["name"]: entry["interface"] for entry in entries}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "assignments.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["name", "category", "subcategory", "primary_stage", "workflow_stages", "summary_zh", "summary_en", "review_status"])
                writer.writeheader()
                for entry in entries:
                    writer.writerow({"name": entry["name"], "category": "02", "subcategory": "02.factor-evaluation", "primary_stage": "evaluation", "workflow_stages": "evaluation", "summary_zh": "已批准简介", "summary_en": "Approved summary.", "review_status": "approved"})
            build_registry.apply_approved_assignments(entries, path)
        self.assertTrue(all(entry["summary_en"] == "Approved summary." for entry in entries))
        self.assertTrue(all(entry["catalog"] == {"category": "02", "subcategory": "02.factor-evaluation"} for entry in entries))
        self.assertEqual({entry["name"]: entry["interface"] for entry in entries}, interfaces)


if __name__ == "__main__":
    unittest.main()
