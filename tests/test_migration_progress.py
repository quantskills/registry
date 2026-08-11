import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.audit_migration import audit
from scripts.record_migration import record


ROOT = Path(__file__).resolve().parents[1]


def run(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True).stdout.strip()


def fixture(tmp_path: Path):
    repo = tmp_path / "repos" / "skill-demo"; repo.mkdir(parents=True)
    repo.joinpath("SKILL.md").write_text("---\nname: skill-demo\ndescription: old\n---\n", encoding="utf-8")
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    for key, value in (("user.name", "abgyjaguo"), ("user.email", "213890245+abgyjaguo@users.noreply.github.com")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    run(repo, "add", "."); run(repo, "commit", "-m", "initial")
    frozen = run(repo, "rev-parse", "HEAD")
    valid = (ROOT / "tests" / "fixtures" / "declarations" / "valid-structured.yml").read_text(encoding="utf-8").replace("skill-factor-grouped-wrapper", "skill-demo")
    repo.joinpath("SKILL.md").write_text("---\n" + valid + "\n---\nbody\n", encoding="utf-8")
    cursor = repo / ".cursor" / "rules"; cursor.mkdir(parents=True); cursor.joinpath("loader.mdc").write_text("# loader\n", encoding="utf-8")
    run(repo, "add", "."); run(repo, "commit", "-m", "chore(catalog): adopt declaration contract v2")
    inventory = tmp_path / "inventory.json"; inventory.write_text(json.dumps({"assets": [{"name": "skill-demo", "head_sha": frozen, "declaration": {"file": "SKILL.md"}}]}), encoding="utf-8")
    assignments = tmp_path / "assignments.csv"; assignments.write_text("name,project_type\nskill-demo,skill\n", encoding="utf-8")
    interfaces = tmp_path / "interfaces.json"; interfaces.write_text(json.dumps({"items": [{"name": "skill-demo"}]}), encoding="utf-8")
    return repo, inventory, assignments, interfaces


def test_ancestor_without_progress_record_is_rejected(tmp_path: Path):
    repo, inventory, assignments, interfaces = fixture(tmp_path)
    result = audit(inventory, assignments, interfaces, repo.parent, tmp_path / "progress")
    assert any(x["check"] == "frozen-head" for x in result["findings"])


def test_verified_record_allows_migrated_head_and_rejects_forgery(tmp_path: Path):
    repo, inventory, assignments, interfaces = fixture(tmp_path); progress = tmp_path / "progress"
    written = record(inventory, "skill-demo", repo, progress)
    result = audit(inventory, assignments, interfaces, repo.parent, progress)
    assert result["assets"] == {"numerator": 1, "denominator": 1}
    data = json.loads(written.read_text(encoding="utf-8")); data["after_sha"] = data["before_sha"]
    written.write_text(json.dumps(data), encoding="utf-8")
    assert any(x["check"] == "frozen-head" for x in audit(inventory, assignments, interfaces, repo.parent, progress)["findings"])


@pytest.mark.parametrize("kind", ["dirty", "runtime", "contract"])
def test_record_rejects_unverified_worktree(tmp_path: Path, kind: str):
    repo, inventory, _, _ = fixture(tmp_path)
    if kind == "dirty": repo.joinpath("dirty.txt").write_text("x", encoding="utf-8")
    elif kind == "runtime": (repo / ".cursor" / "rules" / "loader.mdc").unlink()
    else: repo.joinpath("SKILL.md").write_text("---\nname: skill-demo\n---\n", encoding="utf-8")
    with pytest.raises(ValueError): record(inventory, "skill-demo", repo, tmp_path / "progress")


def test_duplicate_symlink_and_escape_records_fail_closed(tmp_path: Path):
    repo, inventory, assignments, interfaces = fixture(tmp_path); progress = tmp_path / "progress"
    written = record(inventory, "skill-demo", repo, progress)
    duplicate = progress / "copy.json"; duplicate.write_bytes(written.read_bytes())
    assert any(x["check"] == "progress" for x in audit(inventory, assignments, interfaces, repo.parent, progress)["findings"])
    duplicate.unlink(); written.unlink(); outside = tmp_path / "outside.json"; outside.write_text("{}", encoding="utf-8")
    try:
        os.symlink(outside, progress / "skill-demo.json")
    except OSError:
        pytest.skip("symlinks unavailable")
    assert any(x["check"] == "progress" for x in audit(inventory, assignments, interfaces, repo.parent, progress)["findings"])
    with pytest.raises(ValueError): record(inventory, "../escape", repo, progress)
