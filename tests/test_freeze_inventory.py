import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from freeze_inventory import canonical_bytes, freeze_inventory, freeze_repositories


class FreezeInventoryTests(unittest.TestCase):
    def test_fixture_freeze_is_sorted_closed_and_hashed(self):
        fixture = json.loads((ROOT / "tests/fixtures/inventory/github-repos.json").read_text(encoding="utf-8"))
        calls = []
        def request(url):
            calls.append(url)
            return fixture[url]
        inventory = freeze_inventory(request, "https://api.github.test", "quantskills", {"skill": 1, "agent": 1, "resource": 4})
        self.assertEqual([item["name"] for item in inventory["assets"]], ["agent-beta", "skill-alpha"])
        self.assertEqual([item["name"] for item in inventory["resources"]], [".github", "join", "quantskills", "registry"])
        self.assertTrue(all({"name", "default_branch", "head_sha", "declaration", "description", "topics"} <= set(item) for item in inventory["assets"]))
        self.assertEqual(inventory["sha256"], "sha256:" + hashlib.sha256(canonical_bytes({key: value for key, value in inventory.items() if key != "sha256"})).hexdigest())
        self.assertTrue(any("page=2" in url for url in calls))

    def test_wrong_live_counts_fail_closed_without_inventory(self):
        fixture = json.loads((ROOT / "tests/fixtures/inventory/github-repos.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "unexpected repository counts"):
            freeze_inventory(lambda url: [], "https://api.github.test", "wrong-org")

    def test_gh_backend_closes_default_branch_and_redacts_missing_head(self):
        repos = [{"name": name, "defaultBranchRef": {"name": "main"}, "isArchived": False, "isFork": False, "visibility": "PUBLIC", "description": "x", "repositoryTopics": {"nodes": []}} for name in ("skill-alpha", "agent-beta", ".github", "join", "quantskills", "registry")]
        inventory = freeze_repositories(repos, "quantskills", lambda name, branch: "a" * 40, {"skill": 1, "agent": 1, "resource": 4})
        self.assertEqual(inventory["assets"][0]["declaration"]["url"], "https://github.com/quantskills/agent-beta/blob/" + "a" * 40 + "/AGENTS.md")
        with self.assertRaisesRegex(ValueError, "missing target HEAD"):
            freeze_repositories(repos, "quantskills", lambda name, branch: "", {"skill": 1, "agent": 1, "resource": 4})

    def test_live_replacement_name_is_selected_and_deleted_name_is_excluded(self):
        repos = [{"name": name, "defaultBranchRef": {"name": "main"}, "isArchived": False, "isFork": False, "visibility": "PUBLIC", "description": "", "repositoryTopics": []} for name in ("skill-factor-mason", "agent-beta", ".github", "join", "quantskills", "registry")]
        inventory = freeze_repositories(repos, "quantskills", lambda name, branch: "0" * 40, {"skill": 1, "agent": 1, "resource": 4})
        self.assertEqual([item["name"] for item in inventory["assets"]], ["agent-beta", "skill-factor-mason"])
        self.assertNotIn("skill-commodity-brief", [item["name"] for item in inventory["assets"]])


if __name__ == "__main__":
    unittest.main()
