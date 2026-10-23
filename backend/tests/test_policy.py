"""Capability policy: readonly, secrets, paths, network and dangerous commands."""
from app.config import settings
from app.core.security.policy import decide_tool
from app.core.tools.base import ToolContext


def ctx(mode="auto", role="admin"):
    return ToolContext(user={"id": 1, "role": role}, permission_mode=mode)


def test_readonly_blocks_write_and_execute_but_allows_read():
    assert not decide_tool("write_files", "write", None, {"files": {"app.py": "x"}}, ctx("readonly")).allowed
    assert not decide_tool("run_code", "execute", None, {"files": {"main.py": "x"}}, ctx("readonly")).allowed
    assert decide_tool("read_file", "read", None, {"path": "app.py"}, ctx("readonly")).allowed


def test_ask_mode_allows_staged_write():
    decision = decide_tool("write_files", "write", None, {"files": {"app.py": "x"}}, ctx("ask"))
    assert decision.allowed
    assert "fs.write" in decision.capabilities


def test_secret_and_unsafe_paths_are_denied():
    assert not decide_tool("read_file", "read", None, {"path": ".env"}, ctx()).allowed
    assert not decide_tool("write_files", "write", None, {"files": {"../x.py": "x"}}, ctx()).allowed
    assert not decide_tool("read_file", "read", None, {"path": "C:/secret.txt"}, ctx()).allowed
    assert not decide_tool("read_file", "read", None, {"path": "certs/server.pem"}, ctx()).allowed


def test_dangerous_commands_and_git_push_are_denied():
    for command in ("rm -rf /", "git push origin main", "git reset --hard"):
        decision = decide_tool("run_code", "execute", None, {"command": command}, ctx())
        assert not decision.allowed
        assert "安全规则" in decision.reason


def test_install_deps_requires_admin_and_network(monkeypatch):
    demo = decide_tool("install_deps", "execute", None, {}, ctx(role="demo"))
    assert not demo.allowed and "管理员" in demo.reason

    monkeypatch.setattr(settings, "sandbox_allow_network", False)
    admin = decide_tool("install_deps", "execute", None, {}, ctx())
    assert not admin.allowed and "SANDBOX_ALLOW_NETWORK" in admin.reason


def test_fetch_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_fetch_url", False)
    decision = decide_tool("fetch_url", "network", None, {"url": "https://example.com"}, ctx())
    assert not decision.allowed and "ENABLE_FETCH_URL" in decision.reason
