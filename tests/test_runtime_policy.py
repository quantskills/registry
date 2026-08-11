from pathlib import Path

import pytest

from scripts.runtime_policy import RUNTIMES, evaluate_runtime_policy


def _row(rows, runtime):
    return next(row for row in rows if row["runtime"] == runtime)


def _skill_entry(root: Path, body: str = ""):
    (root / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo skill entry for offline runtime discovery.\n---\n" + body,
        encoding="utf-8",
    )


def test_runtime_policy_has_all_supported_runtimes(tmp_path: Path):
    (tmp_path / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "skill")
    assert [row["runtime"] for row in rows] == list(RUNTIMES)
    assert next(row for row in rows if row["runtime"] == "Codex")["status"] == "pass"
    assert next(row for row in rows if row["runtime"] == "Cursor")["status"] == "needs-review"


def test_runtime_policy_uses_openai_yaml_not_a_directory(tmp_path: Path):
    (tmp_path / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    agents = tmp_path / "agents"; agents.mkdir(); (agents / "openai").mkdir()
    assert next(row for row in evaluate_runtime_policy(tmp_path, "skill") if row["runtime"] == "Codex")["evidence"] == ["SKILL.md"]
    (agents / "openai.yaml").write_text("entrypoint: SKILL.md\n", encoding="utf-8")
    assert "agents/openai.yaml" in next(row for row in evaluate_runtime_policy(tmp_path, "skill") if row["runtime"] == "Codex")["evidence"]


def test_runtime_policy_cursor_requires_real_rule_path(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
    loader = tmp_path / ".cursor" / "rules"; loader.mkdir(parents=True); (loader / "skill.mdc").write_text("loader", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "agent")
    assert next(row for row in rows if row["runtime"] == "Cursor")["status"] == "pass"


def test_agent_claude_needs_claude_loader_and_loader_links_are_checked(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# agent\n[bad](../escape.md)\n", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "agent")
    claude = next(row for row in rows if row["runtime"] == "Claude Code")
    assert claude["status"] == "needs-review"
    assert "escapes root" in claude["detail"]


def test_pseudo_hermes_and_openclaw_files_are_not_discovery_entries(tmp_path: Path):
    (tmp_path / "HERMES.md").write_text("# pseudo\n", encoding="utf-8")
    (tmp_path / "OPENCLAW.md").write_text("# pseudo\n", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "skill")
    for runtime in ("Hermes", "OpenClaw"):
        row = _row(rows, runtime)
        assert row["status"] == "fail"
        assert row["evidence"] == []


def test_root_skill_is_the_hermes_and_openclaw_install_entry(tmp_path: Path):
    _skill_entry(tmp_path, "See [references](references.md).\n")
    (tmp_path / "references.md").write_text("reference\n", encoding="utf-8")
    (tmp_path / "HERMES.md").write_text("# pseudo\n", encoding="utf-8")
    (tmp_path / "OPENCLAW.md").write_text("# pseudo\n", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "skill")
    for runtime in ("Hermes", "OpenClaw"):
        row = _row(rows, runtime)
        assert row["status"] == "pass"
        assert row["evidence"] == ["SKILL.md"]


def test_root_skill_install_entry_requires_name_and_description(tmp_path: Path):
    (tmp_path / "SKILL.md").write_text("---\nname: demo-skill\n---\n", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "skill")
    for runtime in ("Hermes", "OpenClaw"):
        row = _row(rows, runtime)
        assert row["status"] == "fail"
        assert "description" in row["detail"]


def test_agent_portable_loader_alone_is_not_a_native_skill_entry(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
    loader = tmp_path / "agents"; loader.mkdir()
    (loader / "portable-loader.md").write_text("Read AGENTS.md.\n", encoding="utf-8")
    rows = evaluate_runtime_policy(tmp_path, "agent")
    for runtime in ("Hermes", "OpenClaw"):
        row = _row(rows, runtime)
        assert row["status"] == "needs-review"
        assert "portable-loader.md" in row["detail"]
        assert row["evidence"] == ["AGENTS.md"]


def test_agent_root_skill_wrapper_points_to_canonical_agents(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
    (tmp_path / "SKILL.md").write_text(
        "---\nname: agent-wrapper\ndescription: Thin install wrapper for the canonical agent instructions.\n---\n"
        "Read [AGENTS.md](AGENTS.md).\n",
        encoding="utf-8",
    )
    rows = evaluate_runtime_policy(tmp_path, "agent")
    for runtime in ("Hermes", "OpenClaw"):
        row = _row(rows, runtime)
        assert row["status"] == "pass"
        assert row["evidence"] == ["AGENTS.md", "SKILL.md"]


@pytest.mark.parametrize(
    ("body", "extra", "needle"),
    [
        ("No canonical pointer.\n", "", "must reference"),
        ("Read [AGENTS.md](../AGENTS.md).\n", "", "escapes root"),
        ("Read [AGENTS.md](AGENTS.md).\n", "allowed-tools: [Read]\n", "fields not allowed"),
    ],
)
def test_agent_wrapper_is_closed_and_safe(tmp_path: Path, body: str, extra: str, needle: str):
    (tmp_path / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
    (tmp_path / "SKILL.md").write_text(
        "---\nname: agent-wrapper\ndescription: Thin install wrapper for the canonical agent instructions.\n"
        + extra
        + "---\n"
        + body,
        encoding="utf-8",
    )
    rows = evaluate_runtime_policy(tmp_path, "agent")
    for runtime in ("Hermes", "OpenClaw"):
        row = _row(rows, runtime)
        assert row["status"] == "fail"
        assert needle in row["detail"]


def test_cursor_ignores_legacy_agents_rule_path(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# agent\n", encoding="utf-8")
    legacy = tmp_path / "agents"; legacy.mkdir()
    (legacy / "cursor-rule.mdc").write_text("AGENTS.md\n", encoding="utf-8")
    assert _row(evaluate_runtime_policy(tmp_path, "agent"), "Cursor")["status"] == "needs-review"
