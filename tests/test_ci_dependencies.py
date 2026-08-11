import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class CiDependencyTests(unittest.TestCase):
    def test_unittest_discovery_dependencies_are_declared(self):
        requirements = {
            line.partition("==")[0].partition(">=")[0].partition("<=")[0].strip().lower()
            for line in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("pytest", requirements)


if __name__ == "__main__":
    unittest.main()
