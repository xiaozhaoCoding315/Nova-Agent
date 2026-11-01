"""Capability-based tool policy.

The policy is deterministic and independent of the model.  It runs before a
tool executes and returns allow/deny plus the capabilities that justified the
decision.  Tools still enforce their own path/sandbox guards; this layer makes
the rules explicit, auditable and consistent across tools.
"""
import re
import shlex
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import settings
from app.core.security.commands import CommandClass, classify_command
from app.core.security.paths import (
    is_nova_secret_path,
    is_secret_path,
    try_normalize_relpath,
)
from app.core.security.risk import RiskLevel, grade_risk

CAPABILITIES_BY_TOOL = {
    "read_file": ["fs.read"],
    "list_files": ["fs.read"],
    "search_code": ["fs.read"],
    "impact_analysis": ["fs.read"],
    "diagnose_error": ["fs.read"],
    "grep": ["fs.read"],
    "glob": ["fs.read"],
    "write_files": ["fs.write"],
    "edit_file": ["fs.write"],
    "run_code": ["proc.exec"],
    "install_deps": ["proc.exec", "net.fetch", "fs.write"],
    "fetch_url": ["net.fetch"],
    "json_tool": [],
    "sql_tool": [],
}

CATEGORY_CAPABILITIES = {
    "read": ["fs.read"],
    "write": ["fs.write"],
    "execute": ["proc.exec"],
    "network": ["net.fetch"],
}

WRITE_CAPABILITIES = {"fs.write", "proc.exec", "git.write", "deploy"}
DENY_COMMANDS = (
    re.compile(r"\bgit\s+push\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bterraform\s+apply\b", re.IGNORECASE),
    re.compile(r"\bkubectl\s+(apply|delete)\b", re.IGNORECASE),
)

_SHELL_HINT = (
    "修改文件请改用 edit_file / write_files；跑测试或构建请在非只读模式下用 run_code"
    "（沙箱副本，不落盘）；或切换到「自动执行」后重试。"
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    capabilities: tuple[str, ...]
    requires_approval: bool = False


def capabilities_for(
    name: str, category: str, explicit: list[str] | None = None
) -> tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    mapped = CAPABILITIES_BY_TOOL.get(name)
    if mapped is not None:
        return tuple(mapped)
    return tuple(CATEGORY_CAPABILITIES.get(category, []))


def _path_values(args: dict) -> list[str]:
    values: list[str] = []
    for key in ("path", "prefix", "requirements"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    files = args.get("files")
    if isinstance(files, dict):
        values.extend(str(path) for path in files)
    return values


def _secret_reference(command: str) -> str | None:
    """Return the secret-looking path referenced by a shell command.

    This is a defence-in-depth check for commands such as ``cat .env`` that
    are otherwise classified as read-only.  The executable boundary is the
    sanitized workspace (run_command mounts a copy without secret files);
    token scanning catches the obvious explicit references early.
    """
    if not command:
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None

    for token in tokens:
        candidate = token.strip()
        if not candidate or candidate in (".", "./", "..", "-"):
            continue
        if "=" in candidate and not candidate.startswith(("/", "./", "../")):
            name, value = candidate.split("=", 1)
            if name.startswith("-") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                candidate = value.strip()
        if ":" in candidate and "://" not in candidate:
            # git rev:path (e.g. ``git show HEAD:.env``)
            candidate = candidate.rsplit(":", 1)[1].strip() or candidate
        if not candidate or candidate in (".", "./", ".."):
            continue
        parts = [part for part in candidate.replace("\\", "/").split("/") if part]
        if not parts:
            continue
        tail = "/".join(parts[-2:])
        if is_nova_secret_path(tail):
            # Nova's own config/data files are approval-gated (below), not
            # flat-denied: an approved retry must be able to run.
            continue
        if is_secret_path(tail):
            return candidate
    return None


# Stems, not exact filenames: ``nova-config.jso?`` / ``nova-config.*`` must
# still be recognised as the JWT signer file.
_NOVA_SECRET_MARKERS = ("nova-config", ".nova-instance", "pgpassword")
_NOVA_DATA_DIR_NAMES = {"novadata", "nova-data", "nova_data"}
# The shipped desktop default data root is ``%APPDATA%\Nova`` (basename
# ``nova``) and holds these children; ``_NOVA_DATA_DIR_NAMES`` alone never
# matched it.
_NOVA_DATA_CHILDREN = (
    "logs", "users", "pgdata", "tmp", "skills", "downloads",
    "legacy-repos", "mcp.json",
)
_NOVA_DEFAULT_ROOT = re.compile(
    r"(?:%appdata%|\$env:appdata|\$\{env:appdata\}|appdata(?:/roaming)?)/nova(?:/|$)"
)
# Wildcards into a Nova-looking directory (``Nova\*``, ``Nova\mcp.jso?``)
# cannot be enumerated by a substring match, so they need approval too.
_NOVA_WILDCARD_REF = re.compile(r"nova/[^\s\"']*[?*]|(?:^|[/\s\"'=])nova[?*]")


def _local_data_root() -> tuple[str, str]:
    """Normalized (path, basename) of the Nova data root, when configured."""
    try:
        raw = str(settings.data_root)
    except (RuntimeError, OSError):
        raw = str(settings.nova_data_dir or "")
    text = raw.replace("\\", "/").rstrip("/").lower()
    if len(text) < 4 or ("/" not in text and ":" not in text):
        return "", ""
    return text, text.rsplit("/", 1)[-1]


def _nova_secret_reference(command: str) -> str | None:
    """Return a marker when a shell command reaches Nova's own local files.

    Local mode runs commands on the host as the signed-in user, so ``type``
    or ``cat`` of ``%APPDATA%\\Nova\\nova-config.json`` would print the JWT
    signer.  ``shlex`` tokenisation cannot see Windows backslash paths, so
    this scans the raw command (normalized, lowercased).  Never returns or
    logs the command itself.  Server mode is unaffected.
    """
    if not settings.is_local or not command:
        return None
    raw = command.replace("\\", "/").lower()
    for marker in _NOVA_SECRET_MARKERS:
        if marker in raw:
            return marker
    root_path, root_name = _local_data_root()
    if root_path and root_path in raw:
        return "Nova 数据目录"
    if root_name in _NOVA_DATA_DIR_NAMES and root_name in raw:
        return "Nova 数据目录"
    if _NOVA_DEFAULT_ROOT.search(raw) or _NOVA_WILDCARD_REF.search(raw):
        return "Nova 数据目录"
    for child in _NOVA_DATA_CHILDREN:
        if f"nova/{child}" in raw:
            return "Nova 数据目录"
    return None


def _host_allowed(host: str, allowed: str) -> bool:
    domains = [item.strip().lower().lstrip(".") for item in allowed.split(",") if item.strip()]
    if not domains:
        return True
    host = host.lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def decide_tool(
    name: str,
    category: str,
    explicit_capabilities: list[str] | None,
    args: dict,
    ctx,
) -> PolicyDecision:
    caps = capabilities_for(name, category, explicit_capabilities)
    cap_set = set(caps)
    mode = getattr(ctx, "permission_mode", "ask")
    user = getattr(ctx, "user", {}) or {}

    if "secrets.read" in cap_set:
        return PolicyDecision(False, "禁止读取密钥/凭据", caps)

    if name.startswith("mcp__") and settings.mcp_admin_only \
            and user.get("role") != "admin" and "mcp.open" not in cap_set:
        # "mcp.open" marks servers explicitly opened to all users
        # ("admin_only": false in the MCP config).
        return PolicyDecision(False, "MCP 工具仅管理员可用", caps)

    for value in _path_values(args):
        if str(value).strip() in ("", ".", "./"):
            continue
        rel = try_normalize_relpath(value)
        if not rel:
            return PolicyDecision(False, f"路径不安全：{value}", caps)
        if is_secret_path(rel):
            return PolicyDecision(False, f"拒绝访问密钥/凭据文件：{rel}", caps)

    if name == "run_command":
        command = str(args.get("command") or "")
        nova = _nova_secret_reference(command)
        if nova and not getattr(ctx, "approval_granted", False):
            return PolicyDecision(
                False,
                f"命令会访问 Nova 的本地配置/数据文件（{nova}），需要你批准后执行",
                caps,
                requires_approval=True,
            )
        secret = _secret_reference(command)
        if secret:
            return PolicyDecision(
                False, f"拒绝访问密钥/凭据文件：{secret}", caps
            )
        # Local mode has no sanitized copy or secret masks: a read-only
        # command such as ``type *.env`` reaches the real files.  Ask mode is
        # documented as "every command needs approval", so gate every local
        # shell command; auto/full keep their normal policy rules.
        if (
            settings.is_local
            and mode == "ask"
            and not getattr(ctx, "approval_granted", False)
        ):
            return PolicyDecision(
                False,
                "本地模式确认执行：命令会在你的电脑上真实运行且没有容器隔离，"
                f"需要你批准：{command[:120]}",
                caps,
                requires_approval=True,
            )

    if (
        name == "run_code"
        and settings.is_local
        and mode == "ask"
        and not getattr(ctx, "approval_granted", False)
    ):
        # run_code executes arbitrary model-authored code as the signed-in
        # user; without this gate ask mode would run it with no prompt.
        return PolicyDecision(
            False,
            "本地模式确认执行：run_code 会以当前用户权限在你的电脑上运行模型编写的代码"
            "（无容器隔离），需要你批准后执行",
            caps,
            requires_approval=True,
        )

    readonly_shell = False
    if name == "run_command" and settings.shell_readonly_allowlist:
        command = str(args.get("command") or "")
        command_class, reason = classify_command(command)
        if command_class is CommandClass.READONLY:
            readonly_shell = True
        elif mode == "ask" and not getattr(ctx, "approval_granted", False):
            return PolicyDecision(
                False,
                f"命令会改动仓库，需要你批准：{command[:160]}（{reason}）",
                caps,
                requires_approval=True,
            )
        elif mode == "readonly":
            return PolicyDecision(
                False,
                f"当前模式（readonly）不允许执行会改动仓库的命令："
                f"{command[:120]}（{reason}）。" + _SHELL_HINT,
                caps,
            )

    if mode == "readonly" and cap_set & WRITE_CAPABILITIES and not readonly_shell:
        return PolicyDecision(
            False,
            f"当前为计划（只读）模式，已阻止 {name}；请切换权限模式（变更前确认 / 自主 / 完全访问）后再试",
            caps,
        )

    if name == "fetch_url":
        if not settings.enable_fetch_url:
            return PolicyDecision(False, "联网抓取已关闭（ENABLE_FETCH_URL=false）", caps)
        if mode in ("readonly", "ask"):
            return PolicyDecision(
                False,
                f"当前模式（{mode}）不允许联网抓取，避免只读/确认模式下外发内容；"
                "请切换到「自主」或「完全访问」后重试",
                caps,
            )
        host = urlparse(str(args.get("url") or "")).hostname or ""
        if not _host_allowed(host, settings.fetch_url_allowed_domains):
            return PolicyDecision(
                False,
                f"域名不在允许列表内：{host or 'unknown'}（见 FETCH_URL_ALLOWED_DOMAINS）",
                caps,
            )

    if name == "install_deps":
        if user.get("role") != "admin" and mode != "full":
            return PolicyDecision(
                False, "联网安装依赖需要管理员，或在会话中切换到「完全访问」模式", caps)
        if not settings.sandbox_allow_network:
            return PolicyDecision(
                False,
                "联网安装未开启：请在服务端 .env 设置 SANDBOX_ALLOW_NETWORK=true 后重启",
                caps,
            )

    if "proc.exec" in cap_set:
        command = str(args.get("command") or "")
        if any(pattern.search(command) for pattern in DENY_COMMANDS):
            return PolicyDecision(False, f"安全规则：禁止执行命令 {command[:120]}", caps)
        level, reasons = grade_risk(command)
        if level == RiskLevel.BLOCK:
            return PolicyDecision(
                False, "安全规则：" + "；".join(reasons[:3]), caps
            )

    return PolicyDecision(True, "allowed", caps)
