"""Resume domain: per-user storage, fact status gates and job versions."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.config import settings
from app.core.resume import (
    FACT_SCHEMA,
    Fact,
    JobVersion,
    Profile,
    ResumeError,
    ResumeNotFound,
    add_fact,
    create_job_version,
    create_profile,
    get_job_version,
    get_profile,
    list_facts,
    list_job_versions,
    list_profiles,
    render_job_version,
    resume_root,
    update_fact,
)


@pytest.fixture()
def user_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path / "data"))
    return tmp_path


def _profile(user_id: int = 1, name: str = "张三") -> Profile:
    return create_profile(
        user_id,
        name=name,
        headline="后端工程师",
        contact={"email": "zhangsan@example.com", "phone": "13800000000"},
    )


def _fact(user_id: int, profile_id: str, title: str = "负责支付系统重构",
          **kwargs) -> Fact:
    kwargs.setdefault("category", "工作经历")
    kwargs.setdefault("detail", "拆分结算链路，补齐对账与重试。")
    return add_fact(user_id, profile_id, title=title, **kwargs)


def test_profile_crud_and_per_user_isolation(user_root: Path):
    profile = _profile()
    assert len(profile.id) == 32
    assert get_profile(1, profile.id).name == "张三"
    assert [item.id for item in list_profiles(1)] == [profile.id]
    assert (resume_root(1) / "profiles.json").exists()

    assert list_profiles(2) == []
    assert not resume_root(2).exists()
    with pytest.raises(ResumeNotFound):
        get_profile(2, profile.id)


def test_invalid_ids_and_path_traversal_rejected(user_root: Path):
    _profile()
    for bad in ("../../etc/passwd", "..\\..\\secret", "f" * 31, "", "not-a-real-id"):
        with pytest.raises(ResumeNotFound):
            get_profile(1, bad)
    with pytest.raises(ResumeNotFound):
        get_job_version(1, "not-a-real-id")
    with pytest.raises(ResumeNotFound):
        render_job_version(1, "../escape")
    with pytest.raises(ResumeError):
        resume_root("../outside")
    with pytest.raises(ResumeError):
        resume_root(-1)
    with pytest.raises(ResumeError):
        resume_root(True)
    with pytest.raises(ResumeNotFound):
        add_fact(1, "../profile", category="项目", title="非法档案")


def test_job_version_rejects_pending_and_excluded_facts(user_root: Path):
    profile = _profile()
    pending = _fact(1, profile.id, title="待确认的数字", status="needs_confirmation")
    excluded = _fact(1, profile.id, title="已排除的事实", status="excluded")

    with pytest.raises(ResumeError) as pending_error:
        create_job_version(1, profile.id, title="后端工程师", fact_ids=[pending.id])
    assert "待确认" in str(pending_error.value)

    with pytest.raises(ResumeError) as excluded_error:
        create_job_version(1, profile.id, title="后端工程师", fact_ids=[excluded.id])
    assert "已排除" in str(excluded_error.value)

    with pytest.raises(ResumeError):
        _fact(1, profile.id, title="未知状态", status="verified")


def test_numeric_metric_without_evidence_needs_confirmation(user_root: Path):
    profile = _profile()
    unverified = _fact(
        1, profile.id, title="接口延迟降低 30%",
        status="self_reported", metrics=["延迟降低 30%"], evidence="",
    )
    assert unverified.status == "needs_confirmation"
    with pytest.raises(ResumeError):
        create_job_version(1, profile.id, title="后端工程师", fact_ids=[unverified.id])

    verified = _fact(
        1, profile.id, title="接口延迟降低 30%（有依据）",
        status="self_reported", metrics=["延迟降低 30%"], evidence="线上监控 2025-03 数据",
    )
    assert verified.status == "self_reported"
    version = create_job_version(1, profile.id, title="后端工程师", fact_ids=[verified.id])
    assert version.fact_ids == [verified.id]
    snapshot = render_job_version(1, version.id)

    # Removing the evidence downgrades the fact and blocks a *new* version,
    # while the resume already reviewed keeps its snapshot.
    downgraded = update_fact(1, profile.id, verified.id, evidence="")
    assert downgraded.status == "needs_confirmation"
    assert render_job_version(1, version.id) == snapshot
    with pytest.raises(ResumeError):
        create_job_version(1, profile.id, title="重做版本", fact_ids=[verified.id])

    # A non-numeric metric does not require an evidence note.
    qualitative = _fact(
        1, profile.id, title="负责支付链路",
        status="self_reported", metrics=["支付链路"], evidence="",
    )
    assert qualitative.status == "self_reported"


def test_job_version_snapshots_jd_hash_and_selected_facts(user_root: Path):
    profile = _profile()
    first = _fact(1, profile.id, title="搭建对账平台")
    second = _fact(1, profile.id, title="负责结算服务")
    unselected = _fact(1, profile.id, title="不应进入版本的事实")
    jd = "岗位职责：\n1. 维护结算系统\n2. 优化接口性能"

    version = create_job_version(
        1, profile.id,
        title="后端工程师",
        company="某科技公司",
        jd_text=jd,
        fact_ids=[second.id, first.id, second.id],
        template="modern",
        notes="内推",
    )

    assert version.jd_text == jd
    assert version.jd_sha256 == hashlib.sha256(jd.encode("utf-8")).hexdigest()
    assert version.fact_ids == [second.id, first.id]
    assert version.template == "modern"
    assert get_job_version(1, version.id).jd_sha256 == version.jd_sha256
    assert list_job_versions(1) == [version]

    markdown_path = resume_root(1) / "versions" / f"{version.id}.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    assert first.title in markdown
    assert second.title in markdown
    assert unselected.title not in markdown

    stored = json.loads((resume_root(1) / "versions.json").read_text(encoding="utf-8"))
    assert stored["versions"][version.id]["jd_sha256"] == version.jd_sha256
    assert stored["versions"][version.id]["fact_ids"] == [second.id, first.id]


def test_templates_change_layout_without_rewriting_facts(user_root: Path):
    profile = _profile()
    fact = _fact(
        1, profile.id, title="搭建对账平台", category="项目",
        detail="负责日终对账。", status="evidence_linked",
        evidence="评审记录", metrics=["覆盖 12 个渠道"],
    )
    versions = {
        name: create_job_version(
            1, profile.id, title=name, fact_ids=[fact.id], template=name,
        )
        for name in ("classic", "modern", "compact")
    }
    classic = render_job_version(1, versions["classic"].id)
    modern = render_job_version(1, versions["modern"].id)
    compact = render_job_version(1, versions["compact"].id)

    assert "\n## 项目\n" in classic
    assert "\n### 项目\n" in modern
    assert "\n### 项目\n" in compact
    # Nested metrics in classic/long form; inline in compact.
    assert "\n  - 指标：覆盖 12 个渠道" in classic
    assert "指标：覆盖 12 个渠道" in compact
    assert "\n  - 指标" not in compact
    for text in (classic, modern, compact):
        assert fact.title in text
        assert "未编造指标、日期或公司信息" in text
        assert "未选择" not in text


def test_rendered_markdown_contains_only_selected_facts(user_root: Path):
    profile = create_profile(
        1, name="李四", headline="数据分析师",
        contact={"email": "lisi@example.com", "city": "上海"},
    )
    work = _fact(
        1, profile.id, title="搭建报表体系",
        category="工作经历", detail="用 SQL 搭建经营报表。",
        status="evidence_linked", evidence="内部评审记录",
    )
    skill = _fact(
        1, profile.id, title="Python", category="技能",
        detail="5 年使用经验", status="self_reported",
    )
    unselected = _fact(1, profile.id, title="未选择的事实", category="项目")
    pending = _fact(
        1, profile.id, title="待确认的事实",
        category="项目", status="needs_confirmation",
    )
    version = create_job_version(
        1, profile.id, title="数据分析师", company="目标公司",
        fact_ids=[work.id, skill.id],
    )

    markdown = render_job_version(1, version.id)
    assert "# 李四" in markdown
    assert "数据分析师" in markdown
    assert "lisi@example.com" in markdown
    assert "本文档仅根据你提供的事实生成" in markdown
    assert "## 工作经历" in markdown
    assert "## 技能" in markdown
    assert "搭建报表体系" in markdown
    assert "Python" in markdown
    assert "依据：内部评审记录" in markdown
    assert unselected.title not in markdown
    assert pending.title not in markdown
    assert "目标公司" not in markdown
    assert "指标：" not in markdown


def test_fact_update_repairs_status_and_rejects_unknown(user_root: Path):
    profile = _profile()
    fact = _fact(
        1, profile.id, title="性能优化",
        category="项目", status="self_reported",
        metrics=["响应时间降低 40%"], evidence="压测报告",
    )
    assert fact.status == "self_reported"

    updated = update_fact(1, profile.id, fact.id, detail="补充了影响范围。")
    assert updated.detail == "补充了影响范围。"
    assert updated.status == "self_reported"

    with pytest.raises(ResumeError):
        update_fact(1, profile.id, fact.id, status="done")
    with pytest.raises(ResumeError):
        update_fact(1, profile.id, fact.id, title="   ")

    excluded = update_fact(1, profile.id, fact.id, status="excluded")
    assert excluded.status == "excluded"
    assert list_facts(1, profile.id)[0].status == "excluded"

    with pytest.raises(ResumeNotFound):
        update_fact(1, profile.id, "f" * 32, detail="unknown")


def test_registry_is_atomic_across_repeated_updates(user_root: Path):
    profile = _profile()
    fact = _fact(1, profile.id)
    for index in range(20):
        update_fact(1, profile.id, fact.id, detail=f"第 {index} 次修改")

    root = resume_root(1)
    payload = json.loads((root / "facts.json").read_text(encoding="utf-8"))
    assert payload["schema"] == FACT_SCHEMA
    assert len(payload["facts"]) == 1
    assert payload["facts"][fact.id]["detail"] == "第 19 次修改"
    assert json.loads((root / "profiles.json").read_text(encoding="utf-8"))[
        "profiles"
    ][profile.id]["name"] == "张三"
    assert list(root.rglob("*.tmp")) == []


def test_concurrent_fact_writes_do_not_lose_data(user_root: Path):
    profile = _profile()

    def add(index: int) -> Fact:
        return _fact(1, profile.id, title=f"并发事实 {index}", category="项目")

    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(add, range(20)))

    assert len({fact.id for fact in created}) == 20
    stored = json.loads(
        (resume_root(1) / "facts.json").read_text(encoding="utf-8")
    )["facts"]
    assert len(stored) == 20
    assert len(list_facts(1, profile.id)) == 20


def test_from_dict_repairs_unknown_values(user_root: Path):
    unknown = Fact.from_dict({
        "id": "a" * 32, "profile_id": "b" * 32,
        "category": "项目", "title": "未知状态", "status": "verified",
    })
    assert unknown.status == "needs_confirmation"

    unverified = Fact.from_dict({
        "id": "a" * 32, "profile_id": "b" * 32,
        "category": "项目", "title": "数字指标",
        "status": "self_reported", "metrics": ["提升 30%"], "evidence": "",
    })
    assert unverified.status == "needs_confirmation"

    verified = Fact.from_dict({
        "id": "a" * 32, "profile_id": "b" * 32,
        "category": "项目", "title": "数字指标",
        "status": "evidence_linked", "metrics": ["提升 30%"],
        "evidence": "复盘报告",
    })
    assert verified.status == "evidence_linked"

    version = JobVersion.from_dict({
        "id": "c" * 32, "profile_id": "b" * 32, "title": "后端工程师",
        "template": "fancy", "jd_text": "JD 内容", "jd_sha256": "bad",
        "fact_ids": ["a" * 32, "a" * 32, "bad"],
    })
    assert version.template == "classic"
    assert version.jd_sha256 == hashlib.sha256("JD 内容".encode("utf-8")).hexdigest()
    assert version.fact_ids == ["a" * 32]

    profile = Profile.from_dict({
        "id": "d" * 32, "user_id": 1, "name": "王五",
        "contact": {"email": "wangwu@example.com", "phone": 138, "nested": {"x": 1}},
    })
    assert profile.contact == {"email": "wangwu@example.com", "phone": "138"}


def test_job_version_rejects_foreign_or_unknown_facts(user_root: Path):
    first = _profile(1, name="张三")
    second = _profile(1, name="李四")
    fact = _fact(1, first.id)

    with pytest.raises(ResumeNotFound):
        create_job_version(1, second.id, title="岗位", fact_ids=[fact.id])
    with pytest.raises(ResumeNotFound):
        create_job_version(1, first.id, title="岗位", fact_ids=["f" * 32])
    with pytest.raises(ResumeError):
        create_job_version(1, first.id, title="岗位", fact_ids=[])
    with pytest.raises(ResumeError):
        create_job_version(1, first.id, title="岗位", fact_ids=[fact.id],
                           template="fancy")
    with pytest.raises(ResumeError):
        create_job_version(1, first.id, title="  ", fact_ids=[fact.id])


def test_job_version_cross_user_isolation(user_root: Path):
    profile = _profile()
    fact = _fact(1, profile.id)
    version = create_job_version(1, profile.id, title="后端工程师",
                                 fact_ids=[fact.id])

    assert list_job_versions(2) == []
    with pytest.raises(ResumeNotFound):
        get_job_version(2, version.id)
    with pytest.raises(ResumeNotFound):
        render_job_version(2, version.id)
    with pytest.raises(ResumeNotFound):
        list_facts(2, profile.id)
    with pytest.raises(ResumeNotFound):
        add_fact(2, profile.id, category="项目", title="越权事实")


def test_job_version_keeps_its_snapshot_after_fact_changes(user_root: Path):
    profile = _profile()
    fact = _fact(1, profile.id, title="最初写下的事实")
    version = create_job_version(1, profile.id, title="后端工程师",
                                 fact_ids=[fact.id])
    original = render_job_version(1, version.id)
    assert "最初写下的事实" in original

    update_fact(1, profile.id, fact.id, title="后来改写的事实",
                status="excluded")
    assert render_job_version(1, version.id) == original
    assert "后来改写的事实" not in render_job_version(1, version.id)
