"""Repo indexing pipeline: walk → symbols → chunks → PostgreSQL + Qdrant.

Runs as a background task per repo; status transitions
pending → indexing → ready | failed with the error message persisted.
"""
import json
import shutil
from pathlib import Path

import structlog

from app.config import settings
from app.core.indexing import chunker
from app.core.indexing.languages import detect_language
from app.core.indexing.symbols import extract_symbols
from app.core.indexing.walker import iter_source_files
from app.db import execute, query

logger = structlog.get_logger()

EMBED_BATCH = 10
EMBEDDING_CHAR_LIMIT = 2000


async def create_repo_row(user_id: int, name: str, source: str, repo_id: str) -> dict:
    root_path = str(Path(settings.repos_dir) / repo_id)
    await execute(
        "INSERT INTO repos (id, user_id, name, source, root_path, status) "
        "VALUES (%s, %s, %s, %s, %s, 'pending')",
        (repo_id, user_id, name[:200], source[:500], root_path),
    )
    return {"id": repo_id, "name": name[:200], "source": source[:500],
            "root_path": root_path, "status": "pending"}


async def set_status(repo_id: str, status: str, error: str | None = None) -> None:
    await execute(
        "UPDATE repos SET status = %s, error = %s, updated_at = now() WHERE id = %s",
        (status, error[:500] if error else None, repo_id),
    )


async def get_repo(repo_id: str, user_id: int | None = None) -> dict | None:
    sql = "SELECT id, user_id, name, source, root_path, status, error, stats, created_at FROM repos WHERE id = %s"
    params: tuple = (repo_id,)
    if user_id is not None:
        sql += " AND user_id = %s"
        params = (repo_id, user_id)
    rows = await query(sql, params)
    if not rows:
        return None
    r = rows[0]
    return {
        "id": str(r[0]), "user_id": r[1], "name": r[2], "source": r[3],
        "root_path": r[4], "status": r[5], "error": r[6], "stats": r[7] or {}, "created_at": r[8],
    }


async def list_repos(user_id: int) -> list[dict]:
    rows = await query(
        "SELECT id, name, source, status, error, stats, created_at FROM repos "
        "WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )
    return [
        {"id": str(r[0]), "name": r[1], "source": r[2], "status": r[3],
         "error": r[4], "stats": r[5] or {}, "created_at": r[6]}
        for r in rows
    ]


async def delete_repo(repo_id: str, user_id: int) -> bool:
    repo = await get_repo(repo_id, user_id)
    if not repo:
        return False
    await execute("DELETE FROM repos WHERE id = %s AND user_id = %s", (repo_id, user_id))
    shutil.rmtree(repo["root_path"], ignore_errors=True)
    try:
        from app.db.qdrant import delete_repo_points
        await delete_repo_points(repo_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("qdrant_cleanup_failed", repo_id=repo_id, error=str(exc))
    return True


def _read_text(abspath: str, lang: str) -> str:
    if lang == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(abspath)
            return "\n".join((page.extract_text() or "") for page in reader.pages[:200])
        except Exception as exc:  # noqa: BLE001
            logger.info("pdf_extract_failed", path=abspath, error=str(exc))
            return ""
    try:
        return Path(abspath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


async def _insert_file(repo_id: str, rel: str, lang: str, size: int, line_count: int, is_doc: bool) -> int:
    rows = await execute(
        "INSERT INTO repo_files (repo_id, path, language, size, line_count, is_doc) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (repo_id, rel, lang, size, line_count, is_doc),
    )
    return rows[0][0]


async def _insert_symbols(repo_id: str, file_id: int, symbols: list[dict]) -> None:
    if not symbols:
        return
    from app.db import transaction
    await transaction([
        (
            "INSERT INTO symbols (repo_id, file_id, kind, name, parent, line_start, line_end, signature) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (repo_id, file_id, s["kind"], s["name"][:200], s["parent"][:200] or None,
             s["line_start"], s["line_end"], s["signature"][:300]),
        )
        for s in symbols
    ])


async def _insert_chunks(repo_id: str, file_id: int, chunks: list[dict]) -> list[int]:
    from app.utils.chinese_analyzer import tokenized_text
    ids: list[int] = []
    for ch in chunks:
        rows = await execute(
            "INSERT INTO chunks (repo_id, file_id, content, line_start, line_end, lang, kind, tsv) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, to_tsvector('simple', %s)) RETURNING id",
            (repo_id, file_id, ch["content"], ch["line_start"], ch["line_end"],
             ch["lang"][:32], ch["kind"], tokenized_text(ch["content"])),
        )
        ids.append(rows[0][0])
    return ids


async def _embed_and_upload(repo_id: str, pending: list[tuple[int, dict, str]]) -> int:
    if not pending:
        return 0
    try:
        from app.core.embedding.embedder import get_embedder
        embedder = get_embedder()
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding_unavailable_keyword_only", error=str(exc))
        return 0

    from qdrant_client.models import PointStruct
    from app.db.qdrant import upsert_points

    cap = pending[: settings.index_embed_max_chunks]
    uploaded = 0
    for i in range(0, len(cap), EMBED_BATCH):
        batch = cap[i:i + EMBED_BATCH]
        try:
            vectors = await embedder.embed([ch["content"][:EMBEDDING_CHAR_LIMIT] for _, ch, _ in batch])
        except Exception as exc:  # noqa: BLE001
            logger.warning("embed_batch_failed", repo_id=repo_id, offset=i, error=str(exc))
            break
        points = [
            PointStruct(
                id=chunk_id,
                vector=vec,
                payload={
                    "repo_id": repo_id, "path": rel,
                    "line_start": ch["line_start"], "line_end": ch["line_end"],
                    "lang": ch["lang"], "kind": ch["kind"],
                    "content": ch["content"][:EMBEDDING_CHAR_LIMIT],
                },
            )
            for (chunk_id, ch, rel), vec in zip(batch, vectors)
        ]
        try:
            await upsert_points(points)
            uploaded += len(points)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant_upsert_failed", repo_id=repo_id, offset=i, error=str(exc))
            break
    return uploaded


async def index_repo(repo_id: str) -> None:
    """Background entrypoint: index (or re-index) one repo end-to-end."""
    repo = await get_repo(repo_id)
    if not repo:
        return
    root = repo["root_path"]
    await set_status(repo_id, "indexing")
    logger.info("index_started", repo_id=repo_id, name=repo["name"])

    try:
        from app.core.indexing.walker import strip_root_dir
        root = strip_root_dir(root)
        # Persist the resolved root so the file-viewer endpoint reads the
        # same directory the indexer walked (zips often nest one top dir).
        await execute("UPDATE repos SET root_path = %s WHERE id = %s", (root, repo_id))

        files = list(iter_source_files(root, settings.max_file_kb * 1024))[: settings.max_repo_files]
        stats = {"files": 0, "chunks": 0, "symbols": 0, "embedded": 0}
        pending: list[tuple[int, dict, str]] = []

        for rel, abspath, size in files:
            lang, is_doc = detect_language(rel)
            content = _read_text(abspath, lang)
            if not content or not content.strip():
                continue
            file_id = await _insert_file(repo_id, rel, lang, size, content.count("\n") + 1, is_doc)

            symbols = [] if is_doc else extract_symbols(content, lang)
            await _insert_symbols(repo_id, file_id, symbols)

            chunks = chunker.chunk_file(content, lang, is_doc)
            chunk_ids = await _insert_chunks(repo_id, file_id, chunks)
            pending.extend((cid, ch, rel) for cid, ch in zip(chunk_ids, chunks))

            stats["files"] += 1
            stats["symbols"] += len(symbols)
            stats["chunks"] += len(chunks)

        stats["embedded"] = await _embed_and_upload(repo_id, pending)
        await execute(
            "UPDATE repos SET status = 'ready', stats = %s, error = NULL, updated_at = now() WHERE id = %s",
            (json.dumps(stats, ensure_ascii=False), repo_id),
        )
        logger.info("index_done", repo_id=repo_id, **stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("index_failed", repo_id=repo_id)
        await set_status(repo_id, "failed", str(exc))


async def reindex_repo(repo_id: str) -> None:
    """Clear derived data, then rebuild."""
    await execute("DELETE FROM repo_files WHERE repo_id = %s", (repo_id,))
    await execute("DELETE FROM symbols WHERE repo_id = %s", (repo_id,))
    await execute("DELETE FROM chunks WHERE repo_id = %s", (repo_id,))
    try:
        from app.db.qdrant import delete_repo_points
        await delete_repo_points(repo_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("qdrant_cleanup_failed", repo_id=repo_id, error=str(exc))
    await index_repo(repo_id)