"""SKILL.md skill system: parsing, caching, trigger matching, prompt building."""
import pytest

from app.core.skills import loader as skills_mod


SKILL_A = """---
name: release-check
description: 发布前的检查清单
triggers:
  - 发布
  - 上线检查
---

# 发布检查手册

1. 跑全量测试
2. 确认契约检查通过
"""

SKILL_B = """---
name: sql-review
description: SQL 变更审阅规范
triggers:
  - sql 变更
---

审阅任何 DDL 时先检查索引与回滚语句。
"""


@pytest.fixture()
def skills_dir(tmp_path, monkeypatch):
    (tmp_path / "release-check").mkdir()
    (tmp_path / "release-check" / "SKILL.md").write_text(SKILL_A, encoding="utf-8")
    (tmp_path / "sql-review").mkdir()
    (tmp_path / "sql-review" / "SKILL.md").write_text(SKILL_B, encoding="utf-8")
    monkeypatch.setattr(skills_mod.settings, "skills_dir", str(tmp_path))
    monkeypatch.setattr(skills_mod.settings, "skills_enabled", True)
    skills_mod._cache.clear()
    skills_mod._last_scan = 0.0
    return tmp_path


def test_load_skills_parses_frontmatter_and_body(skills_dir):
    skills = skills_mod.load_skills(force=True)
    names = [s.name for s in skills]
    assert names == ["release-check", "sql-review"]
    release = skills[0]
    assert "发布前的检查清单" in release.description
    assert "发布" in release.triggers
    assert "跑全量测试" in release.body


def test_load_skills_skips_malformed_files(skills_dir):
    (skills_dir / "broken").mkdir()
    (skills_dir / "broken" / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    skills = skills_mod.load_skills(force=True)
    assert "broken" not in [s.name for s in skills]


def test_disabled_skills_return_empty(skills_dir, monkeypatch):
    monkeypatch.setattr(skills_mod.settings, "skills_enabled", False)
    assert skills_mod.load_skills(force=True) == []


def test_match_by_trigger_and_slash_name(skills_dir):
    skills = skills_mod.load_skills(force=True)
    by_trigger = skills_mod.match_skills("帮我做一次上线检查", skills)
    assert [s.name for s in by_trigger] == ["release-check"]
    by_slash = skills_mod.match_skills("/sql-review 请审这个迁移", skills)
    assert [s.name for s in by_slash] == ["sql-review"]
    assert skills_mod.match_skills("今天天气怎么样", skills) == []


def test_build_prompt_injects_only_triggered_manual(skills_dir):
    prompt = skills_mod.build_skill_prompt("准备发布，先做上线检查")
    assert "可用技能" in prompt
    assert "发布检查手册" in prompt          # triggered body injected
    assert "审阅任何 DDL" not in prompt      # untriggered body withheld
    assert "sql-review" in prompt            # but its index entry is present


def test_build_prompt_empty_when_no_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_mod.settings, "skills_dir", str(tmp_path / "nope"))
    skills_mod._cache.clear()
    skills_mod._last_scan = 0.0
    assert skills_mod.build_skill_prompt("anything") == ""


@pytest.mark.asyncio
async def test_agent_loop_injects_skill_prompt(monkeypatch):
    """The chat loop wires build_skill_prompt into the system message."""
    from app.core.agent import loop as loop_mod
    from tests.test_agent_loop import FakeLLM, USER, SESSION, _collect, _patch_common

    captured = {}

    class CapturingLLM(FakeLLM):
        async def astream_with_tools(self, messages, tools):
            captured["messages"] = messages
            async for e in super().astream_with_tools(messages, tools):
                yield e

    llm = CapturingLLM([[{"type": "content", "content": "ok"},
                         {"type": "finish", "finish_reason": "stop"}]])
    _patch_common(monkeypatch, llm)
    monkeypatch.setattr(
        "app.core.skills.build_skill_prompt",
        lambda msg: "## 可用技能\n- demo：示例",
    )
    await _collect(loop_mod.run_chat(USER, SESSION, "hi", []))
    assert "可用技能" in captured["messages"][0]["content"]
