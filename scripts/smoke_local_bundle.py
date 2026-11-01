#!/usr/bin/env python
"""Smoke-test the packaged local backend.

Starts ``backend/dist/nova-backend/nova-backend`` with a throwaway config,
waits for its JSON ``listening`` line, checks ``/api/v1/status/health``,
then closes stdin (the same signal the desktop shell sends on quit) and
verifies a clean exit.

Run after ``python scripts/build_desktop.py --skip-frontend --skip-installer``:

  python scripts/smoke_local_bundle.py
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "backend" / "dist" / "nova-backend"
BINARY = BUNDLE / ("nova-backend.exe" if os.name == "nt" else "nova-backend")


def _reader(stream, sink: "queue.Queue[str]") -> None:
    try:
        for line in stream:
            sink.put(line.rstrip("\r\n"))
    finally:
        sink.put("")


def _tail(lines: list[str], limit: int = 25) -> str:
    return "\n".join(lines[-limit:])


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the packaged local backend")
    parser.add_argument("--timeout", type=int, default=240, help="seconds to wait for listening")
    args = parser.parse_args()

    if not BINARY.is_file():
        print(f"missing bundle: {BINARY}", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="nova-smoke-"))
    env = {
        **os.environ,
        "NOVA_CONFIG_PATH": str(tmp / "nova-config.json"),
        "NOVA_PARENT_WATCH": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    print(f"bundle: {BINARY}")
    print(f"config: {env['NOVA_CONFIG_PATH']}")

    proc = subprocess.Popen(
        [str(BINARY), "local", "--port", "0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    stdout, stderr, stdin = proc.stdout, proc.stderr, proc.stdin
    if stdout is None or stderr is None or stdin is None:
        proc.kill()
        print("FAIL: child pipes were not created", file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    out: "queue.Queue[str]" = queue.Queue()
    err: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=_reader, args=(stdout, out), daemon=True).start()
    threading.Thread(target=_reader, args=(stderr, err), daemon=True).start()

    lines: list[str] = []
    url = None
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            line = out.get(timeout=1)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        if line == "":
            break
        lines.append(line)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "listening":
            url = str(event.get("url") or "")
            break

    if not url:
        proc.kill()
        drained = []
        while not err.empty():
            drained.append(err.get())
        print(f"FAIL: no listening line\nstdout:\n{_tail(lines)}\nstderr:\n{_tail(drained)}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    health = None
    for _ in range(20):
        try:
            with urllib.request.urlopen(f"{url}/api/v1/status/health", timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)

    if not health or not health.get("status"):
        proc.kill()
        print(f"FAIL: health check did not answer at {url}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    print(f"listening: {url}")
    print(f"health: {json.dumps(health, ensure_ascii=False)}")

    stdin.close()
    try:
        code = proc.wait(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("FAIL: backend did not exit after stdin closed")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    stderr_lines = []
    while not err.empty():
        stderr_lines.append(err.get())
    if code != 0:
        print(f"FAIL: exit code {code}\nstderr:\n{_tail(stderr_lines)}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: packaged local backend starts, serves health, and exits cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
