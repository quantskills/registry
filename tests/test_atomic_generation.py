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


if __name__ == "__main__":
    unittest.main()
