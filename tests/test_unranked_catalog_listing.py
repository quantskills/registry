import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from jsonschema import Draft202012Validator
from scripts.build_registry import publication_manifest
from scripts.detect_evaluation_candidates import detect_evaluation_candidates
from scripts.export_public_evaluations import expected_scoring_asset_ids


class UnrankedCatalogListingTests(unittest.TestCase):
    def assets(self):
        return [{"name": "skill-existing", "commit_sha": "a" * 40},
                {"name": "skill-new", "commit_sha": "b" * 40,
                 "current_ranking_eligible": False}]

    def test_new_listing_does_not_require_a_fabricated_old_model_score(self):
        assets = self.assets()
        self.assertEqual(expected_scoring_asset_ids({"assets": assets}, assets), {"skill-existing"})

    def test_unranked_listing_still_generates_evaluation_work(self):
        assets = self.assets()
        result = detect_evaluation_candidates(
            {"assets": assets}, assets,
            {"records": [{"asset_id": "skill-existing", "commit_sha": "a" * 40,
                          "score_formula": "score-formula.v9"}]})
        self.assertEqual([r["asset_id"] for r in result["new"]], ["skill-new"])

    def test_ranking_marker_must_be_boolean(self):
        assets = self.assets()
        assets[1]["current_ranking_eligible"] = "false"
        with self.assertRaises(ValueError):
            expected_scoring_asset_ids({"assets": assets}, assets)

    def test_catalog_schema_accepts_explicit_unranked_asset(self):
        catalog = json.loads((ROOT / "catalog.snapshot.json").read_text(encoding="utf-8"))
        catalog["assets"][0]["current_ranking_eligible"] = False
        schema = json.loads((ROOT / "schema/catalog-snapshot.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(catalog)), [])

    def test_frozen_inventory_ranking_marker_survives_generation(self):
        entries = [{"name": "skill-new", "commit_sha": "b" * 40}]
        inventory = {"assets": [{"name": "skill-new", "default_branch": "main",
                                 "current_ranking_eligible": False}], "sha256": "sha256:" + "c" * 64}
        publication_manifest(entries, inventory, ROOT / "migration/catalog-assignments-2026-08-29-reviewed.csv")
        self.assertIs(entries[0].get("current_ranking_eligible"), False)


if __name__ == "__main__":
    unittest.main()
