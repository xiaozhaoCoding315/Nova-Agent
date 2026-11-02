"""Image attachment validation, data URLs and vision capability helpers."""
import base64
import struct

import pytest

from app.config import settings
from app.core.agent.image_input import (
    ImageRejected,
    build_user_content,
    is_image_rejection,
    is_vision_image,
    no_vision_content,
    sniff_image,
    strip_image_blocks,
    total_image_bytes,
    validate_image_bytes,
)


def png_bytes(width: int = 2, height: int = 3) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + ihdr
        + b"\x00\x00\x00\x00"
    )


def jpeg_bytes(width: int = 4, height: int = 5, *, app0: bytes = b"") -> bytes:
    sof = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03"
        + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def test_sniff_png_and_jpeg_headers():
    png = sniff_image(png_bytes(120, 80))
    assert png is not None
    assert (png.media_type, png.width, png.height) == ("image/png", 120, 80)

    app0 = b"\xff\xe0" + struct.pack(">H", 6) + b"JFIF\x00"
    jpeg = sniff_image(jpeg_bytes(640, 480, app0=app0))
    assert jpeg is not None
    assert (jpeg.media_type, jpeg.width, jpeg.height) == ("image/jpeg", 640, 480)


def test_sniff_rejects_truncated_and_foreign_bytes():
    assert sniff_image(b"not an image") is None
    assert sniff_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) is None
    assert sniff_image(b"\xff\xd8\xff" + b"\x00" * 4) is None
    assert sniff_image(b"GIF89a" + b"\x00" * 16) is None


def test_validate_rejects_fake_and_oversized_images():
    with pytest.raises(ImageRejected, match="PNG/JPEG"):
        validate_image_bytes(b"not a png")

    with pytest.raises(ImageRejected, match="单边"):
        validate_image_bytes(png_bytes(8001, 10), max_side=8000)

    with pytest.raises(ImageRejected, match="像素"):
        validate_image_bytes(png_bytes(8000, 6000), max_pixels=40_000_000)

    with pytest.raises(ImageRejected, match="上限"):
        validate_image_bytes(png_bytes(10, 10) + b"x" * 2048, max_kb=1)

    assert validate_image_bytes(png_bytes(10, 10), max_kb=1).media_type == "image/png"


def test_build_user_content_orders_text_then_images():
    blocks = build_user_content("图里是什么？", [{
        "mime": "image/png",
        "data": b"\x89PNG\r\n\x1a\n",
    }])
    assert blocks[0] == {"type": "text", "text": "图里是什么？"}
    assert blocks[1]["type"] == "image_url"
    prefix = "data:image/png;base64,"
    assert blocks[1]["image_url"]["url"].startswith(prefix)
    encoded = blocks[1]["image_url"]["url"][len(prefix):]
    assert base64.b64decode(encoded) == b"\x89PNG\r\n\x1a\n"


def test_no_vision_content_is_explicit():
    text = no_vision_content("看图")
    assert text.startswith("看图")
    assert "不支持图片输入" in text
    assert "不要声称看到了图片" in text


def test_strip_image_blocks_replaces_without_mutating_source():
    source = {"role": "user", "content": [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]}
    stripped = strip_image_blocks([source])
    assert stripped[0]["content"][0] == {"type": "text", "text": "看图"}
    assert stripped[0]["content"][1]["type"] == "text"
    assert "图片已省略" in stripped[0]["content"][1]["text"]
    assert source["content"][1]["type"] == "image_url"


def test_is_vision_image_and_total_image_bytes():
    attachments = [
        {"mime": "image/png", "size": 10},
        {"mime": "image/jpeg", "size": 20},
        {"mime": "text/plain", "size": 900},
    ]
    assert is_vision_image(attachments[0]) is True
    assert is_vision_image(attachments[2]) is False
    assert total_image_bytes(attachments) == 30


def test_is_image_rejection_only_for_image_related_4xx():
    class BadRequest(Exception):
        status_code = 400

    assert is_image_rejection(BadRequest("Invalid image content")) is True
    assert is_image_rejection(RuntimeError(
        "Anthropic API 400: messages.0.content.1.image: unsupported image"
    )) is True
    assert is_image_rejection(BadRequest("model not found")) is False
    assert is_image_rejection(RuntimeError("Anthropic API 500: image backend down")) is False


def test_image_settings_defaults():
    assert settings.image_input_max_kb == 3584
    assert settings.image_input_max_side == 8000
    assert settings.image_input_max_pixels == 40_000_000
    assert settings.image_input_max_total_kb == 10_240


from app.core.agent.context_governor import compact_messages
from app.core.agent.context_meter import IMAGE_TOKEN_ESTIMATE, estimate_messages


def test_estimate_messages_counts_image_blocks():
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
    }
    assert estimate_messages([message]) >= IMAGE_TOKEN_ESTIMATE


def test_compaction_never_stringifies_block_content():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": [
            {"type": "text", "text": "x" * 40_000},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "latest"},
    ]
    compact_messages(messages, window=10, keep_recent=1)
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_recent_messages_before_id_excludes_current(monkeypatch):
    from app.core.memory import session as session_mod

    captured = {}

    async def fake_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return [("user", "older")]

    monkeypatch.setattr(session_mod, "query", fake_query)
    rows = await session_mod.recent_messages("s1", before_id=42, user_id=7)
    assert "id < %s" in captured["sql"]
    assert 42 in captured["params"]
    assert rows == [{"role": "user", "content": "older"}]
