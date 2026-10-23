"""Repo rules loading and system-prompt injection."""
from app.core.agent.rules import load_repo_rules
from app.core.memory.context import build_system_prompt


def test_load_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# 规则\n- 使用 pytest", encoding="utf-8")
    rules = load_repo_rules([{"name": "demo", "root_path": str(tmp_path), "rules": ""}])
    assert rules == [{"repo": "demo", "source": "AGENTS.md", "content": "# 规则\n- 使用 pytest"}]


def test_load_falls_back_to_stored_rules(tmp_path):
    rules = load_repo_rules([{"name": "builder", "root_path": str(tmp_path), "rules": "只生成 Python"}])
    assert rules[0]["source"] == "项目约定"
    assert "只生成 Python" in rules[0]["content"]


def test_claude_md_adapter(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("use ruff", encoding="utf-8")
    rules = load_repo_rules([{"name": "demo", "root_path": str(tmp_path), "rules": ""}])
    assert rules[0]["source"] == "CLAUDE.md"


def test_rules_injected_into_system_prompt(tmp_path):
    (tmp_path / "AGENTS.md").write_text("所有接口必须写测试", encoding="utf-8")
    rules = load_repo_rules([{"name": "demo", "root_path": str(tmp_path), "rules": ""}])
    prompt = build_system_prompt([], [], repo_selected=True, repos=[{"id": "r1", "name": "demo"}], rules=rules)
    assert "仓库项目约定" in prompt
    assert "所有接口必须写测试" in prompt
