"""OpenAPI contract discovery and drift checking.

The Gate only reads a committed contract and compares a generated TypeScript
client against the committed client.  Refreshing the contract from a running
FastAPI app is a developer/CI action, not something the sandbox performs.
"""
import shlex
from pathlib import Path

import yaml

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
_CONTRACT_TARGET = "/tmp/nova-contract.d.ts"


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


def contract_step(files: dict[str, str]) -> dict | None:
    info = discover_contract(files)
    if not info["source"]:
        return None
    source = shlex.quote(info["source"])
    target = shlex.quote(info["target"])
    script = (
        "const fs=require('fs');"
        f"const a=fs.readFileSync('{_CONTRACT_TARGET}','utf8').replace(/\\r\\n/g,'\\n');"
        "if(!fs.existsSync(process.argv[1])){"
        "console.error('contract target missing: '+process.argv[1]);process.exit(2);}"
        "const b=fs.readFileSync(process.argv[1],'utf8').replace(/\\r\\n/g,'\\n');"
        "if(a!==b){console.error('contract drift: regenerate '+process.argv[1]);process.exit(1);}"
        "console.log('contract ok');"
    )
    command = (
        f"openapi-typescript {source} -o {_CONTRACT_TARGET} "
        f"&& node -e \"{script}\" {target}"
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
