"""Builder smoke boot: after a generated project is approved and written,
boot it in an isolated preview container, hit the health endpoint, then tear
the container down immediately. "It compiles" becomes "it runs".
"""
import json
import time

import structlog

from app.config import settings
from app.db import execute, query

logger = structlog.get_logger()

HEALTH_TIMEOUT_S = 60


async def run_smoke(repo_id: str, user: dict) -> dict:
    """Boot → health check → teardown. Returns the recorded result dict."""
    from app.core.deploy.service import deploy_preview, teardown_preview

    started = time.perf_counter()
    result: dict = {"ok": False, "status": "skipped"}
    deployment: dict | None = None
    try:
        if not settings.sandbox_enabled:
            result = {"ok": False, "status": "skipped", "note": "沙箱未启用"}
            return result
        # Proposal approval re-indexes first; wait for the repo to become ready.
        ready = False
        for _ in range(30):
            rows = await query("SELECT status FROM repos WHERE id = %s", (repo_id,))
            status = (rows[0][0] if rows else "missing")
            if status == "ready":
                ready = True
                break
            if status in ("failed", "missing"):
                break
            await _sleep(4)
        if not ready:
            result = {"ok": False, "status": "skipped", "note": "仓库索引未就绪，跳过冒烟"}
            return result
        # deploy_preview raises (with container logs) when the health check
        # fails; returning means the app booted and answered.
        deployment = await deploy_preview(user, repo_id, force=True)
        healthy = deployment.get("status") == "running"
        result = {
            "ok": healthy,
            "status": "healthy" if healthy else "unhealthy",
            "url": deployment.get("url"),
            "deploy_id": deployment.get("id"),
        }
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "status": "error", "note": str(exc)[:500]}
    finally:
        if deployment and deployment.get("id"):
            try:
                await teardown_preview(user, str(deployment["id"]))
            except Exception as exc:  # noqa: BLE001
                logger.warning("smoke_teardown_failed", repo=repo_id, error=str(exc))
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    await execute(
        "UPDATE repos SET smoke = %s WHERE id = %s",
        (json.dumps(result, ensure_ascii=False), repo_id),
    )
    logger.info("builder_smoke_done", repo=repo_id, ok=result.get("ok"),
                status=result.get("status"))
    return result


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


async def get_smoke(repo_id: str) -> dict | None:
    rows = await query("SELECT smoke FROM repos WHERE id = %s", (repo_id,))
    return (rows[0][0] if rows else None) or None
