import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts import export_public_evaluations
from scripts.detect_evaluation_candidates import detect_evaluation_candidates
from scripts.verify_public_evaluations import verify_publication


ROOT = Path(__file__).resolve().parents[1]


def _asset(name: str, commit: str | None = None) -> dict:
    value = {"name": name}
    if commit is not None:
        value["commit_sha"] = commit
    return value


class EvaluationProjectionTests(unittest.TestCase):
    def test_expected_count_follows_public_catalog_218_to_219(self):
        assets = [_asset(f"skill-{index}") for index in range(218)]
        catalog = {"snapshot_id": "sha256:catalog", "assets": assets}
        registry = {"snapshot_id": "sha256:catalog", "assets": copy.deepcopy(assets)}
        self.assertEqual(export_public_evaluations.expected_scoring_count(catalog, registry), 218)
        assets.append(_asset("skill-218"))
        registry["assets"].append(_asset("skill-218"))
        self.assertEqual(export_public_evaluations.expected_scoring_count(catalog, registry), 219)

    def test_templates_are_not_scoreable_assets(self):
        catalog = {
            "assets": [
                _asset("skill-a", "a"),
                _asset("skill-template", "t"),
                _asset("agent-template", "u"),
            ]
        }
        registry = {"assets": copy.deepcopy(catalog["assets"])}
        self.assertEqual(
            export_public_evaluations.expected_scoring_asset_ids(catalog, registry),
            {"skill-a"},
        )

    def test_candidate_diff_is_new_changed_and_offline_and_idempotent(self):
        catalog = {
            "snapshot_id": "sha256:new-catalog",
            "assets": [_asset("skill-a", "new-a"), _asset("skill-b", "b")],
        }
        registry = {"snapshot_id": "sha256:new-catalog", "assets": copy.deepcopy(catalog["assets"])}
        current = {
            "catalog_snapshot_id": "sha256:old-catalog",
            "records": [
                {"asset_id": "skill-a", "commit_sha": "old-a", "score_formula": "score-formula.v9"},
                {"asset_id": "skill-offline", "commit_sha": "gone", "score_formula": "score-formula.v9"},
            ],
        }
        result = detect_evaluation_candidates(catalog, registry, current)
        self.assertEqual([row["asset_id"] for row in result["new"]], ["skill-b"])
        self.assertEqual([row["asset_id"] for row in result["commit_changed"]], ["skill-a"])
        self.assertEqual([row["asset_id"] for row in result["offline"]], ["skill-offline"])
        self.assertEqual(result, detect_evaluation_candidates(catalog, registry, current))
        self.assertTrue(all(row["idempotency_key"].startswith("sha256:") for key in ("new", "commit_changed", "offline") for row in result[key]))

    def test_offline_records_are_history_only(self):
        expected = {"skill-a"}
        current = {
            "skill-a": {"asset_id": "skill-a"},
            "skill-offline": {"asset_id": "skill-offline"},
        }
        projected = export_public_evaluations.project_current_records(current, expected)
        self.assertEqual([row["asset_id"] for row in projected], ["skill-a"])

    def test_mixed_formula_cohort_fails_closed(self):
        records = [
            {"asset_id": "skill-a", "score_formula": "score-formula.v9"},
            {"asset_id": "skill-b", "score_formula": "score-formula.v10"},
        ]
        with self.assertRaisesRegex(ValueError, "mixed score formula cohort"):
            export_public_evaluations.validate_scoring_cohort(records)

    def test_verifier_and_schema_accept_a_219_asset_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "evaluations", root / "evaluations")
            catalog = json.loads((ROOT / "catalog.snapshot.json").read_text(encoding="utf-8"))
            registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
            template_names = {"agent-template", "skill-template"}
            catalog["assets"] = [row for row in catalog["assets"] if row["name"] not in template_names]
            scores = json.loads((root / "evaluations" / "current-scores.json").read_text(encoding="utf-8"))
            new_id = "skill-evaluation-new"
            new_record = copy.deepcopy(scores["records"][0])
            new_record.update({
                "asset_id": new_id,
                "repo": f"quantskills/{new_id}",
                "commit_sha": "c" * 40,
                "source_request_id": "1" * 64,
            })
            new_record["metrics"]["reliability"] = 0
            scores["records"].append(new_record)
            scores["records"].sort(key=lambda row: row["asset_id"])
            catalog["assets"].extend([
                {"name": "skill-a-share-placement-discount-alpha", "commit_sha": "p" * 40},
                {"name": new_id, "commit_sha": "c" * 40},
            ])
            registry = [row for row in registry if row["name"] not in template_names]
            registry.extend([
                {"name": "skill-a-share-placement-discount-alpha", "commit_sha": "p" * 40},
                {"name": new_id, "commit_sha": "c" * 40},
            ])

            def stable(value):
                if isinstance(value, dict):
                    return {key: stable(item) for key, item in value.items() if key not in {"snapshot_id", "generated_at", "validated_at", "scan_time", "last_validated"}}
                if isinstance(value, list):
                    return [stable(item) for item in value]
                return value

            catalog["snapshot_id"] = "sha256:" + hashlib.sha256(export_public_evaluations.canonical(stable(catalog))).hexdigest()
            for row in registry:
                row["snapshot_id"] = catalog["snapshot_id"]
            scores.update({"record_count": 219, "historical_observation_count": 225, "catalog_snapshot_id": catalog["snapshot_id"]})
            (root / "evaluations" / "current-scores.json").write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (root / "catalog.snapshot.json").write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            (root / "registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            history_path = root / "evaluations" / "publications" / "publication.v12.23.jsonl"
            with history_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(export_public_evaluations.canonical(new_record).decode("utf-8") + "\n")
            recommended_path = root / "evaluations" / "recommended.snapshot.json"
            recommended = json.loads(recommended_path.read_text(encoding="utf-8"))
            recommended["catalog_snapshot_id"] = catalog["snapshot_id"]
            recommended["score_dataset_sha256"] = hashlib.sha256((root / "evaluations" / "current-scores.json").read_bytes()).hexdigest()
            recommended_path.write_text(json.dumps(recommended, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest_path = root / "evaluations" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["catalog_snapshot_id"] = catalog["snapshot_id"]
            manifest["record_count"] = 219
            manifest["historical_observation_count"] = 225
            manifest["publications"] = [
                {**row, "observation_count": 2 if row["publication"] == "publication.v12.23" else row["observation_count"]}
                for row in manifest["publications"]
            ]
            for path in (root / "evaluations").rglob("*"):
                if path.is_file() and path.name != "manifest.json":
                    manifest["files"][path.relative_to(root / "evaluations").as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest["snapshot_digest"] = export_public_evaluations.digest({key: value for key, value in manifest.items() if key != "snapshot_digest"})
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            dataset_schema = json.loads((root / "evaluations" / "schemas" / "current-scores.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator(dataset_schema).validate(scores)
            result = verify_publication(root)
            self.assertEqual(result["records"], 219)

    def test_verifier_rejects_score_count_or_asset_set_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "evaluations", root / "evaluations")
            shutil.copy2(ROOT / "catalog.snapshot.json", root / "catalog.snapshot.json")
            shutil.copy2(ROOT / "registry.json", root / "registry.json")
            path = root / "evaluations" / "current-scores.json"
            dataset = json.loads(path.read_text(encoding="utf-8"))
            dataset["records"].pop()
            dataset["record_count"] = len(dataset["records"])
            path.write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "asset set mismatch"):
                verify_publication(root)

    def test_atomic_promotion_failure_preserves_old_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evaluations"
            stage = root / "stage"
            output.mkdir()
            stage.mkdir()
            old = {
                "current-scores.json": b"old-current\n",
                "manifest.json": b"old-manifest\n",
            }
            new = {
                "current-scores.json": b"new-current\n",
                "manifest.json": b"new-manifest\n",
                "publications/publication.v12.13.jsonl": b"new-history\n",
            }
            for relative, content in old.items():
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            for relative, content in new.items():
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            original_replace = export_public_evaluations.os.replace
            calls = 0

            def fail_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected replacement failure")
                return original_replace(source, destination)

            export_public_evaluations.os.replace = fail_second
            try:
                with self.assertRaises(OSError):
                    export_public_evaluations.promote_evaluation_artifacts(
                        stage, output, tuple(new),
                    )
            finally:
                export_public_evaluations.os.replace = original_replace
            self.assertEqual((output / "current-scores.json").read_bytes(), old["current-scores.json"])
            self.assertEqual((output / "manifest.json").read_bytes(), old["manifest.json"])
            self.assertFalse((output / "publications/publication.v12.13.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
