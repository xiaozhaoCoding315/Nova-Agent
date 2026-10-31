"""Repo indexing pipeline: walk → symbols → chunks → PostgreSQL + Qdrant.

Runs as a background task per repo; status transitions
pending → indexing → ready | failed with the error message persisted.
"""
import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import structlog

from app.config import settings
from app.core.indexing import chunker
from app.core.indexing.imports import extract_imports
from app.core.indexing.languages import detect_language
from app.core.indexing.symbols import extract_symbols
from app.core.indexing.walker import iter_source_files
from app.db import execute, query

logger = structlog.get_logger()

EMBED_BATCH = 10
EMBEDDING_CHAR_LIMIT = 2000


async def create_repo_row(
    user_id: int, name: str, source: str, repo_id: str, origin: str = "upload"
) -> dict:
    from app.core.storage.user_storage import repo_container
    root = repo_container(user_id, repo_id)
    root.mkdir(parents=True, exist_ok=True)
    root_path = str(root)
    await execute(
        "INSERT INTO repos (id, user_id, name, source, root_path, status, origin) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
        (repo_id, user_id, name[:200], source[:500], root_path, origin),
    )
    return {"id": repo_id, "name": name[:200], "source": source[:500],
            "root_path": root_path, "status": "pending", "origin": origin}


async def create_local_repo_row(
    user_id: int, name: str, root_path: str, repo_id: str
) -> dict:
    source = f"local:{root_path}"
    await execute(
        "INSERT INTO repos (id, user_id, name, source, root_path, status, origin) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', 'local')",
        (repo_id, user_id, name[:200], source[:500], root_path),
    )
    return {"id": repo_id, "name": name[:200], "source": source[:500],
            "root_path": root_path, "status": "pending", "origin": "local"}


async def set_status(repo_id: str, status: str, error: str | None = None) -> None:
    await execute(
        "UPDATE repos SET status = %s, error = %s, updated_at = now() WHERE id = %s",
        (status, error[:500] if error else None, repo_id),
    )


async def get_repo(repo_id: str, user_id: int | None = None) -> dict | None:
    sql = ("SELECT id, user_id, name, source, root_path, status, error, stats, created_at, kind, rules, "
           "stack_mode, brief, smoke, origin FROM repos WHERE id = %s")
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
        "root_path": r[4], "status": r[5], "error": r[6], "stats": r[7] or {},
        "created_at": r[8], "kind": r[9] or "import", "rules": r[10] or "",
        "stack_mode": r[11] or "python", "brief": r[12] or "", "smoke": r[13],
        "origin": r[14] or "upload",
    }


async def list_repos(user_id: int) -> list[dict]:
    rows = await query(
        "SELECT id, name, source, status, error, stats, created_at, kind, origin FROM repos "
        "WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )
    return [
        {"id": str(r[0]), "name": r[1], "source": r[2], "status": r[3],
         "error": r[4], "stats": r[5] or {}, "created_at": r[6], "kind": r[7] or "import",
         "origin": r[8] or "upload"}
        for r in rows
    ]


async def delete_repo(repo_id: str, user_id: int) -> bool:
    repo = await get_repo(repo_id, user_id)
    if not repo:
        return False
    try:
        from app.core.deploy.service import cleanup_repo_resources
        await cleanup_repo_resources(repo_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("repo_resource_cleanup_failed", repo_id=repo_id, error=str(exc))
    await execute("DELETE FROM repos WHERE id = %s AND user_id = %s", (repo_id, user_id))
    if repo.get("origin") == "local":
        logger.info("local_project_unregistered", repo_id=repo_id)
    else:
        from app.core.storage.user_storage import repo_container
        shutil.rmtree(repo_container(user_id, repo_id), ignore_errors=True)
        shutil.rmtree(Path(settings.repos_dir) / repo_id, ignore_errors=True)
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


async def _insert_file(
    repo_id: str, rel: str, lang: str, size: int, line_count: int,
    is_doc: bool, content_hash: str,
) -> int:
    rows = await execute(
        "INSERT INTO repo_files "
        "(repo_id, path, language, size, line_count, is_doc, content_hash) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (repo_id, rel, lang, size, line_count, is_doc, content_hash),
    )
    return rows[0][0]


def _same_file(old: dict | None, current_hash: str, size: int, force: bool = False) -> bool:
    return bool(
        old and not force
        and old.get("hash") == current_hash
        and old.get("size") == size
    )


def _file_hash(abspath: str) -> str:
    digest = hashlib.sha256()
    with open(abspath, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _delete_file_data(file_id: int) -> None:
    """Delete one file's chunks/symbols/deps and its vectors."""
    rows = await query("SELECT id FROM chunks WHERE file_id = %s", (file_id,))
    chunk_ids = [int(row[0]) for row in rows]
    if chunk_ids:
        try:
            from app.db.qdrant import delete_point_ids
            await delete_point_ids(chunk_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant_file_delete_failed", file_id=file_id, error=str(exc))
    # chunks/symbols/file_deps cascade from repo_files.
    await execute("DELETE FROM repo_files WHERE id = %s", (file_id,))


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


async def _embed_and_upload(
    repo_id: str, user_id: int, pending: list[tuple[int, dict, str]]
) -> int:
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
                    "user_id": user_id, "repo_id": repo_id, "path": rel,
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


async def index_repo(repo_id: str, ctx=None, force: bool = False) -> None:
    """Index a repo incrementally: only changed/new files are re-processed."""
    repo = await get_repo(repo_id)
    if not repo:
        return
    root = repo["root_path"]
    await set_status(repo_id, "indexing")
    logger.info("index_started", repo_id=repo_id, name=repo["name"])

    try:
        if ctx:
            await ctx.check_cancel()
            await ctx.update(progress=0.02, step="扫描文件")
        from app.core.indexing.walker import iter_local_project_files, strip_root_dir

        if repo.get("origin") != "local":
            root = strip_root_dir(root)
        # Persist the resolved root so the file-viewer endpoint reads the
        # same directory the indexer walked (zips often nest one top dir).
        await execute("UPDATE repos SET root_path = %s WHERE id = %s", (root, repo_id))

        if force:
            await execute("DELETE FROM repo_files WHERE repo_id = %s", (repo_id,))
            try:
                from app.db.qdrant import delete_repo_points
                await delete_repo_points(repo_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("qdrant_cleanup_failed", repo_id=repo_id, error=str(exc))

        rows = await query(
            "SELECT id, path, language, size, line_count, is_doc, content_hash "
            "FROM repo_files WHERE repo_id = %s",
            (repo_id,),
        )
        existing = {
            row[1]: {
                "id": int(row[0]), "language": row[2] or "",
                "size": int(row[3] or 0), "line_count": int(row[4] or 0),
                "is_doc": bool(row[5]), "hash": row[6],
            }
            for row in rows
        }

        if repo.get("origin") == "local":
            iterator = iter_local_project_files(root, settings.max_file_kb * 1024)
        else:
            iterator = iter_source_files(root, settings.max_file_kb * 1024)
        files = list(iterator)[: settings.max_repo_files]
        stats = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0, "embedded": 0}
        pending: list[tuple[int, dict, str]] = []
        file_meta: list[dict] = []
        raw_deps: list[dict] = []
        seen: set[str] = set()

        for index, (rel, abspath, size) in enumerate(files):
            if ctx and index % 10 == 0:
                await ctx.check_cancel()
                await ctx.update(progress=min(0.55, 0.05 + 0.5 * index / max(1, len(files))))
            seen.add(rel)
            current_hash = await asyncio.to_thread(_file_hash, abspath)
            old = existing.get(rel)
            if _same_file(old, current_hash, size, force):
                language = old["language"] or detect_language(rel)[0]
                file_meta.append({
                    "path": rel, "language": language,
                    "line_count": old["line_count"], "is_doc": old["is_doc"],
                })
                stats["skipped"] += 1
                continue

            if old:
                await _delete_file_data(old["id"])

            lang, is_doc = detect_language(rel)
            content = _read_text(abspath, lang)
            if not content or not content.strip():
                if old:
                    stats["deleted"] += 1
                continue
            line_count = content.count("\n") + 1
            file_id = await _insert_file(
                repo_id, rel, lang, size, line_count, is_doc, current_hash
            )
            file_meta.append({
                "path": rel, "language": lang,
                "line_count": line_count, "is_doc": is_doc,
            })
            stats["updated" if old else "added"] += 1

            symbols = [] if is_doc else extract_symbols(content, lang)
            await _insert_symbols(repo_id, file_id, symbols)

            if not is_doc:
                for imp in extract_imports(content, lang):
                    raw_deps.append({"file_id": file_id, "source_path": rel, **imp})

            chunks = chunker.chunk_file(content, lang, is_doc)
            chunk_ids = await _insert_chunks(repo_id, file_id, chunks)
            pending.extend((cid, ch, rel) for cid, ch in zip(chunk_ids, chunks))

        for rel, old in existing.items():
            if rel not in seen:
                await _delete_file_data(old["id"])
                stats["deleted"] += 1

        if raw_deps:
            from app.db import transaction
            await transaction([
                (
                    "INSERT INTO file_deps "
                    "(repo_id, file_id, source_path, target, resolved_path, kind) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (repo_id, dep["file_id"], dep["source_path"], dep["target"], None, dep["kind"]),
                )
                for dep in raw_deps
            ])

        # Re-resolve every dependency row: a newly added file can resolve an
        # import that was previously unresolved.
        from app.core.indexing.imports import build_path_index, resolve_import
        path_set, suffix_index = build_path_index([m["path"] for m in file_meta])
        dep_rows = await query(
            "SELECT id, source_path, target, kind FROM file_deps WHERE repo_id = %s",
            (repo_id,),
        )
        dep_updates: list[tuple] = []
        resolved_deps: list[dict] = []
        for dep_id, source_path, target, kind in dep_rows:
            resolved = resolve_import(target, source_path, kind, path_set, suffix_index)
            dep_updates.append((resolved, dep_id))
            if resolved:
                resolved_deps.append({"source_path": source_path, "resolved_path": resolved})
        if dep_updates:
            from app.db import transaction
            await transaction([
                ("UPDATE file_deps SET resolved_path = %s WHERE id = %s", row)
                for row in dep_updates
            ])

        symbol_rows = await query(
            "SELECT s.kind, s.name, s.parent, s.line_start, s.line_end, s.signature, f.path "
            "FROM symbols s JOIN repo_files f ON f.id = s.file_id "
            "WHERE s.repo_id = %s",
            (repo_id,),
        )
        all_symbols = [
            {
                "kind": row[0], "name": row[1], "parent": row[2] or "",
                "line_start": row[3] or 0, "line_end": row[4] or 0,
                "signature": row[5] or "", "path": row[6],
            }
            for row in symbol_rows
        ]

        languages: dict[str, int] = {}
        for meta in file_meta:
            languages[meta["language"]] = languages.get(meta["language"], 0) + 1

        from app.core.indexing.brain import build_brain
        brain = build_brain(file_meta, all_symbols, resolved_deps, languages)

        if ctx:
            await ctx.check_cancel()
            await ctx.update(progress=0.65, step="生成向量索引")
        stats["embedded"] = await _embed_and_upload(repo_id, repo["user_id"], pending)
        stats["dependencies"] = len(resolved_deps)

        totals = await query(
            "SELECT COUNT(*) FROM repo_files WHERE repo_id = %s", (repo_id,)
        )
        chunk_totals = await query(
            "SELECT COUNT(*) FROM chunks WHERE repo_id = %s", (repo_id,)
        )
        symbol_totals = await query(
            "SELECT COUNT(*) FROM symbols WHERE repo_id = %s", (repo_id,)
        )
        stats["files"] = int(totals[0][0] or 0)
        stats["chunks"] = int(chunk_totals[0][0] or 0)
        stats["symbols"] = int(symbol_totals[0][0] or 0)

        await execute(
            "UPDATE repos SET status = 'ready', stats = %s, brain = %s, error = NULL, "
            "updated_at = now() WHERE id = %s",
            (json.dumps(stats, ensure_ascii=False), json.dumps(brain, ensure_ascii=False), repo_id),
        )
        logger.info("index_done", repo_id=repo_id, **stats)
    except Exception as exc:  # noqa: BLE001
        from app.core.jobs.models import JobCanceled
        if isinstance(exc, JobCanceled):
            logger.info("index_canceled", repo_id=repo_id)
            await set_status(repo_id, "pending", "索引已取消")
            raise
        logger.exception("index_failed", repo_id=repo_id)
        await set_status(repo_id, "failed", str(exc))


async def reindex_repo(repo_id: str, ctx=None, force: bool = False) -> None:
    """Incrementally re-index; ``force`` clears everything first."""
    if ctx:
        await ctx.check_cancel()
    await index_repo(repo_id, ctx=ctx, force=force)