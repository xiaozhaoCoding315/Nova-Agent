"""First-class image attachments: validation, data URLs and vision blocks."""
from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
VISION_MEDIA_TYPES = frozenset({"image/png", "image/jpeg"})
VISION_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg));base64,([A-Za-z0-9+/=\s]+)$")
JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
IMAGE_ERROR_MARKERS = ("image", "vision", "media type", "content type", "图片", "图像")
NO_VISION_NOTE = (
    "（当前模型不支持图片输入，本轮上传的图片不会发送；不要声称看到了图片。）"
)
STRIPPED_IMAGE_NOTE = "（图片已省略：当前模型不支持图片输入）"


class ImageRejected(ValueError):
    """Uploaded bytes are not a usable PNG/JPEG vision image."""


@dataclass(frozen=True)
class ImageInfo:
    media_type: str
    width: int
    height: int


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Read width/height from a JPEG SOF marker without decoding pixels."""
    index = 2
    total = len(data)
    while index + 4 <= total:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker == 0x00:
            index += 2
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker in (0xD9, 0xDA):
            return None
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if length < 2:
            return None
        if marker in JPEG_SOF_MARKERS:
            if index + 9 > total:
                return None
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return (width, height)
        index += 2 + length
    return None


def sniff_image(data: bytes) -> ImageInfo | None:
    if data.startswith(PNG_MAGIC):
        if len(data) < 24 or data[12:16] != b"IHDR":
            return None
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return ImageInfo("image/png", width, height)
    if data.startswith(JPEG_MAGIC):
        size = _jpeg_size(data)
        if size is None:
            return None
        return ImageInfo("image/jpeg", *size)
    return None


def validate_image_bytes(
    data: bytes,
    *,
    max_kb: int | None = None,
    max_side: int | None = None,
    max_pixels: int | None = None,
) -> ImageInfo:
    limit_kb = settings.image_input_max_kb if max_kb is None else max_kb
    if len(data) > limit_kb * 1024:
        raise ImageRejected(f"图片超过上限（{limit_kb / 1024:.1f} MB）")
    info = sniff_image(data)
    if info is None:
        raise ImageRejected("仅支持 PNG/JPEG 图片，且文件头必须有效")
    side_limit = settings.image_input_max_side if max_side is None else max_side
    pixel_limit = settings.image_input_max_pixels if max_pixels is None else max_pixels
    if info.width <= 0 or info.height <= 0:
        raise ImageRejected("图片尺寸无效")
    if max(info.width, info.height) > side_limit:
        raise ImageRejected(f"图片单边不能超过 {side_limit} 像素")
    if info.width * info.height > pixel_limit:
        raise ImageRejected(
            f"图片总像素超过上限（{pixel_limit // 1_000_000} MP）"
        )
    return info


def data_url(media_type: str, data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def build_user_content(text: str, images: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    if text.strip():
        blocks.append({"type": "text", "text": text})
    for image in images:
        blocks.append({
            "type": "image_url",
            "image_url": {"url": data_url(image["mime"], image["data"])},
        })
    return blocks or [{"type": "text", "text": " "}]


def no_vision_content(text: str) -> str:
    return f"{text}\n\n{NO_VISION_NOTE}" if text.strip() else NO_VISION_NOTE


def strip_image_blocks(messages: list[dict]) -> list[dict]:
    """Return a copy with image blocks replaced by an explicit text note."""
    stripped: list[dict] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            stripped.append(message)
            continue
        blocks: list = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image_url":
                blocks.append({"type": "text", "text": STRIPPED_IMAGE_NOTE})
            else:
                blocks.append(block)
        stripped.append({**message, "content": blocks})
    return stripped


def is_vision_image(item: dict) -> bool:
    return str(item.get("mime") or "").lower() in VISION_MEDIA_TYPES


def total_image_bytes(attachments: list[dict]) -> int:
    return sum(
        int(item.get("size") or 0)
        for item in attachments
        if is_vision_image(item)
    )


async def load_vision_images(
    user_id: int, attachments: list[dict],
) -> tuple[list[dict], list[str]]:
    """Load and re-validate current-turn images. Failures skip the image only."""
    from app.core.storage.user_storage import get_file

    images: list[dict] = []
    warnings: list[str] = []
    for item in attachments:
        if not is_vision_image(item):
            continue
        file_id = str(item.get("id") or "")
        try:
            file = await get_file(file_id, user_id)
            if not file:
                raise FileNotFoundError("文件不存在")
            data = await asyncio.to_thread(Path(file["storage_path"]).read_bytes)
            info = validate_image_bytes(data)
        except Exception as exc:  # noqa: BLE001 — one broken image must not fail the turn
            warnings.append(f"{item.get('filename') or file_id}: {exc}")
            continue
        images.append({
            "id": file_id,
            "filename": item.get("filename") or file["filename"],
            "mime": info.media_type,
            "data": data,
        })
    return images, warnings


def is_image_rejection(exc: Exception) -> bool:
    """True only for a 4xx that names image/vision/media content."""
    status = getattr(exc, "status_code", None)
    if status is None:
        match = re.search(r"\b(400|415|422)\b", str(exc))
        status = int(match.group(1)) if match else None
    if status not in (400, 415, 422):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in IMAGE_ERROR_MARKERS)
