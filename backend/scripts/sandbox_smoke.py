"""Container smoke test for the sandbox images.

    docker exec -w /app nova-agent-app-1 python -m scripts.sandbox_smoke
"""
import asyncio

from app.core.sandbox.runtime import execute, sandbox_status


async def _run(command: str, *, files: dict | None = None) -> dict:
    return await execute(files=files or {}, command=command, timeout=60)


async def main() -> int:
    status = await sandbox_status()
    if not status.get("available"):
        print(f"[SKIP] sandbox unavailable: {status.get('reason')}")
        return 2

    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f" — {detail[:300]}" if detail and not ok else ""))
        if not ok:
            failures += 1

    result = await _run("git --version")
    check("git is installed", result["exit_code"] == 0, result["stderr"])

    result = await _run("id -u")
    check("runs as non-root", result["stdout"].strip() != "0", result["stdout"])

    result = await _run("touch /root-probe")
    check("root filesystem is read-only", result["exit_code"] != 0, result["stderr"])

    result = await _run(
        "python -c \"import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)\""
    )
    check("network is disabled", result["exit_code"] != 0, result["stdout"])

    result = await _run(
        "python -c \"print('hello')\"", files={"main.py": "print('x')"}
    )
    check("python executes user files", result["exit_code"] == 0
          and "hello" in result["stdout"], result["stderr"])

    print(f"\n{failures} failure(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
