import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.export_public_evaluations import canonical, digest, select_recommendations
from scripts.verify_public_evaluations import verify_publication


ROOT = Path(__file__).resolve().parents[1]


class PublicEvaluationTests(unittest.TestCase):
    def test_canonical_json_is_stable(self):
        left = {"b": 2, "a": {"z": 3, "y": 1}}
        right = {"a": {"y": 1, "z": 3}, "b": 2}
        self.assertEqual(canonical(left), canonical(right))
        self.assertEqual(hashlib.sha256(canonical(left)).hexdigest(), hashlib.sha256(canonical(right)).hexdigest())

    def test_recommendations_are_top_quartile_and_exclude_regressions(self):
        rows = []
        for index, score in enumerate((91, 88, 84, 80, 76, 72, 68, 64), start=1):
            rows.append({
                "asset_id": f"skill-{index}",
                "kind": "skill",
                "category": "01",
                "scores": {"total": score},
                "security": {"status": "pass"},
                "metrics": {"reliability": 100},
                "featured": {"material_core_regression_count": 0},
                "source_publication": "publication.v12.13",
            })
        rows[0]["featured"]["material_core_regression_count"] = 1
        selected = select_recommendations(rows, {row["asset_id"] for row in rows})
        self.assertEqual([row["asset_id"] for row in selected], ["skill-2", "skill-3"])

    def test_committed_publication_verifies(self):
        result = verify_publication(ROOT)
        self.assertEqual(result["records"], 218)
        self.assertEqual(result["observations"], 224)
        self.assertGreater(result["recommended"], 0)

    def test_public_files_use_portable_lf_bytes(self):
        paths = list((ROOT / "evaluations").rglob("*.json"))
        paths.extend((ROOT / "evaluations" / "publications").glob("*.jsonl"))
        for path in paths:
            content = path.read_bytes()
            self.assertNotIn(b"\r\n", content, path)
            self.assertTrue(content.endswith(b"\n"), path)

    def test_v1213_roots_are_pinned_beyond_manifest_self_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "evaluations", root / "evaluations")
            shutil.copy2(ROOT / "catalog.snapshot.json", root / "catalog.snapshot.json")
            shutil.copy2(ROOT / "registry.json", root / "registry.json")
            path = root / "evaluations" / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            publication = next(row for row in manifest["publications"] if row["publication"] == "publication.v12.13")
            publication["score_rows_root"] = "0" * 64
            manifest["snapshot_digest"] = digest({key: value for key, value in manifest.items() if key != "snapshot_digest"})
            path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable roots"):
                verify_publication(root)


if __name__ == "__main__":
    unittest.main()
