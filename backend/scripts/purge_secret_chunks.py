"""One-off cleanup: remove secret-path files from existing indexes.

Run once after upgrading to the version that filters secret paths, so rows
created by older indexes no longer sit in PostgreSQL/Qdrant:

    cd backend && python -m scripts.purge_secret_chunks --dry-run
    cd backend && python -m scripts.purge_secret_chunks

Idempotent; safe to re-run.  Retrieval already filters secret paths, but this
removes the stored content as well.
"""
import argparse
import asyncio
import json

import structlog

from app.core.security.paths import is_secret_path
from app.db import execute, query

logger = structlog.get_logger()


async def purge(dry_run: bool = False, repo_id: str | None = None) -> dict:
    sql = "SELECT id, repo_id, path FROM repo_files"
    params: tuple = ()
    if repo_id:
        sql += " WHERE repo_id = %s"
        params = (repo_id,)
    rows = await query(sql, params)
    targets = [row for row in rows if is_secret_path(row[2])]
    summary = {
        "scanned_files": len(rows),
        "secret_files": len(targets),
        "chunks": 0,
        "points": 0,
        "dry_run": dry_run,
        "repo_id": repo_id,
    }

    for file_id, _rid, path in targets:
        chunk_rows = await query(
            "SELECT id FROM chunks WHERE file_id = %s", (file_id,)
        )
        chunk_ids = [int(row[0]) for row in chunk_rows]
        summary["chunks"] += len(chunk_ids)
        if dry_run:
            logger.info("purge_secret_dry_run", file_id=file_id, path=path,
                        chunks=len(chunk_ids))
            continue

        if chunk_ids:
            try:
                from app.db.qdrant import delete_point_ids
                summary["points"] += await delete_point_ids(chunk_ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("purge_qdrant_failed", path=path, error=str(exc))
        await execute("DELETE FROM chunks WHERE file_id = %s", (file_id,))
        await execute("DELETE FROM symbols WHERE file_id = %s", (file_id,))
        await execute("DELETE FROM repo_files WHERE id = %s", (file_id,))
        logger.info("purged_secret_file", file_id=file_id, path=path,
                    chunks=len(chunk_ids))

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge secret-path files from old indexes")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo-id", default=None)
    args = parser.parse_args()
    summary = asyncio.run(purge(dry_run=args.dry_run, repo_id=args.repo_id))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
