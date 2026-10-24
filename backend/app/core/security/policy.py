"""Capability-based tool policy.

The policy is deterministic and independent of the model.  It runs before a
tool executes and returns allow/deny plus the capabilities that justified the
decision.  Tools still enforce their own path/sandbox guards; this layer makes
the rules explicit, auditable and consistent across tools.
"""
import re
from dataclasses import dataclass

from app.config import settings
from app.core.security.paths import is_secret_path, try_normalize_relpath
from app.core.security.risk import RiskLevel, grade_risk

CAPABILITIES_BY_TOOL = {
    "read_file": ["fs.read"],
    "list_files": ["fs.read"],
    "search_code": ["fs.read"],
    "impact_analysis": ["fs.read"],
    "diagnose_error": ["fs.read"],
    "write_files": ["fs.write"],
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


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    capabilities: tuple[str, ...]


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

    if mode == "readonly" and cap_set & WRITE_CAPABILITIES:
        return PolicyDecision(
            False,
            f"当前为只读模式，已阻止 {name}；请切换权限模式（需确认 / 自动）后再试",
            caps,
        )

    for value in _path_values(args):
        rel = try_normalize_relpath(value)
        if not rel:
            return PolicyDecision(False, f"路径不安全：{value}", caps)
        if is_secret_path(rel):
            return PolicyDecision(False, f"拒绝访问密钥/凭据文件：{rel}", caps)

    if "net.fetch" in cap_set and name == "fetch_url" and not settings.enable_fetch_url:
        return PolicyDecision(False, "联网抓取已关闭（ENABLE_FETCH_URL=false）", caps)

    if name == "install_deps":
        if user.get("role") != "admin":
            return PolicyDecision(False, "只有管理员可以联网安装依赖（demo 账号不允许）", caps)
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
