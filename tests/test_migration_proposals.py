import csv
import json
from pathlib import Path

import pytest
import yaml

from scripts.audit_migration import audit
from scripts.catalog_contract import (load_taxonomy, validate_asset_semantics,
                                      validate_frontmatter_schema)
from scripts.render_migration_proposals import OUTPUT_FILES, generate


ROOT = Path(__file__).resolve().parents[1]


def _inputs(tmp_path: Path, malformed: bool = False, mode: str = "structured"):
    workspace = tmp_path / "repos"; repo = workspace / "skill-demo"; repo.mkdir(parents=True)
    (repo / "SKILL.md").write_text("---\nname: [bad\n---\n", encoding="utf-8") if malformed else (repo / "SKILL.md").write_text("---\ndescription: trigger token=super-secret-value\n---\n", encoding="utf-8")
    inventory = tmp_path / "inventory.json"; inventory.write_text(json.dumps({"assets": [{"name": "skill-demo", "declaration": {"file": "SKILL.md"}}]}), encoding="utf-8")
    assignments = tmp_path / "assignments.csv"
    with assignments.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "project_type", "category", "subcategory", "primary_stage", "workflow_stages", "summary_zh", "summary_en", "interface_candidate", "review_status"])
        writer.writeheader(); writer.writerow({"name": "skill-demo", "project_type": "skill", "category": "02", "subcategory": "02.factor-selection", "primary_stage": "factor-screening", "workflow_stages": "factor-screening|evaluation", "summary_zh": "用于因子筛选和评估的研究工作流", "summary_en": "Structured workflow for factor screening and evaluation.", "interface_candidate": mode, "review_status": "approved"})
    notes = "orchestration-only" if mode == "not-applicable" else "token=leak-me"
    interfaces = tmp_path / "interfaces.json"; interfaces.write_text(json.dumps({"items": [{"name": "skill-demo", "candidate_mode": mode, "notes": notes}]}), encoding="utf-8")
    waves = tmp_path / "waves.json"; waves.write_text(json.dumps({"waves": {"test": ["skill-demo"]}}), encoding="utf-8")
    return inventory, assignments, interfaces, waves, workspace


def test_proposals_are_review_only_and_redacted(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path)
    before = (workspace / "skill-demo" / "SKILL.md").read_bytes(); output = tmp_path / "report"
    generate(inventory, assignments, interfaces, waves, workspace, output)
    proposal = output / "skill-demo"
    assert {p.name for p in proposal.iterdir()} == set(OUTPUT_FILES)
    assert (workspace / "skill-demo" / "SKILL.md").read_bytes() == before
    assert "super-secret-value" not in "".join(p.read_text(encoding="utf-8") for p in proposal.iterdir())


def test_malformed_yaml_is_review_item_without_patch(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path, malformed=True)
    output = tmp_path / "report"; generate(inventory, assignments, interfaces, waves, workspace, output)
    assert "malformed YAML" in (output / "skill-demo" / "readme-review.md").read_text(encoding="utf-8")
    assert "No patch" in (output / "skill-demo" / "declaration.diff").read_text(encoding="utf-8")


def test_audit_has_exact_denominators(tmp_path: Path):
    inventory, assignments, interfaces, _, workspace = _inputs(tmp_path)
    result = audit(inventory, assignments, interfaces, workspace)
    assert result["assets"]["denominator"] == 1
    assert result["runtime"]["denominator"] == 5


def test_malicious_inventory_name_cannot_escape_output(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path)
    inventory.write_text(json.dumps({"assets": [{"name": "../escape"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid asset name"):
        generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")


def test_clean_declaration_has_actionable_diff_and_preserves_body(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path, mode="natural-language")
    source = workspace / "skill-demo" / "SKILL.md"
    source.write_text("---\ndescription: useful trigger\n---\n\nBody stays unchanged.\n", encoding="utf-8")
    generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")
    proposal = (tmp_path / "report" / "skill-demo" / "frontmatter.proposed.yml").read_text(encoding="utf-8")
    diff = (tmp_path / "report" / "skill-demo" / "declaration.diff").read_text(encoding="utf-8")
    assert "quantSkills:" in proposal and "schema_version: 2.0.0" in proposal
    assert "GPL-3.0-only" in proposal and "abgyjaguo" in proposal
    assert "@@" in diff and "Body stays unchanged." in diff


@pytest.mark.parametrize("mode", ["natural-language", "not-applicable"])
def test_non_structured_proposals_pass_real_declaration_validators(tmp_path: Path, mode: str):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path, mode=mode)
    generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")
    proposal = yaml.safe_load((tmp_path / "report" / "skill-demo" / "frontmatter.proposed.yml").read_text(encoding="utf-8"))
    assert validate_frontmatter_schema(proposal, ROOT / "schema" / "frontmatter.schema.json") == []
    assert validate_asset_semantics(proposal, "skill-demo", "SKILL.md", load_taxonomy(ROOT)) == []
    assert proposal["quantSkills"]["interface"] == ({"mode": mode} if mode == "natural-language" else {"mode": mode, "reason": "orchestration-only"})


@pytest.mark.parametrize("mode", ["structured", "hybrid"])
def test_structured_candidates_without_profile_endpoints_fail_closed(tmp_path: Path, mode: str):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path, mode=mode)
    generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")
    proposal = tmp_path / "report" / "skill-demo"
    assert (proposal / "declaration.diff").read_text(encoding="utf-8").startswith("# No patch:")
    assert "approved Profile endpoints" in (proposal / "readme-review.md").read_text(encoding="utf-8")


def test_preexisting_undeclared_output_or_symlink_fails_closed(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path)
    output = tmp_path / "report" / "skill-demo"; output.mkdir(parents=True); (output / "other.txt").write_text("x")
    with pytest.raises(ValueError, match="undeclared"):
        generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")


def test_dirty_git_repo_is_unchanged_and_has_no_patch(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path)
    repo = workspace / "skill-demo"
    import subprocess
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "changed.txt").write_text("dirty", encoding="utf-8")
    before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], check=True, capture_output=True, text=True).stdout
    source = (repo / "SKILL.md").read_bytes()
    generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")
    after = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], check=True, capture_output=True, text=True).stdout
    assert before == after and source == (repo / "SKILL.md").read_bytes()
    assert "No patch" in (tmp_path / "report" / "skill-demo" / "declaration.diff").read_text(encoding="utf-8")


def test_unapproved_assignment_has_no_patch(tmp_path: Path):
    inventory, assignments, interfaces, waves, workspace = _inputs(tmp_path)
    text = assignments.read_text(encoding="utf-8").replace("approved", "needs-maintainer")
    assignments.write_text(text, encoding="utf-8")
    generate(inventory, assignments, interfaces, waves, workspace, tmp_path / "report")
    assert "assignment not approved" in (tmp_path / "report" / "skill-demo" / "readme-review.md").read_text(encoding="utf-8")
