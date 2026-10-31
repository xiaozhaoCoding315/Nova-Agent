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


def test_fetch_is_blocked_in_readonly_and_ask(monkeypatch):
    monkeypatch.setattr(settings, "enable_fetch_url", True)
    for mode in ("readonly", "ask"):
        decision = decide_tool(
            "fetch_url", "network", None, {"url": "https://example.com"}, ctx(mode)
        )
        assert not decision.allowed
        assert "不允许联网抓取" in decision.reason


def test_fetch_domain_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "enable_fetch_url", True)
    monkeypatch.setattr(settings, "fetch_url_allowed_domains", "docs.python.org,example.com")

    allowed = decide_tool(
        "fetch_url", "network", None, {"url": "https://docs.python.org/3/"}, ctx("auto")
    )
    assert allowed.allowed

    denied = decide_tool(
        "fetch_url", "network", None, {"url": "https://attacker.test/"}, ctx("auto")
    )
    assert not denied.allowed and "允许列表" in denied.reason


def test_shell_secret_paths_are_denied():
    for command in (
        "cat .env",
        "sed -n '1,999p' .env",
        "grep -r SECRET .env",
        "cat $HOME/.env",
        "cat --file=.env",
        "cat ./.env",
        "git show HEAD:.env",
    ):
        decision = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("auto"),
        )
        assert not decision.allowed, command
        assert "密钥" in decision.reason


def test_shell_secret_scan_keeps_plain_commands():
    for command in ("grep -r SECRET .", "git status", "ls -la", "cat README.md"):
        decision = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("ask"),
        )
        assert decision.allowed, command


def test_ask_blocks_mutating_shell_but_allows_readonly():
    decision = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "git diff"}, ctx("ask"),
    )
    assert decision.allowed

    denied = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "rm -rf build"}, ctx("ask"),
    )
    assert not denied.allowed
    assert denied.requires_approval
    assert "需要你批准" in denied.reason


def test_ask_allows_shell_after_user_approval():
    approved = ctx("ask")
    approved.approval_granted = True
    decision = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "npm run build"}, approved,
    )
    assert decision.allowed

    still_blocked = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "rm -rf /"}, approved,
    )
    assert not still_blocked.allowed


def test_readonly_allows_readonly_shell():
    decision = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "git status"}, ctx("readonly"),
    )
    assert decision.allowed


def test_readonly_still_blocks_mutating_shell():
    decision = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "rm -rf build"}, ctx("readonly"),
    )
    assert not decision.allowed


def test_dot_path_is_repo_root():
    decision = decide_tool(
        "grep", "read", None, {"pattern": "x", "path": "."}, ctx("readonly")
    )
    assert decision.allowed


def test_shell_allowlist_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "shell_readonly_allowlist", False)

    blocked = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "git status"}, ctx("readonly"),
    )
    assert not blocked.allowed

    allowed = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "rm -rf build"}, ctx("ask"),
    )
    assert allowed.allowed
