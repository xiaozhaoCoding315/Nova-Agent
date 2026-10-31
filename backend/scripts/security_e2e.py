"""Server-side security E2E (run inside the app container).

    docker exec -w /app nova-agent-app-1 python -m scripts.security_e2e

Covers: explicit and indirect secret reads in all permission modes, readonly
git diagnostics, and container cleanup on cancellation.  Requires Docker.
"""
import asyncio
import shutil
import subprocess
import uuid

from app.core.git_ops.service import init_repo
from app.core.indexing.pipeline import create_repo_row, delete_repo
from app.core.sandbox.runtime import execute as sandbox_execute
from app.core.sandbox.runtime import sandbox_status
from app.core.storage.user_storage import repo_container
from app.core.tools import ToolContext, get_registry
from app.db import query

SECRET = "SECRET_VALUE_9f3a"


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail[:300]}" if detail and not ok else ""))
        if not ok:
            self.failures.append(name)


def _output(result: dict) -> str:
    output = result.get("output") or {}
    return f"{output.get('stdout') or ''}\n{output.get('stderr') or ''}"


def _running_containers(label: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"label=nova.job_id={label}"],
        capture_output=True, text=True, timeout=15,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


async def main() -> int:
    report = Report()
    status = await sandbox_status()
    if not status.get("available"):
        print(f"[SKIP] sandbox unavailable: {status.get('reason')}")
        return 2

    rows = await query("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
    if not rows:
        print("[FAIL] no admin user found")
        return 1
    admin_id = int(rows[0][0])
    repo_id = str(uuid.uuid4())
    root = repo_container(admin_id, repo_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text(f"{SECRET}=1\n", encoding="utf-8")
    (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
    await init_repo(root)
    await create_repo_row(admin_id, "security-e2e", "zip:security-e2e", repo_id)

    registry = get_registry()
    user = {"id": admin_id, "role": "admin"}

    def ctx(mode: str) -> ToolContext:
        return ToolContext(user=user, repo_ids=[repo_id], permission_mode=mode)

    try:
        for mode in ("readonly", "ask", "auto"):
            result = await registry.execute(
                "run_command", {"command": "cat .env"}, ctx(mode)
            )
            report.check(
                f"{mode}: explicit .env read denied",
                not result["ok"] and "密钥" in str(result.get("error") or ""),
                str(result.get("error") or ""),
            )

        result = await registry.execute(
            "run_command", {"command": f"grep -r {SECRET} ."}, ctx("readonly")
        )
        report.check(
            "readonly: indirect grep does not see secrets",
            result["ok"] and SECRET not in _output(result),
            _output(result),
        )

        result = await registry.execute(
            "run_command",
            {"command": f"sh -c 'grep -r {SECRET} . || true'"},
            ctx("auto"),
        )
        report.check(
            "auto: masked workspace does not see secrets",
            result["ok"] and SECRET not in _output(result),
            _output(result),
        )

        result = await registry.execute(
            "run_command", {"command": "git status --short"}, ctx("readonly")
        )
        report.check(
            "readonly: git diagnostics still work",
            result["ok"] and (result.get("output") or {}).get("exit_code") == 0,
            _output(result),
        )

        label = f"e2e-cancel-{uuid.uuid4().hex[:8]}"
        task = asyncio.create_task(
            sandbox_execute(
                files={}, command="sleep 30", timeout=60,
                workspace_dir=str(root), job_id=label,
            )
        )
        await asyncio.sleep(3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(2)
        residue = _running_containers(label)
        report.check("cancel: no sandbox container residue", not residue, str(residue))
    finally:
        await delete_repo(repo_id, admin_id)
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{len(report.failures)} failure(s)")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
