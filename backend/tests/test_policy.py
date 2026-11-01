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


def test_local_nova_config_reads_require_approval(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    # auto mode: the local ask gate must not be what catches these.
    for command in (
        r"type %APPDATA%\Nova\nova-config.json",
        "cat Nova/nova-config.json",
        "cat .nova-instance.lock",
        "cat pgpassword",
    ):
        decision = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("auto"),
        )
        assert not decision.allowed, command
        assert decision.requires_approval, command
        assert "需要你批准" in decision.reason

    approved = ctx("auto")
    approved.approval_granted = True
    allowed = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": r"type %APPDATA%\Nova\nova-config.json"}, approved,
    )
    assert allowed.allowed


def test_local_nova_default_data_root_requires_approval(monkeypatch):
    """The shipped default data root is %APPDATA%\\Nova, not NovaData."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    for command in (
        r"dir %APPDATA%\Nova",
        r"type %APPDATA%\Nova\mcp.json",
        r"type %APPDATA%\Nova\logs\app.log",
        r"type %APPDATA%\Nova\users\1\secret.txt",
        r"type %APPDATA%\Nova\pgdata\postgresql.conf",
        r"type C:\Users\alice\AppData\Roaming\Nova\mcp.json",
        r"type $env:APPDATA\Nova\mcp.json",
        r"type ${env:APPDATA}\Nova\mcp.json",
        r"type appdata/roaming/nova/mcp.json",
        r"type appdata/nova/mcp.json",
    ):
        decision = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("auto"),
        )
        assert not decision.allowed, command
        assert decision.requires_approval, command


def test_local_nova_wildcards_require_approval(monkeypatch):
    """Trivial wildcards must not slip past the substring matcher."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    for command in (
        r"type %APPDATA%\Nova\nova-config.jso?",
        r"type %APPDATA%\Nova\nova-config.*",
        r"type Nova\*",
        r"type %APPDATA%\Nova\mcp.jso?",
        r"type %APPDATA%\Nova\*",
    ):
        decision = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("auto"),
        )
        assert not decision.allowed, command
        assert decision.requires_approval, command


def test_local_nova_data_root_requires_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "nova_mode", "local")
    root = tmp_path / "NovaData"
    monkeypatch.setattr(settings, "nova_data_dir", str(root))
    command = f'ls "{root.as_posix()}"'
    decision = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": command}, ctx("auto"),
    )
    assert not decision.allowed
    assert decision.requires_approval
    assert "需要你批准" in decision.reason
    assert command not in decision.reason


def test_local_unrelated_paths_are_unaffected(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    for command in ("cat README.md", "ls nova", "grep -r nova ."):
        allowed = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("auto"),
        )
        assert allowed.allowed, command


def test_server_mode_nova_config_reads_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "server")
    allowed = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": r"type %APPDATA%\Nova\nova-config.json"}, ctx("ask"),
    )
    assert allowed.allowed


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


def test_local_ask_gates_every_run_command(monkeypatch):
    """Local ask has no sanitized copy, so every shell command is approved."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    for command in (
        "type *.env",
        "cat .e*",
        "grep -r API_KEY .",
        "git status",
        "rm -rf build",
    ):
        decision = decide_tool(
            "run_command", "execute", ["proc.exec", "fs.write"],
            {"command": command}, ctx("ask"),
        )
        assert not decision.allowed, command
        assert decision.requires_approval, command
        assert "需要你批准" in decision.reason

    approved = ctx("ask")
    approved.approval_granted = True
    assert decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "grep -r API_KEY ."}, approved,
    ).allowed
    # An explicit secret file is still flat-denied after approval.
    denied = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "cat .env"}, approved,
    )
    assert not denied.allowed
    assert not denied.requires_approval


def test_local_auto_keeps_normal_policy_rules(monkeypatch):
    monkeypatch.setattr(settings, "nova_mode", "local")
    assert decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "git status"}, ctx("auto"),
    ).allowed
    denied = decide_tool(
        "run_command", "execute", ["proc.exec", "fs.write"],
        {"command": "cat .env"}, ctx("auto"),
    )
    assert not denied.allowed
    assert not denied.requires_approval


def test_local_ask_requires_approval_for_run_code(monkeypatch):
    """C1: model-authored code must never run unapproved in local ask."""
    monkeypatch.setattr(settings, "nova_mode", "local")
    decision = decide_tool(
        "run_code", "execute", None, {"files": {"main.py": "print(1)"}}, ctx("ask")
    )
    assert not decision.allowed
    assert decision.requires_approval
    assert "run_code" in decision.reason

    approved = ctx("ask")
    approved.approval_granted = True
    assert decide_tool(
        "run_code", "execute", None, {"files": {"main.py": "print(1)"}}, approved
    ).allowed

    monkeypatch.setattr(settings, "nova_mode", "server")
    assert decide_tool(
        "run_code", "execute", None, {"files": {"main.py": "print(1)"}}, ctx("ask")
    ).allowed
