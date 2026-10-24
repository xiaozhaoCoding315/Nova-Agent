"""Per-user file storage and chat attachment tool."""
from pathlib import Path

import pytest

from app.config import settings
from app.core.storage import user_storage
from app.core.tools import build_registry
from app.core.tools.base import ToolContext

USER = {"id": 7, "username": "u", "role": "demo"}


class FakeUpload:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def test_sanitize_filename_strips_paths_and_control_chars():
    assert user_storage.sanitize_filename("../../etc/passwd") == "passwd"
    assert user_storage.sanitize_filename("a\x00b?.txt") == "a_b_.txt"
    assert user_storage.sanitize_filename("") == "file"


def test_storage_limit_uses_guest_quota():
    guest = user_storage.storage_limit_bytes({"is_guest": True})
    normal = user_storage.storage_limit_bytes({"is_guest": False})
    assert guest == settings.guest_storage_mb * 1024 * 1024
    assert normal == settings.user_storage_mb * 1024 * 1024


@pytest.mark.asyncio
async def test_save_upload_writes_under_user_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path))
    captured = {}

    async def fake_execute(_sql, params):
        captured["params"] = params
        return [(
            params[0], params[1], params[2], params[3], params[4],
            params[5], params[6], params[7], params[9], None,
        )]

    monkeypatch.setattr(user_storage, "execute", fake_execute)

    saved = await user_storage.save_upload(
        USER["id"],
        FakeUpload([b"hello", b" world"]),
        filename="notes.txt",
        mime="text/plain",
    )

    path = Path(captured["params"][8])
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello world"
    assert USER["id"] == captured["params"][1]
    assert path.parent == tmp_path / str(USER["id"]) / "uploads"
    assert saved["filename"] == "notes.txt"
    assert saved["size"] == 11


@pytest.mark.asyncio
async def test_save_upload_rejects_oversized_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "user_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "attachment_max_mb", 0)

    with pytest.raises(ValueError):
        await user_storage.save_upload(
            USER["id"], FakeUpload([b"too large"]), filename="big.txt"
        )
    uploads = tmp_path / str(USER["id"]) / "uploads"
    assert not uploads.exists() or not list(uploads.iterdir())


@pytest.mark.asyncio
async def test_read_text_rejects_binary_and_reads_text(monkeypatch, tmp_path):
    text_path = tmp_path / "a.txt"
    text_path.write_text("print('hi')", encoding="utf-8")

    async def fake_get_file(_file_id, _user_id):
        return {
            "id": "f1", "filename": "a.txt", "mime": "text/plain",
            "size": 11, "storage_path": str(text_path),
        }

    monkeypatch.setattr(user_storage, "get_file", fake_get_file)
    data = await user_storage.read_text("f1", USER["id"])
    assert data["content"] == "print('hi')"

    async def binary_file(_file_id, _user_id):
        return {
            "id": "f2", "filename": "a.bin", "mime": "application/octet-stream",
            "size": 3, "storage_path": str(text_path),
        }

    monkeypatch.setattr(user_storage, "get_file", binary_file)
    with pytest.raises(ValueError):
        await user_storage.read_text("f2", USER["id"])


@pytest.mark.asyncio
async def test_attachment_tool_only_reads_current_turn_files(monkeypatch):
    async def fake_read(file_id, user_id, max_chars=50_000):
        return {
            "id": file_id, "filename": "a.txt", "size": 2,
            "content": "ok", "truncated": False,
        }

    monkeypatch.setattr("app.core.tools.read_attachment.read_text", fake_read)

    registry = build_registry()
    r = await registry.execute(
        "read_uploaded_file", {"file_id": "f1"},
        ToolContext(user=USER, file_ids=["f1"]),
    )
    assert r["ok"] and r["output"]["content"] == "ok"

    r = await registry.execute(
        "read_uploaded_file", {"file_id": "other"},
        ToolContext(user=USER, file_ids=["f1"]),
    )
    assert r["ok"] is False and r["business"] is True
