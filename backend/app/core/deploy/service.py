"""Preview deployments: copy workspace, run an isolated container, health check."""
import asyncio
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import structlog

from app.config import settings
from app.core.contracts.service import parse_nova_config
from app.core.deploy import ledger
from app.core.indexing.pipeline import get_repo
from app.core.security.audit import AuditAction, log_audit
from app.core.tools.run_code import _collect_repo_files

logger = structlog.get_logger()

DEFAULT_COMMAND = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
DEFAULT_HEALTH = "/health"
HEALTH_TIMEOUT_S = 45


class DeployError(ValueError):
    """Deployment could not be started; the message is user-facing."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_docker(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


async def _docker(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(_run_docker, args, timeout)


async def _git_head(root: Path) -> str:
    if not (root / ".git").is_dir():
        return ""
    result = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _preview_config(files: dict[str, str]) -> tuple[str, str]:
    config = parse_nova_config(files.get("nova.yaml", ""))
    preview = config.get("preview") if isinstance(config.get("preview"), dict) else {}
    command = str(preview.get("command") or DEFAULT_COMMAND)
    health = str(preview.get("health") or DEFAULT_HEALTH)
    return command, health


async def _wait_health(url: str, health_path: str, timeout: int = HEALTH_TIMEOUT_S) -> bool:
    paths = [health_path]
    if health_path != "/":
        paths.append("/")
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2.0, follow_redirects=True, trust_env=False) as client:
        while time.monotonic() < deadline:
            for path in paths:
                try:
                    response = await client.get(url + path)
                    if response.status_code < 500:
                        return True
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(1)
    return False


async def _container_logs(name: str) -> str:
    try:
        result = await _docker(["docker", "logs", "--tail", "80", name], timeout=15)
        return ((result.stdout or "") + "\n" + (result.stderr or ""))[-4000:]
    except Exception:  # noqa: BLE001
        return ""


async def _remove_container(name: str) -> None:
    try:
        await _docker(["docker", "rm", "-f", name], timeout=20)
    except Exception:  # noqa: BLE001
        pass


def _deployment_dict(row) -> dict:
    return {
        "id": str(row[0]), "user_id": row[1], "repo_id": str(row[2]),
        "action_id": str(row[3]) if row[3] else None,
        "container_name": row[4], "host_port": row[5], "url": row[6],
        "status": row[7], "image": row[8], "command": row[9],
        "workspace_path": row[10], "error": row[11],
        "created_at": row[12], "updated_at": row[13], "stopped_at": row[14],
    }


async def get_deployment(deploy_id: str, user_id: int) -> dict | None:
    from app.db import query

    rows = await query(
        "SELECT id, user_id, repo_id, action_id, container_name, host_port, url, "
        "status, image, command, workspace_path, error, created_at, updated_at, stopped_at "
        "FROM deployments WHERE id = %s AND user_id = %s",
        (deploy_id, user_id),
    )
    return _deployment_dict(rows[0]) if rows else None


async def list_deployments(user_id: int, repo_id: str | None = None, limit: int = 20) -> list[dict]:
    from app.db import query

    sql = (
        "SELECT id, user_id, repo_id, action_id, container_name, host_port, url, "
        "status, image, command, workspace_path, error, created_at, updated_at, stopped_at "
        "FROM deployments WHERE user_id = %s"
    )
    params: list = [user_id]
    if repo_id:
        sql += " AND repo_id = %s"
        params.append(repo_id)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(max(1, min(limit, 50)))
    rows = await query(sql, tuple(params))
    return [_deployment_dict(row) for row in rows]


async def deploy_preview(user: dict, repo_id: str, force: bool = False) -> dict:
    repo = await get_repo(repo_id, user["id"])
    if not repo:
        raise DeployError("仓库不存在或无权访问")
    if repo["status"] != "ready":
        raise DeployError("仓库尚未完成索引，无法部署预览")

    files = await _collect_repo_files(repo_id, user)
    if not files:
        raise DeployError("仓库没有可部署文件")
    if "package.json" in files and "app/main.py" not in files:
        raise DeployError("当前预览部署仅支持 Python/FastAPI 项目（需要 app/main.py）")
    if "app/main.py" not in files and "nova.yaml" not in files:
        raise DeployError("未找到 app/main.py；可在 nova.yaml 的 preview.command 指定启动命令")

    command, health = _preview_config(files)
    root = Path(repo["root_path"])
    head = await _git_head(root)
    base_key = f"{user['id']}:deploy:{repo_id}:{head or 'nogit'}"
    key = f"{base_key}:force:{uuid.uuid4().hex[:8]}" if force else base_key

    existing = await ledger.get(key)
    if existing and existing["status"] == "pending":
        raise DeployError("该版本正在部署中，请稍后刷新")
    if existing and existing["status"] == "succeeded" and not force:
        deployment = await get_deployment(
            str((existing.get("response") or {}).get("deployment_id") or ""), user["id"]
        )
        if deployment and deployment["status"] == "running":
            return deployment
        key = f"{base_key}:redeploy:{uuid.uuid4().hex[:8]}"
        existing = None
    if existing and existing["status"] in ("failed", "unknown") and not force:
        await ledger.mark_pending(key)

    action = await ledger.begin(
        user["id"], key, "deploy", repo_id,
        {"repo_id": repo_id, "command": command, "head": head},
    )
    deploy_id = str(uuid.uuid4())
    container_name = f"nova-preview-{deploy_id[:12]}"
    workspace = Path(tempfile.mkdtemp(prefix="nova_preview_"))
    for rel, content in files.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    from app.db import execute

    await execute(
        "INSERT INTO deployments "
        "(id, user_id, repo_id, action_id, container_name, status, image, command, workspace_path) "
        "VALUES (%s, %s, %s, %s, %s, 'starting', %s, %s, %s)",
        (deploy_id, user["id"], repo_id, action["id"], container_name,
         settings.sandbox_builder_image, command, str(workspace)),
    )
    await log_audit(
        AuditAction.DEPLOY, user_id=str(user["id"]),
        details={"deployment_id": deploy_id, "repo_id": repo_id, "command": command[:300]},
    )

    port = _free_port()
    docker_args = [
        "docker", "run", "-d", "--name", container_name,
        "--label", f"nova.preview_id={deploy_id}",
        "--label", f"nova.user_id={user['id']}",
        "-p", f"127.0.0.1:{port}:8000",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "128", "--memory", settings.sandbox_memory,
        "--cpus", settings.sandbox_cpus, "--tmpfs", "/tmp:rw,size=64m",
        "-v", f"{workspace}:/workspace:rw", "-w", "/workspace",
        "--user", "65534:65534",
        settings.sandbox_builder_image, "sh", "-c", command,
    ]
    url = f"http://127.0.0.1:{port}"
    try:
        started = await _docker(docker_args, timeout=60)
        if started.returncode != 0:
            raise DeployError(f"容器启动失败：{(started.stderr or started.stdout)[:800]}")
        if not await _wait_health(url, health):
            logs = await _container_logs(container_name)
            raise DeployError(f"健康检查未通过：\n{logs[-1200:]}")
        await execute(
            "UPDATE deployments SET status = 'running', host_port = %s, url = %s, "
            "updated_at = now() WHERE id = %s",
            (port, url, deploy_id),
        )
        await ledger.finish(key, "succeeded", {"deployment_id": deploy_id, "url": url})
        logger.info("preview_running", deployment_id=deploy_id, url=url)
        return await get_deployment(deploy_id, user["id"]) or {}
    except Exception as exc:  # noqa: BLE001
        await _remove_container(container_name)
        shutil.rmtree(workspace, ignore_errors=True)
        detail = str(exc)[:2000]
        await execute(
            "UPDATE deployments SET status = 'failed', error = %s, updated_at = now() WHERE id = %s",
            (detail, deploy_id),
        )
        await ledger.finish(key, "failed", error=detail)
        if isinstance(exc, DeployError):
            raise
        raise DeployError(detail)


async def teardown_preview(user: dict, deploy_id: str) -> dict:
    deployment = await get_deployment(deploy_id, user["id"])
    if not deployment:
        raise DeployError("预览不存在")
    if deployment["status"] == "stopped":
        return deployment

    await _remove_container(deployment["container_name"])
    if deployment.get("workspace_path"):
        shutil.rmtree(deployment["workspace_path"], ignore_errors=True)
    from app.db import execute

    await execute(
        "UPDATE deployments SET status = 'stopped', stopped_at = now(), updated_at = now() "
        "WHERE id = %s AND user_id = %s",
        (deploy_id, user["id"]),
    )
    teardown_key = f"{user['id']}:teardown:{deploy_id}"
    await ledger.begin(user["id"], teardown_key, "teardown", deploy_id, {"deployment_id": deploy_id})
    await ledger.finish(teardown_key, "succeeded", {"deployment_id": deploy_id, "status": "stopped"})
    await log_audit(
        AuditAction.DEPLOY_STOP, user_id=str(user["id"]),
        details={"deployment_id": deploy_id, "container": deployment["container_name"]},
    )
    return await get_deployment(deploy_id, user["id"]) or {}
