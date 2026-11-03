"""OpenAPI contract discovery and drift checking.

The Gate only reads a committed contract and compares a generated TypeScript
client against the committed client.  Refreshing the contract from a running
FastAPI app is a developer/CI action, not something the sandbox performs.
"""
from pathlib import Path

import yaml

from app.core.exec.host import quote_shell_arg
from app.core.security.paths import UnsafePathError, resolve_repo_path, try_normalize_relpath

CONTRACT_SOURCES = (
    "contracts/openapi.yaml",
    "contracts/openapi.yml",
    "contracts/openapi.json",
    "openapi.yaml",
    "openapi.yml",
    "openapi.json",
)
DEFAULT_TARGETS = (
    "frontend/src/lib/api-schema.d.ts",
    "web/src/lib/api-schema.d.ts",
    "src/lib/api-schema.d.ts",
    "frontend/src/api/schema.d.ts",
)

_CONTRACT_STEP = "契约检查"


def _contract_target(platform: str | None) -> str:
    """契约检查先写到一个临时文件，再与仓库里的类型文件比对。

    Docker 沙箱里固定用 /tmp；本地主机（Windows）没有 /tmp，必须换成本地
    临时目录，否则 openapi-typescript 直接写不进去。

    路径用正斜杠：这个值还会被嵌进 ``node -e`` 的单引号字符串里，反斜杠
    在那里是转义符——``%TEMP%\\nova-contract.d.ts`` 展开后 ``\\n`` 会变成
    换行，node 读到的是一个不存在的路径。cmd.exe 与 openapi-typescript
    都接受正斜杠。
    """
    if (platform or "posix") == "win32":
        return "%TEMP%/nova-contract.d.ts"
    return "/tmp/nova-contract.d.ts"


def parse_nova_config(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize(value: object) -> str | None:
    if value is None:
        return None
    return try_normalize_relpath(str(value))


def discover_contract(files: dict[str, str]) -> dict:
    config = parse_nova_config(files.get("nova.yaml", "") or files.get("NOVA.yaml", ""))
    contract_cfg = config.get("contract") if isinstance(config.get("contract"), dict) else {}
    source = _normalize(contract_cfg.get("source"))
    if not source:
        source = next((path for path in CONTRACT_SOURCES if path in files), None)
    target = _normalize(contract_cfg.get("target"))
    if not target:
        target = next((path for path in DEFAULT_TARGETS if path in files), None)
    if not target:
        target = DEFAULT_TARGETS[0]
    return {
        "configured": bool(source),
        "source": source,
        "target": target,
        "source_exists": bool(source and source in files),
        "target_exists": target in files,
        "from_config": bool(contract_cfg),
    }


def discover_contract_from_root(root: Path | str) -> dict:
    root = Path(root)
    paths: dict[str, str] = {}
    config_path = root / "nova.yaml"
    if config_path.is_file():
        try:
            paths["nova.yaml"] = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    config = parse_nova_config(paths.get("nova.yaml", ""))
    contract_cfg = config.get("contract") if isinstance(config.get("contract"), dict) else {}
    candidates = list(CONTRACT_SOURCES) + list(DEFAULT_TARGETS)
    for value in (contract_cfg.get("source"), contract_cfg.get("target")):
        normalized = _normalize(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for rel in candidates:
        try:
            target = resolve_repo_path(root, rel)
        except (UnsafePathError, ValueError):
            continue
        if target.is_file():
            paths.setdefault(rel, "")
    return discover_contract(paths)


def contract_step(files: dict[str, str], *, platform: str | None = None) -> dict | None:
    """Build the contract check step.

    Paths come from model-controlled ``nova.yaml``.  ``platform`` selects the
    quoting rules of the shell that will run the step (POSIX for the Docker
    sandbox, ``sys.platform`` for local host verification); unsafe values
    raise ``ValueError`` and must be skipped by the caller.
    """
    info = discover_contract(files)
    if not info["source"]:
        return None
    shell_platform = platform or "posix"
    source = quote_shell_arg(info["source"], platform=shell_platform)
    target = quote_shell_arg(info["target"], platform=shell_platform)
    tmp = _contract_target(shell_platform)
    # 临时路径必须以命令行参数传进去，不能拼进 JS 字符串字面量：
    # %TEMP% 展开后是反斜杠路径，`\n`、`\2` 在 JS 里是转义序列，
    # 拼进去会变成一个不存在的路径（实测 node 报 ENOENT）。
    script = (
        "const fs=require('fs');"
        "const a=fs.readFileSync(process.argv[1],'utf8').replace(/\\r\\n/g,'\\n');"
        "if(!fs.existsSync(process.argv[2])){"
        "console.error('contract target missing: '+process.argv[2]);process.exit(2);}"
        "const b=fs.readFileSync(process.argv[2],'utf8').replace(/\\r\\n/g,'\\n');"
        "if(a!==b){console.error('contract drift: regenerate '+process.argv[2]);process.exit(1);}"
        "console.log('contract ok');"
    )
    command = (
        f"openapi-typescript {source} -o {tmp} "
        f"&& node -e \"{script}\" {tmp} {target}"
    )
    return {
        "name": _CONTRACT_STEP,
        "command": command,
        "timeout": 180,
        "source": info["source"],
        "target": info["target"],
        "target_exists": info["target_exists"],
    }


def contract_step_name() -> str:
    return _CONTRACT_STEP
