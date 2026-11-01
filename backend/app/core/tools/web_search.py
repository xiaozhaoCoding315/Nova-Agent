"""web_search tool: search the public web without a browser.

Default ``WEB_SEARCH_PROVIDER=auto`` tries Bing's HTML endpoint first (works
from mainland China) and falls back to DuckDuckGo.  Brave Search is available
for deployments that want a stable API: set ``WEB_SEARCH_PROVIDER=brave`` and
``WEB_SEARCH_API_KEY``.  Like ``fetch_url``, this tool leaves the machine, so
the policy engine only exposes it in auto/full permission modes.
"""
import html
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import settings
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition

_DDG_URL = "https://html.duckduckgo.com/html/"
_BING_URL = "https://cn.bing.com/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_MAX_QUERY_CHARS = 400
_MAX_RESULTS = 10
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class _DDGParser(HTMLParser):
    """Extract ``result__a`` titles/links and ``result__snippet`` summaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._current: dict | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if "result__a" in classes:
            self._current = {
                "title": "",
                "url": _clean_ddg_url(values.get("href") or ""),
                "snippet": "",
            }
            self._capture = "title"
        elif "result__snippet" in classes and self._current is not None:
            self._capture = "snippet"

    def handle_data(self, data: str) -> None:
        if self._current is None or self._capture is None:
            return
        self._current[self._capture] += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._capture is None or self._current is None:
            return
        if self._capture == "title":
            title = " ".join(self._current["title"].split())
            if title and self._current["url"]:
                self._current["title"] = title
                self.results.append(self._current)
            self._capture = None
        else:
            self._current["snippet"] = " ".join(self._current["snippet"].split())
            self._capture = None


def _clean_ddg_url(href: str) -> str:
    """Unwrap DuckDuckGo's ``/l/?uddg=...`` redirector into the target URL."""
    value = html.unescape(href or "").strip()
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        value = unquote(target)
    if value.startswith("//"):
        value = f"https:{value}"
    return value


def _public_result(result: dict) -> bool:
    parsed = urlparse(str(result.get("url") or ""))
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


async def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=settings.web_search_timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NovaAgent/2.0)"},
        ) as client:
            response = await client.post(_DDG_URL, data={"q": query})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolBusinessError(
            f"搜索请求失败：{type(exc).__name__}。可稍后重试，或改用 Brave（WEB_SEARCH_PROVIDER=brave）"
        ) from exc

    parser = _DDGParser()
    try:
        parser.feed(response.text)
    except Exception as exc:  # noqa: BLE001 - malformed third-party HTML
        raise ToolBusinessError(f"无法解析搜索结果：{type(exc).__name__}") from exc

    results = [item for item in parser.results if _public_result(item)]
    if not results:
        raise ToolBusinessError(
            "搜索没有返回结果。DuckDuckGo 可能要求人机验证；"
            "可稍后重试，或配置 WEB_SEARCH_PROVIDER=brave 与 WEB_SEARCH_API_KEY"
        )
    return results[:limit]


class _BingParser(HTMLParser):
    """Extract ``li.b_algo`` result blocks (h2 link + first paragraph)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._current: dict | None = None
        self._depth = 0
        self._in_h2 = False
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "li" and "b_algo" in classes and self._current is None:
            self._current = {"title": "", "url": values.get("href") or "", "snippet": ""}
            self._depth = 1
            return
        if self._current is None:
            return
        if tag == "li":
            self._depth += 1
        elif tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2:
            if not self._current["url"]:
                self._current["url"] = values.get("href") or ""
            self._capture = "title"
        elif tag == "p" and not self._current["snippet"]:
            self._capture = "snippet"

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._capture:
            self._current[self._capture] += data

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "a" and self._capture == "title":
            self._capture = None
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p" and self._capture == "snippet":
            self._capture = None
        elif tag == "li":
            self._depth -= 1
            if self._depth <= 0:
                current = self._current
                current["title"] = " ".join(current["title"].split())
                current["snippet"] = " ".join(current["snippet"].split())
                current["url"] = html.unescape(current["url"]).strip()
                if current["title"] and _public_result(current):
                    self.results.append(current)
                self._current = None
                self._capture = None
                self._in_h2 = False


async def _search_bing(query: str, limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=settings.web_search_timeout,
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
        ) as client:
            response = await client.get(_BING_URL, params={"q": query})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolBusinessError(f"Bing 搜索请求失败：{type(exc).__name__}") from exc

    parser = _BingParser()
    try:
        parser.feed(response.text)
    except Exception as exc:  # noqa: BLE001 - malformed third-party HTML
        raise ToolBusinessError(f"无法解析 Bing 搜索结果：{type(exc).__name__}") from exc

    results = parser.results[:limit]
    if not results:
        raise ToolBusinessError("Bing 搜索没有返回结果（可能触发了人机验证）")
    return results


async def _search_brave(query: str, limit: int) -> list[dict]:
    key = settings.web_search_api_key.strip()
    if not key:
        raise ToolBusinessError("Brave 搜索需要配置 WEB_SEARCH_API_KEY")
    try:
        async with httpx.AsyncClient(timeout=settings.web_search_timeout) as client:
            response = await client.get(
                _BRAVE_URL,
                params={"q": query, "count": limit},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": key,
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise ToolBusinessError("Brave 搜索 Key 无效或额度不足") from exc
        if exc.response.status_code == 429:
            raise ToolBusinessError("Brave 搜索请求过于频繁，请稍后重试") from exc
        raise ToolBusinessError(f"搜索请求失败：HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ToolBusinessError(f"搜索请求失败：{type(exc).__name__}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolBusinessError("搜索服务返回了非 JSON 响应") from exc
    items = ((payload.get("web") or {}).get("results") or [])[:limit]
    results = []
    for item in items:
        result = {
            "title": html.unescape(str(item.get("title") or "")).strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": html.unescape(str(item.get("description") or "")).strip(),
        }
        if _public_result(result):
            results.append(result)
    if not results:
        raise ToolBusinessError("搜索没有返回结果")
    return results


async def web_search(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolBusinessError("query 不能为空")
    if len(query) > _MAX_QUERY_CHARS:
        raise ToolBusinessError(f"query 过长（最多 {_MAX_QUERY_CHARS} 字符）")

    raw_limit = args.get("max_results") or settings.web_search_max_results
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ToolBusinessError("max_results 必须是整数") from exc
    limit = max(1, min(limit, _MAX_RESULTS))

    provider = settings.web_search_provider.strip().lower() or "auto"
    if provider == "auto":
        # Bing first: reachable from mainland China; DuckDuckGo is the backup.
        attempts: list[tuple[str, Callable[[str, int], Awaitable[list[dict]]]]] = []
        if settings.web_search_api_key.strip():
            attempts.append(("brave", _search_brave))
        attempts.extend([("bing", _search_bing), ("duckduckgo", _search_duckduckgo)])
        errors: list[str] = []
        results: list[dict] = []
        for name, search in attempts:
            try:
                results = await search(query, limit)
                provider = name
                break
            except ToolBusinessError as exc:
                errors.append(f"{name}: {exc}")
        if not results:
            raise ToolBusinessError("搜索不可用。" + "；".join(errors[-2:]))
    elif provider == "duckduckgo":
        results = await _search_duckduckgo(query, limit)
    elif provider == "bing":
        results = await _search_bing(query, limit)
    elif provider == "brave":
        results = await _search_brave(query, limit)
    else:
        raise ToolBusinessError(
            f"未知的搜索提供方：{provider}（可选 auto / bing / duckduckgo / brave）"
        )

    seen: set[str] = set()
    unique = []
    for item in results:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
        if len(unique) >= limit:
            break
    return {
        "query": query,
        "provider": provider,
        "count": len(unique),
        "results": unique,
    }


TOOL = ToolDefinition(
    name="web_search",
    description=(
        "搜索公开网络，返回标题、URL 与摘要。适合查找最新文档、报错讨论、"
        "库版本说明和外部资料；需要网页全文时再对结果 URL 调用 fetch_url。"
        "仅在自主/完全访问模式可用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，尽量具体"},
            "max_results": {
                "type": "integer",
                "description": "返回条数，1-10，默认 6",
            },
        },
        "required": ["query"],
    },
    func=web_search,
    category="network",
    timeout=30,
    parallel_safe=True,
)
