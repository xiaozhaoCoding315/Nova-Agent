"""local_run_command tool: 让 Agent 把命令派发到用户本机执行。

架构：对话在服务器上跑，客户端只是界面——所以工具默认碰不到用户电脑。
本工具与 `nova.py agent`（本地常驻执行器）配合：工具把命令写进派发表，
本地执行器长轮询领取、在本机执行、回传输出。用户本机的确认（或 --yes）
是最后一道闸门；readonly 权限模式由能力引擎统一拦截（proc.exec）。
"""
import asyncio
import time
import uuid

from app.config import settings
from app.core.security.audit import log_audit
from app.core.tools.base import ToolBusinessError, ToolContext, ToolDefinition
from app.db import execute, query

_POLL_INTERVAL_S = 1.5
_MAX_OUTPUT_CHARS = 8000


async def _dispatch(ctx: ToolContext, *, kind: str, command: str, cwd: str,
                    file_path: str | None = None, content: str | None = None) -> str:
    request_id = str(uuid.uuid4())
    await execute(
        "INSERT INTO local_exec_requests (id, user_id, cwd, command, kind, file_path, content) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (request_id, ctx.user["id"], cwd[:300], command[:4000],
         kind, (file_path or "")[:500] or None, content),
    )
    await log_audit(
        "local_exec_dispatch",
        user_id=str(ctx.user.get("id", "")),
        details={"request_id": request_id, "kind": kind, "cwd": cwd, "command": command[:300]},
    )
    return request_id


async def _await_result(request_id: str, command: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = await query(
            "SELECT status, output, exit_code FROM local_exec_requests WHERE id = %s",
            (request_id,),
        )
        if rows:
            status, output, exit_code = rows[0][0], rows[0][1], rows[0][2]
            if status in ("done", "error"):
                output = (output or "").strip()
            if status == "done":
                return {
                    "exit_code": exit_code,
                    "stdout": output[:_MAX_OUTPUT_CHARS],
                    "command": command,
                    "executed_on": "user-local-machine",
                    "hint": (
                        "已在用户本机完成。输出即真实结果；如需继续操作本机，可继续派发。"
                        if exit_code == 0 else
                        "在用户本机执行失败：请阅读输出，修正后重试。"
                    ),
                }
            if status == "error":
                return {
                    "exit_code": exit_code,
                    "stderr": output[:_MAX_OUTPUT_CHARS],
                    "command": command,
                    "executed_on": "user-local-machine",
                    "hint": "本机执行器返回错误（可能是命令不存在、路径越界或被用户拒绝），请调整后重试或询问用户。",
                }
        await asyncio.sleep(_POLL_INTERVAL_S)

    await execute(
        "UPDATE local_exec_requests SET status = 'timeout', updated_at = now() WHERE id = %s AND status IN ('pending','claimed')",
        (request_id,),
    )
    raise ToolBusinessError(
        "本地执行器未在限时内响应：请让用户在本机运行 `python nova.py agent` 启动本地执行器后重试，"
        "或改用 run_command 在服务器沙箱中完成。"
    )


async def local_run_command(args: dict, ctx: ToolContext) -> dict:
    command = str(args.get("command") or "").strip()
    if not command:
        raise ToolBusinessError("command 不能为空")
    cwd = str(args.get("cwd") or ".").strip() or "."

    request_id = await _dispatch(ctx, kind="shell", command=command, cwd=cwd)
    await log_audit(
        "local_exec_dispatch",
        user_id=str(ctx.user.get("id", "")),
        details={"request_id": request_id, "cwd": cwd, "command": command[:300]},
    )

    timeout = min(int(args.get("timeout") or settings.local_exec_timeout), 300)
    return await _await_result(request_id, command, timeout)


TOOL = ToolDefinition(
    name="local_run_command",
    description=(
        "把 shell 命令派发到用户本机执行（需要用户已在本地运行 nova.py agent 执行器并授权）。"
        "适合：在用户的真实项目目录里跑构建/测试、查系统环境、安装依赖、git 操作等"
        "只能在用户电脑上完成的事。命令会先经用户本机确认；只读模式不可用。"
        "与 run_command 的区别：run_command 在服务器沙箱里执行，本工具作用于用户的真实电脑。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要在用户本机执行的命令，如 'npm run build'"},
            "cwd": {"type": "string", "description": "相对执行器根目录的路径（默认 '.' 即根目录）"},
            "timeout": {"type": "integer", "description": "等待本机执行的超时秒数（默认 60，最大 300）"},
        },
        "required": ["command"],
    },
    func=local_run_command,
    category="execute",
    capabilities=["proc.exec"],
    timeout=310,
)


async def local_write_file(args: dict, ctx: ToolContext) -> dict:
    """把生成的文件写到用户本机（默认进入执行器根目录下的 output/ 文件夹）。"""
    path = str(args.get("path") or "").strip().replace("\\", "/")
    content = args.get("content")
    if not path:
        raise ToolBusinessError("path 不能为空")
    if content is None or not isinstance(content, str):
        raise ToolBusinessError("content 必须是完整的文件文本内容")
    if len(content) > 2_000_000:
        raise ToolBusinessError("文件内容过大（>2MB），请拆分文件")
    # 引导模型把产出集中到 output/；也允许用户明确指定的其他相对路径
    if path.startswith("/") or ".." in path.split("/") or ":" in path.split("/")[0]:
        raise ToolBusinessError("path 必须是执行器根目录下的相对路径（不要以 / 开头，不要包含 ..）")

    request_id = await _dispatch(
        ctx, kind="write", command=f"[write file] {path}", cwd=".",
        file_path=path, content=content,
    )
    timeout = min(int(args.get("timeout") or settings.local_exec_timeout), 300)
    result = await _await_result(request_id, f"write {path}", timeout)
    return {
        **result,
        "path": path,
        "bytes_written": len(content.encode("utf-8")),
        "hint": (
            f"文件已写入用户本机（{path}）。若用户上传过工作区，也可以把生成结果"
            "写入其工作区目录，或用 run_command 在服务器沙箱中操作仓库副本。"
            if result.get("exit_code") == 0 else
            "写入失败：请检查路径是否合法（相对路径、不含 ..），或询问用户执行器状态。"
        ),
    }


LOCAL_WRITE_TOOL = ToolDefinition(
    name="local_write_file",
    description=(
        "把一份完整的文件内容写到用户本机磁盘（需要用户已运行 nova.py agent 并授权）。"
        "适合：为用户生成代码文件、脚本、配置、文档，直接落到他的电脑上。"
        "path 用执行器根目录下的相对路径，生成物建议放在 output/ 目录下（如 output/main.py）；"
        "会覆盖同名文件，写入前经用户本机确认（--yes 除外）。只读模式不可用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对执行器根目录的路径，如 output/main.py"},
            "content": {"type": "string", "description": "完整的文件文本内容（不是 diff）"},
            "timeout": {"type": "integer", "description": "等待本机写入确认的超时秒数（默认 60）"},
        },
        "required": ["path", "content"],
    },
    func=local_write_file,
    category="write",
    capabilities=["fs.write", "proc.exec"],
    timeout=310,
)
