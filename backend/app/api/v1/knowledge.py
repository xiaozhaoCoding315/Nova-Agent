from fastapi import APIRouter, UploadFile, File, HTTPException
from app.core.knowledge.pipeline import process_and_index
from app.db import query, execute

router = APIRouter()


async def _list_docs():
    try:
        rows = await query("SELECT source, COUNT(*) FROM documents GROUP BY source")
        return [{"name": r[0], "chunks": r[1]} for r in rows]
    except Exception:
        return []


@router.get("/knowledge")
async def list_knowledge():
    return {"documents": await _list_docs()}


_ALLOWED_EXTS = (
    '.md', '.markdown', '.txt',
    '.py', '.java', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs',
    '.cpp', '.cc', '.c', '.h', '.hpp', '.cs', '.rb', '.php', '.kt', '.swift',
    '.sql', '.sh', '.yaml', '.yml', '.json', '.toml',
)


@router.post("/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    if not file.filename.lower().endswith(_ALLOWED_EXTS):
        raise HTTPException(status_code=400, detail="Unsupported file type")
    raw = (await file.read()).decode("utf-8", errors="replace")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    try:
        result = await process_and_index(file.filename, raw)
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


@router.delete("/knowledge/{doc_name:path}")
async def delete_knowledge(doc_name: str):
    await execute("DELETE FROM documents WHERE source = %s", (doc_name,))
    return {"status": "ok", "deleted": doc_name}
