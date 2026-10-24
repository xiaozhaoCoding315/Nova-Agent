"""Best-effort removal of a user's external resources before DB deletion."""
import structlog

from app.core.storage.user_storage import cleanup_user_storage
from app.db import execute, query

logger = structlog.get_logger()


async def purge_user_resources(user_id: int) -> dict:
    from app.core.deploy.service import cleanup_repo_resources

    repos = await query("SELECT id FROM repos WHERE user_id = %s", (user_id,))
    containers = workspaces = volumes = vectors = 0
    for (repo_id,) in repos:
        try:
            result = await cleanup_repo_resources(str(repo_id), user_id)
            containers += result.get("containers", 0)
            workspaces += result.get("workspaces", 0)
            volumes += result.get("volumes", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("user_repo_cleanup_failed", repo_id=str(repo_id), error=str(exc))
        try:
            from app.db.qdrant import delete_repo_points
            await delete_repo_points(str(repo_id))
            vectors += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("user_vector_cleanup_failed", repo_id=str(repo_id), error=str(exc))

    await cleanup_user_storage(user_id)
    await execute("DELETE FROM usage_log WHERE user_id = %s", (user_id,))
    await execute("DELETE FROM audit_log WHERE user_id = %s", (str(user_id),))
    return {
        "repos": len(repos), "containers": containers,
        "workspaces": workspaces, "volumes": volumes, "vectors": vectors,
    }


async def cleanup_expired_guests(limit: int = 50) -> int:
    rows = await query(
        "SELECT id FROM users WHERE is_guest = TRUE AND expires_at IS NOT NULL "
        "AND expires_at < now() ORDER BY expires_at LIMIT %s",
        (limit,),
    )
    removed = 0
    for (user_id,) in rows:
        try:
            await purge_user_resources(int(user_id))
            await execute("DELETE FROM users WHERE id = %s", (user_id,))
            removed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("guest_cleanup_failed", user_id=user_id, error=str(exc))
    if removed:
        logger.info("expired_guests_removed", count=removed)
    return removed
