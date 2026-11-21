"""Evidence-pack tests: claims, manifests, storage and environment comparison.

Everything runs on tmp_path; no database, no network, no verification steps.
"""
import hashlib
import json

import pytest

from app.config import settings
from app.core.evidence import (
    Claim,
    EnvironmentManifest,
    EvidenceArtifact,
    EvidenceError,
    EvidencePack,
    artifact_for,
    build_pack,
    canonical_json,
    comparability_note,
    compare_environments,
    load_pack,
    save_pack,
    verify_pack,
)


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(settings, "user_data_dir", str(root))
    return root


def _verification() -> dict:
    return {
        "status": "failed",
        "steps": [
            {
                "name": "单元测试", "command": "python -m pytest -q",
                "required": True, "status": "passed", "exit_code": 0,
                "timed_out": False, "reason": "",
            },
            {
                "name": "代码规范", "command": "ruff check .",
                "required": False, "status": "skipped", "exit_code": 127,
                "timed_out": False, "reason": "命令不存在",
            },
            {
                "name": "类型检查", "command": "mypy app",
                "required": True, "status": "not_run", "exit_code": -1,
                "timed_out": False, "reason": "前序必需步骤失败，未运行",
            },
            {
                "name": "端到端测试", "command": "playwright test",
                "required": True, "status": "unsupported", "exit_code": -1,
                "timed_out": False, "reason": "当前环境不支持该步骤",
            },
            {
                "name": "构建", "command": "python -m build",
                "required": True, "status": "failed", "exit_code": 1,
                "timed_out": False, "reason": "退出码 1",
            },
        ],
        "report": {
            "environment": {
                "mode": "container",
                "isolation": "container",
                "network": "disabled",
                "image": "nova-builder:latest",
                "notes": ["沙箱内执行"],
            },
            "workspace": {"commit": "deadbeef"},
        },
    }


def _pack(**kwargs) -> EvidencePack:
    options = {
        "pack_id": "pack-1",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    options.update(kwargs)
    return build_pack(**options)


def test_claim_roundtrip_known_values():
    claim = Claim(
        claim_id="c1", statement="tax.py 第 12 行计算税额",
        kind="code_fact", status="confirmed", commit="abc123",
        path="app/tax.py", line=12, evidence_ids=["art-1"],
        notes=["人工核对"],
    )
    restored = Claim.from_dict(claim.to_dict())
    assert restored == claim
    assert canonical_json({"b": 1, "a": [2]}) == '{"a":[2],"b":1}'


def test_claim_unknown_values_are_repaired_not_guessed():
    claim = Claim.from_dict({
        "claim_id": "c2", "statement": "来源不明", "kind": "rumour",
        "status": "maybe",
    })
    assert claim.kind == "unverified"
    assert claim.status == "unverified"
    assert any("rumour" in note for note in claim.notes)
    assert any("maybe" in note for note in claim.notes)


def test_build_pack_preserves_each_verification_status():
    pack = _pack(verification=_verification(), repo={"id": "repo-1"})
    assert [claim.status for claim in pack.claims] == [
        "confirmed", "not_run", "not_run", "unsupported", "failed",
    ]
    assert all(claim.kind == "test_result" for claim in pack.claims)
    assert all(claim.commit == "deadbeef" for claim in pack.claims)
    assert pack.commit == "deadbeef"
    assert pack.repo_id == "repo-1"
    assert pack.environment.mode == "container"
    assert pack.environment.image_digest == "nova-builder:latest"
    assert any("skipped" in note for note in pack.claims[1].notes)
    # Every non-passing step must remain visible in unproven.
    assert len(pack.unproven) == 4
    assert any("代码规范" in item and "跳过" in item for item in pack.unproven)
    assert any("构建" in item and "失败" in item for item in pack.unproven)
    assert all(isinstance(item, str) for item in pack.unproven)


def test_manifest_hash_is_deterministic_and_artifacts_are_sorted(tmp_path):
    first = tmp_path / "b.txt"
    second = tmp_path / "a.txt"
    first.write_text("b", encoding="utf-8")
    second.write_text("a", encoding="utf-8")

    pack_one = _pack(artifact_paths=[first, second])
    pack_two = _pack(artifact_paths=[second, first])
    assert pack_one.manifest_sha256 == pack_two.manifest_sha256
    assert pack_one.manifest_sha256.startswith("sha256:")
    names = [row["name"] for row in pack_one.manifest()["artifacts"]]
    assert names == sorted(names) == ["a.txt", "b.txt"]
    assert pack_one.manifest()["artifacts"][0]["sha256"] == hashlib.sha256(
        b"a"
    ).hexdigest()


def test_artifact_for_computes_hash_and_size(tmp_path):
    target = tmp_path / "result.json"
    target.write_text('{"ok": true}', encoding="utf-8")
    artifact = artifact_for(target)
    assert artifact.name == "result.json"
    assert artifact.sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    assert artifact.size == len(target.read_bytes())
    assert artifact.media_type
    with pytest.raises(EvidenceError):
        artifact_for(tmp_path / "missing.bin")


def test_verify_pack_accepts_intact_artifacts(tmp_path):
    artifact = tmp_path / "result.txt"
    artifact.write_text("ok", encoding="utf-8")
    pack = _pack(artifact_paths=[artifact])
    assert verify_pack(pack, [tmp_path]) == {"ok": True, "problems": []}


def test_verify_pack_detects_tampered_artifact(tmp_path):
    artifact = tmp_path / "result.txt"
    artifact.write_text("ok", encoding="utf-8")
    pack = _pack(artifact_paths=[artifact])
    artifact.write_text("no", encoding="utf-8")  # same size, different bytes
    report = verify_pack(pack, [tmp_path])
    assert report["ok"] is False
    assert any("result.txt" in problem for problem in report["problems"])
    assert any("篡改" in problem or "不一致" in problem
               for problem in report["problems"])


def test_verify_pack_detects_missing_artifact(tmp_path):
    artifact = tmp_path / "result.txt"
    artifact.write_text("ok", encoding="utf-8")
    pack = _pack(artifact_paths=[artifact])
    artifact.unlink()
    report = verify_pack(pack, [tmp_path])
    assert report["ok"] is False
    assert any("缺失" in problem for problem in report["problems"])


def test_verify_pack_without_artifacts_needs_no_roots():
    pack = _pack()
    assert verify_pack(pack, []) == {"ok": True, "problems": []}


def test_verify_pack_detects_modified_metadata(tmp_path):
    pack = _pack()
    pack.unproven = ["手工加入、未重新签名的条目"]
    report = verify_pack(pack, [tmp_path])
    assert report["ok"] is False
    assert any("清单摘要不一致" in problem for problem in report["problems"])


def test_verify_pack_does_not_crash_on_malformed_input(tmp_path):
    for broken in (
        None,
        [],
        {"pack_id": "p", "claims": 42},
        {"pack_id": "p", "artifacts": "nope"},
        {"pack_id": "p", "unproven": 7},
    ):
        report = verify_pack(broken, [tmp_path])
        assert report["ok"] is False
        assert report["problems"]


def test_pack_redacts_secrets_before_saving(user_data):
    secret = "sk-" + "a" * 24
    verification = {
        "steps": [{
            "name": "单元测试", "command": "pytest",
            "required": True, "status": "failed", "exit_code": 1,
            "reason": f"API_KEY=supersecretvalue 泄露了 {secret}",
        }],
        "report": {"environment": {
            "mode": "container", "isolation": "container",
            "network": "disabled", "image": "img:latest",
            "notes": ["TOKEN=abcdef"],
        }},
    }
    pack = _pack(
        verification=verification,
        environment=EnvironmentManifest(
            mode="container", isolation="container", network="disabled",
            tool_versions={"api_secret": secret},
            notes=["PASSWORD=hunter2"],
        ),
        unproven=[f"未记录：{secret}"],
    )
    assert secret not in pack.claims[0].statement
    assert "supersecretvalue" not in pack.claims[0].statement
    assert pack.environment.tool_versions["api_secret"] == "[REDACTED]"
    assert secret not in " ".join(pack.unproven)

    path = save_pack(pack, 7)
    saved = path.read_text(encoding="utf-8")
    assert secret not in saved
    assert "supersecretvalue" not in saved
    assert "hunter2" not in saved
    assert "[REDACTED]" in saved
    loaded = load_pack(7, "pack-1")
    assert secret not in loaded.claims[0].statement


def test_environment_comparison_reports_same_dimensions():
    local = EnvironmentManifest(
        mode="host", os="Windows", arch="AMD64", isolation="none",
        network="host", image_digest="host",
        tool_versions={"Python": "3.12.0", "node": "20"},
        working_dir="C:\\work",
    )
    container = EnvironmentManifest(
        mode="container", os="windows", arch="x86_64", isolation="NONE",
        network="HOST", image_digest="host",
        tool_versions={"python": "3.12.0", "node": "20"},
        working_dir="c:/work",
    )
    report = compare_environments(local, container)
    assert all(row["result"] == "same" for row in report["rows"])
    assert report["identical"] is True
    assert report["not_comparable"] == []
    assert len(report["comparable"]) == 7


def test_environment_comparison_never_calls_unknown_comparable():
    local = EnvironmentManifest(
        mode="host", os="windows", arch="x86_64", isolation="none",
        network="host", image_digest="host", tool_versions={}, working_dir="",
    )
    container = EnvironmentManifest(
        mode="container", os="linux", arch="x86_64",
        isolation="container", network="disabled", image_digest="",
        tool_versions={"python": "3.12"}, working_dir="/workspace",
    )
    report = compare_environments(local, container)
    results = {row["dimension"]: row["result"] for row in report["rows"]}
    assert results["os"] == "different"
    assert results["arch"] == "same"
    assert results["isolation"] == "different"
    assert results["network"] == "different"
    assert results["image_digest"] == "unknown"
    assert results["tool_versions"] == "unknown"
    assert results["working_dir"] == "unknown"
    assert report["identical"] is False
    assert report["comparable"] == ["arch"]
    assert "image_digest" in report["unknown"]
    assert "image_digest" not in report["comparable"]
    assert set(report["not_comparable"]) == {
        "os", "isolation", "network", "image_digest",
        "tool_versions", "working_dir",
    }


def test_environment_comparison_missing_side_is_all_unknown():
    report = compare_environments(None, EnvironmentManifest(
        mode="container", os="linux", arch="x86_64",
        isolation="container", network="disabled", image_digest="sha256:"
        + "a" * 64, tool_versions={"python": "3.12"},
        working_dir="/workspace",
    ))
    assert report["comparable"] == []
    assert report["identical"] is False
    assert all(row["result"] == "unknown" for row in report["rows"])
    note = comparability_note(report["rows"])
    assert "无法确认" in note
    assert "未记录不等于一致" in note


def test_tool_versions_recorded_on_one_side_only_is_unknown():
    local = EnvironmentManifest(tool_versions={"python": "3.11"})
    container = EnvironmentManifest(
        tool_versions={"python": "3.11", "node": "20"},
    )
    report = compare_environments(local, container)
    row = next(item for item in report["rows"]
               if item["dimension"] == "tool_versions")
    assert row["result"] == "unknown"
    assert "tool_versions" not in report["comparable"]


def test_save_load_is_per_user_and_recomputes_manifest(user_data):
    pack = _pack(environment=EnvironmentManifest(
        mode="container", os="linux", arch="x86_64",
        isolation="container", network="disabled",
    ))
    pack.manifest_sha256 = ""  # save must finalize it
    path = save_pack(pack, 1)
    assert path == user_data / "1" / "evidence" / "pack-1.json"
    loaded = load_pack(1, "pack-1")
    assert loaded.pack_id == "pack-1"
    assert loaded.environment.os == "linux"
    assert loaded.manifest_sha256.startswith("sha256:")
    assert verify_pack(loaded, [user_data]) == {"ok": True, "problems": []}
    with pytest.raises(EvidenceError):
        load_pack(2, "pack-1")


def test_load_pack_rejects_malformed_files(user_data):
    directory = user_data / "3" / "evidence"
    directory.mkdir(parents=True)
    target = directory / "broken.json"
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvidenceError):
        load_pack(3, "broken")
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(EvidenceError):
        load_pack(3, "broken")
    target.write_text(
        json.dumps({"pack_id": "broken", "unproven": "not-a-list"}),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError):
        load_pack(3, "broken")


def test_pack_ids_and_users_cannot_escape_the_data_directory(user_data):
    pack = _pack()
    pack.pack_id = "../escape"
    with pytest.raises(EvidenceError):
        save_pack(pack, 1)
    with pytest.raises(EvidenceError):
        save_pack(_pack(pack_id="safe-pack"), "../1")
    with pytest.raises(EvidenceError):
        load_pack(1, "../escape")
    assert not (user_data.parent / "escape.json").exists()


def test_build_pack_accepts_a_single_explicit_claim():
    pack = _pack(claims={
        "claim_id": "c-single", "statement": "人工确认的事实",
        "kind": "human_note", "status": "confirmed",
    })
    assert len(pack.claims) == 1
    assert pack.claims[0].claim_id == "c-single"
    assert pack.claims[0].kind == "human_note"


def test_unproven_items_are_never_silently_dropped():
    pack = EvidencePack(
        pack_id="p", created_at="2026-01-01T00:00:00+00:00",
        unproven=["", "人工确认第 3 条", None],  # noqa: E501 - None becomes ""
    )
    assert pack.unproven == ["", "人工确认第 3 条", ""]
    restored = EvidencePack.from_dict(pack.to_dict())
    assert restored.unproven == pack.unproven
    missing = EvidencePack.from_dict({"pack_id": "p"})
    assert missing.unproven == []
    with pytest.raises(EvidenceError):
        EvidencePack.from_dict({"pack_id": "p", "unproven": "oops"})


def test_pack_roundtrip_keeps_claims_artifacts_and_environment(tmp_path):
    artifact_path = tmp_path / "coverage.txt"
    artifact_path.write_text("coverage 87%", encoding="utf-8")
    artifact = artifact_for(artifact_path)
    pack = EvidencePack(
        pack_id="roundtrip",
        task_id="task-9",
        repo_id="repo-9",
        commit="abc123",
        created_at="2026-01-01T00:00:00+00:00",
        claims=[Claim(
            claim_id="c1", statement="覆盖率 87%", kind="test_result",
            status="confirmed", commit="abc123", evidence_ids=[artifact.artifact_id],
        )],
        artifacts=[artifact],
        environment=EnvironmentManifest(
            mode="container", os="linux", arch="x86_64",
            isolation="container", network="disabled",
            image_digest="sha256:" + "b" * 64,
            tool_versions={"python": "3.12"},
            working_dir="/workspace",
        ),
        unproven=["人工复核第 4 章"],
    )
    restored = EvidencePack.from_dict(pack.to_dict())
    assert restored.to_dict() == pack.to_dict()
    assert restored.claims == pack.claims
    assert restored.artifacts == pack.artifacts
    assert restored.environment.to_dict() == pack.environment.to_dict()
    assert restored.unproven == pack.unproven


def test_artifact_with_stored_sha_prefix_is_normalized(tmp_path):
    artifact = EvidenceArtifact.from_dict({
        "artifact_id": "a1", "name": "x.txt",
        "sha256": "sha256:" + "c" * 64, "size": 3,
    })
    assert artifact.sha256 == "c" * 64
