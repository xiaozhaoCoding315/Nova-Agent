"""Minimal MCP stdio client.

Windows SelectorEventLoop cannot create asyncio subprocesses, so the client
uses Popen plus a reader thread and hands responses back to the event loop.
Only newline-delimited JSON-RPC 2.0 is supported.
"""
import asyncio
import json
import os
import re
import subprocess
import threading

import structlog

from app.core.security.redaction import redact_text

logger = structlog.get_logger()


class MCPError(RuntimeError):
    pass


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


class MCPClient:
    def __init__(self, command: str, args: list[str], timeout: int = 30):
        self.command = command
        self.args = args
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._write_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stderr: threading.Thread | None = None
        self._closed = False

    def _argv(self) -> list[str]:
        cmd = [self.command, *self.args]
        if os.name == "nt" and self.command.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/c", *cmd]
        return cmd

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout and self._loop
        for line in self.proc.stdout:
            if self._closed:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("mcp_bad_json", line=line[:300])
                continue
            if isinstance(message, dict) and "id" in message:
                self._loop.call_soon_threadsafe(
                    self._resolve, message.get("id"), message
                )

    def _stderr_loop(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            logger.info("mcp_server_stderr", line=redact_text(line.strip())[:500])

    def _resolve(self, request_id, message: dict) -> None:
        future = self._pending.pop(request_id, None)
        if future and not future.done():
            future.set_result(message)

    async def start(self) -> dict:
        self._loop = asyncio.get_running_loop()
        try:
            self.proc = subprocess.Popen(
                self._argv(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=None,
            )
        except FileNotFoundError as exc:
            raise MCPError(f"MCP 命令不存在：{self.command}") from exc
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._stderr = threading.Thread(target=self._stderr_loop, daemon=True)
        self._reader.start()
        self._stderr.start()
        result = await self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nova-agent", "version": "2.0.0"},
        }, timeout=15)
        await self.notify("notifications/initialized", {})
        return result

    def _write(self, payload: dict) -> None:
        if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
            raise MCPError("MCP 进程已退出")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._write_lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    async def notify(self, method: str, params: dict | None = None) -> None:
        await asyncio.to_thread(
            self._write, {"jsonrpc": "2.0", "method": method, "params": params or {}}
        )

    async def request(self, method: str, params: dict | None = None, timeout: int | None = None) -> dict:
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future = self._loop.create_future() if self._loop else asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await asyncio.to_thread(
                self._write,
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
            )
            message = await asyncio.wait_for(future, timeout=timeout or self.timeout)
        except asyncio.TimeoutError as exc:
            raise MCPError(f"MCP 请求超时：{method}") from exc
        finally:
            self._pending.pop(request_id, None)
        if "error" in message:
            error = message["error"]
            raise MCPError(str(error.get("message") or error))
        return message.get("result") or {}

    async def list_tools(self) -> list[dict]:
        result = await self.request("tools/list", {}, timeout=self.timeout)
        tools = result.get("tools") if isinstance(result, dict) else None
        return [tool for tool in tools or [] if isinstance(tool, dict)]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        result = await self.request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=self.timeout
        )
        content = result.get("content") if isinstance(result, dict) else []
        texts = [
            str(item.get("text") or "")
            for item in content or []
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return {
            "content": content or [],
            "text": "\n".join(texts).strip(),
            "is_error": bool(result.get("isError")) if isinstance(result, dict) else False,
        }

    def close(self) -> None:
        self._closed = True
        for future in list(self._pending.values()):
            if future.done():
                continue
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(
                    self._set_exception, future, MCPError("MCP 进程已关闭")
                )
        self._pending.clear()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    @staticmethod
    def _set_exception(future: asyncio.Future, exc: Exception) -> None:
        if not future.done():
            future.set_exception(exc)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)
