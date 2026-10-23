"""Run the golden repository verification cases.

Requires the configured PostgreSQL/Qdrant (Qdrant is not used for these
checks), Docker, and the nova-builder / nova-node images.
"""
import asyncio
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"

CASES = [
    ("python-api", "passed"),
    ("node-app", "passed"),
    ("fullstack-contract", "passed"),
]


async def _cleanup(repo_id: str) -> None:
    from app.db import execute

    await execute("DELETE FROM repos WHERE id = %s", (repo_id,))
    subprocess.run(
        ["docker", "volume", "rm", f"nova-node-deps-{repo_id}"],
        capture_output=True,
        timeout=30,
    )


async def main() -> int:
    from app.core.sandbox.runtime import sandbox_status
    from app.core.verify.service import run_verification
    from app.db import execute, query

    status = await sandbox_status()
    if not status.get("available") or not status.get("node_available"):
        print("sandbox images missing:", status)
        return 1

    rows = await query("SELECT id, username, role FROM users ORDER BY id LIMIT 1")
    if not rows:
        print("no users found; run init_db first")
        return 1
    user = {"id": rows[0][0], "username": rows[0][1], "role": rows[0][2]}
    failures = 0

    for name, expected in CASES:
        root = SAMPLES / name
        if not root.is_dir():
            print(f"[{name}] missing sample directory: {root}")
            failures += 1
            continue
        repo_id = str(uuid.uuid4())
        await execute(
            "INSERT INTO repos (id, user_id, name, source, root_path, status, kind) "
            "VALUES (%s, %s, %s, %s, %s, 'ready', 'import')",
            (repo_id, user["id"], name, f"local:{name}", str(root)),
        )
        try:
            result = await run_verification(
                {"id": repo_id, "name": name, "root_path": str(root)}, user
            )
            steps = [(step["name"], step["status"]) for step in result.get("steps", [])]
            ok = result.get("status") == expected
            print(f"[{name}] {result.get('status')} stack={result.get('stack')} steps={steps}")
            if not ok:
                failures += 1
                print(f"  expected {expected}")
        finally:
            await _cleanup(repo_id)

    if failures:
        print(f"golden failures: {failures}")
        return 1
    print("all golden cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
