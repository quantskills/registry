import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_registry


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
                entries, _ = build_registry.collect_entries(repos, {}, "enforce")
            finally:
                build_registry.shallow_clone, build_registry.head_sha, build_registry.validate = original_clone, original_head, original_validate
            self.assertEqual(entries[0]["commit_sha"], "local-clone-sha")


if __name__ == "__main__":
    unittest.main()
