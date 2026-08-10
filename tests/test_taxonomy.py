import json
import unittest
from pathlib import Path


TAXONOMY_PATH = Path(__file__).parents[1] / "schema" / "taxonomy.v1.json"


class TaxonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TAXONOMY_PATH.open(encoding="utf-8") as handle:
            cls.data = json.load(handle)

    def test_taxonomy_shape(self):
        data = self.data
        self.assertEqual(data["schema_version"], "1.0.0")
        self.assertEqual(list(data["categories"]), [f"{i:02d}" for i in range(1, 11)])
        self.assertEqual(sum(len(v["subcategories"]) for v in data["categories"].values()), 61)
        self.assertEqual(len(data["workflow_stages"]), 14)
        self.assertEqual(set(data["workflow_groups"]), {
            "data-foundation", "research-signal", "portfolio-validation",
            "monitoring-trading", "orchestration",
        })

    def test_subcategory_ids_are_prefixed_and_unique(self):
        subcategory_ids = []
        for category_id, category in self.data["categories"].items():
            for subcategory in category["subcategories"]:
                subcategory_id = subcategory["id"]
                self.assertTrue(subcategory_id.startswith(f"{category_id}."))
                subcategory_ids.append(subcategory_id)
        self.assertEqual(len(subcategory_ids), len(set(subcategory_ids)))

    def test_each_stage_is_in_exactly_one_group(self):
        stages = self.data["workflow_stages"]
        grouped_stages = [
            stage
            for group_stages in self.data["workflow_groups"].values()
            for stage in group_stages
        ]
        self.assertEqual(set(grouped_stages), set(stages))
        self.assertEqual(len(grouped_stages), len(stages))

    def test_category_09_label(self):
        self.assertEqual(self.data["categories"]["09"]["label_zh"], "量化智能体与自动化")


if __name__ == "__main__":
    unittest.main()
