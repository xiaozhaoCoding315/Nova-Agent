"""Deterministic delivery report for one chat turn.

This is intentionally not LLM-generated: it reports what actually happened
(commands, exit codes, edits, citation checks, token usage) so the user can
reproduce the conclusion.
"""
from datetime import datetime, timezone


def _command_entries(tools: list[dict]) -> list[dict]:
    entries = []
    for tool in tools:
        command = tool.get("command")
        if not command:
            continue
        entries.append({
            "tool": tool.get("name") or "",
            "command": str(command)[:500],
            "exit_code": tool.get("exit_code"),
            "ok": bool(tool.get("ok")),
            "timed_out": bool(tool.get("timed_out")),
            "ms": int(tool.get("ms") or 0),
        })
    return entries


def _files_changed(edits: list[dict]) -> list[dict]:
    files: dict[str, str] = {}
    for edit in edits:
        status = edit.get("status") or ("pending" if edit.get("staged") else "applied")
        for path in edit.get("files") or []:
            files[str(path)] = str(status)
    return [{"path": path, "status": status} for path, status in sorted(files.items())]


def build_turn_report(
    *,
    user_message: str,
    repos: list[dict],
    permission_mode: str,
    tools: list[dict],
    edits: list[dict],
    evidence: dict,
    usage: dict,
    rounds: int,
    elapsed_ms: int,
    final_text: str,
    errors: list[str] | None = None,
) -> dict:
    commands = _command_entries(tools)
    tests = [c for c in commands if "pytest" in c["command"] or "unittest" in c["command"]]
    last_test = tests[-1] if tests else None
    changed = _files_changed(edits)
    pending = [f for f in changed if f["status"] == "pending"]
    failed_commands = [c for c in commands if not c["ok"]]
    citation_verified = int(evidence.get("verified") or 0)
    citation_missing = int(evidence.get("missing") or 0)
    citation_out_of_range = int(evidence.get("out_of_range") or 0)
    errors = errors or []

    unverified: list[str] = []
    if not commands:
        unverified.append("本轮没有在沙箱中执行命令")
    if last_test is None:
        unverified.append("没有运行测试")
    elif not last_test["ok"]:
        unverified.append(f"最后一次测试失败（exit {last_test['exit_code']}）")
    if citation_missing:
        unverified.append(f"{citation_missing} 处引用在仓库中未找到")
    if citation_out_of_range:
        unverified.append(f"{citation_out_of_range} 处引用行号越界")
    if pending:
        unverified.append(f"{len(pending)} 个文件修改尚未批准写入")
    if failed_commands:
        unverified.append(f"{len(failed_commands)} 条命令执行失败")

    if errors:
        status = "failed"
    elif pending:
        status = "partial"
    elif last_test is not None and last_test["ok"] and not citation_missing and not citation_out_of_range:
        status = "verified"
    elif commands or citation_verified:
        status = "partial"
    else:
        status = "unverified"

    checks = [
        {
            "name": "沙箱执行",
            "status": "passed" if commands and not failed_commands else "failed" if commands else "skipped",
            "detail": f"{len(commands)} 条命令，{len(failed_commands)} 条失败",
        },
        {
            "name": "测试",
            "status": "passed" if last_test and last_test["ok"] else "failed" if last_test else "skipped",
            "detail": (
                f"最后一次 exit {last_test['exit_code']}" if last_test else "未运行测试"
            ),
        },
        {
            "name": "引用核对",
            "status": "passed" if citation_verified and not citation_missing and not citation_out_of_range
            else "failed" if citation_missing or citation_out_of_range
            else "skipped",
            "detail": f"核对 {citation_verified} 处，异常 {citation_missing + citation_out_of_range} 处",
        },
    ]

    return {
        "status": status,
        "request": (user_message or "")[:1000],
        "repos": [{"id": str(r.get("id", "")), "name": r.get("name", "")} for r in repos],
        "permission_mode": permission_mode,
        "final_answer": (final_text or "")[:3000],
        "files_changed": changed,
        "commands": commands[:30],
        "checks": checks,
        "citations": {
            "verified": citation_verified,
            "missing": citation_missing,
            "out_of_range": citation_out_of_range,
            "skipped": int(evidence.get("skipped") or 0),
            "executed": bool(evidence.get("executed")),
        },
        "unverified": unverified,
        "errors": errors[:10],
        "stats": {
            "rounds": rounds,
            "tools": [t.get("name", "") for t in tools][:30],
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "elapsed_ms": elapsed_ms,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
