from pathlib import Path

from scripts.runtime_policy import RUNTIMES, evaluate_runtime_policy


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
