"""fetch_url tool: fetch a public documentation URL and return Markdown.

SSRF guard: only http(s), host must resolve exclusively to public IPs,
redirects are re-validated hop by hop, response size and type are capped.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import html2text
import httpx

from app.config import settings
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

_ALLOWED_TYPES = {
    "text/html", "text/plain", "application/json",
    "text/markdown", "application/xml", "text/xml",
}
_MAX_HOPS = 4


def _resolves_to_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


async def fetch_url(args: dict, ctx: ToolContext) -> dict:
    url = (args.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ToolBusinessError("url 必须是 http/https 公网地址")

    max_bytes = settings.fetch_url_max_kb * 1024
    response = None
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        headers={"User-Agent": "NovaAgent/2.0 (docs fetch)"},
    ) as client:
        for _ in range(_MAX_HOPS):
            if not await asyncio.to_thread(_resolves_to_public, parsed.hostname):
                raise ToolBusinessError("拒绝访问：目标解析到内网/保留地址")
            response = await client.get(url)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise ToolBusinessError("重定向缺少 location")
                url = urljoin(url, location)
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise ToolBusinessError("重定向到非 http(s) 地址，已拒绝")
                continue
            break

    if response is None:
        raise ToolBusinessError("请求失败：重定向次数过多")

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        raise ToolBusinessError(f"不支持的内容类型：{content_type or 'unknown'}（仅允许文本类页面）")

    body = response.content[:max_bytes]
    text = body.decode(response.encoding or "utf-8", errors="replace")
    if "html" in content_type:
        converter = html2text.HTML2Text()
        converter.body_width = 0
        converter.ignore_images = True
        text = converter.handle(text)

    return {
        "url": url,
        "status": response.status_code,
        "content_type": content_type,
        "text": text[:30_000],
        "truncated": len(response.content) > max_bytes,
    }


TOOL = ToolDefinition(
    name="fetch_url",
    description=(
        "抓取公开文档链接（http/https 公网地址）并转为 Markdown 文本。"
        "适合让助手阅读 API 文档、报错页面、规范说明等在线资料。仅允许公网文本类内容，禁止内网地址。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的公开 URL"},
        },
        "required": ["url"],
    },
    func=fetch_url,
    category="network",
    timeout=25,
)