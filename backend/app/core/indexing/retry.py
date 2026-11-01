"""Re-enqueue index work that was lost during an unclean local shutdown."""
from app.config import settings
from app.core.jobs.service import enqueue_index
from app.db import query


async def retry_pending_indexes(stale_seconds: int = 600) -> int:
    if not settings.is_local:
        return 0
    rows = await query(
        """
        SELECT r.id, r.user_id FROM repos r
        WHERE r.status IN ('pending', 'indexing')
          AND r.updated_at < now() - (%s * interval '1 second')
          AND NOT EXISTS (
              SELECT 1 FROM jobs j
              WHERE j.kind = 'index'
                AND j.status IN ('queued', 'running')
                AND j.payload->>'repo_id' = r.id::text
          )
        ORDER BY r.updated_at
        LIMIT 20
        """,
        (stale_seconds,),
    )
    retried = 0
    for repo_id, user_id in rows:
        await enqueue_index(str(repo_id), user_id=user_id)
        retried += 1
    return retried
