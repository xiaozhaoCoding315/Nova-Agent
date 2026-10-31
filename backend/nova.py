#!/usr/bin/env python
"""Nova Agent headless CLI (CI-friendly).

Usage:
  python nova.py repos
  python nova.py run "这个仓库有哪些接口？" --repo todo-api --permission readonly --json
  python nova.py verify --repo todo-api --json
  python nova.py trajectory --session <uuid> --json
  python nova.py export --repo todo-api --out build.zip

Env:
  NOVA_URL       default http://localhost:8000
  NOVA_USERNAME  default admin
  NOVA_PASSWORD  default admin123
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx


def client() -> httpx.Client:
    base = os.getenv("NOVA_URL", "http://localhost:8000").rstrip("/")
    c = httpx.Client(base_url=base, timeout=httpx.Timeout(300.0, connect=10.0))
    username = os.getenv("NOVA_USERNAME", "admin")
    password = os.getenv("NOVA_PASSWORD", "admin123")
    try:
        r = c.post("/api/v1/auth/login", json={"username": username, "password": password})
    except httpx.HTTPError as exc:
        print(f"连接失败：{exc}", file=sys.stderr)
        sys.exit(2)
    if r.status_code != 200:
        print(f"登录失败（{r.status_code}）：{r.text[:200]}", file=sys.stderr)
        sys.exit(2)
    return c


def resolve_repo(c: httpx.Client, ref: str) -> dict:
    try:
        repos = c.get("/api/v1/repos").json()
    except httpx.HTTPError as exc:
        print(f"获取仓库失败：{exc}", file=sys.stderr)
        sys.exit(2)
    for repo in repos:
        if repo["id"] == ref or repo["name"] == ref:
            return repo
    print(f"仓库不存在：{ref}", file=sys.stderr)
    sys.exit(2)


def cmd_repos(args) -> int:
    c = client()
    repos = c.get("/api/v1/repos").json()
    if args.json:
        print(json.dumps(repos, ensure_ascii=False, indent=2))
    else:
        for repo in repos:
            print(f"{repo['id']}  {repo['name']:<24} {repo['status']:<10} {repo.get('kind', 'import')}")
    return 0


def cmd_run(args) -> int:
    c = client()
    repo_ids = [resolve_repo(c, args.repo)["id"]] if args.repo else []
    body = {
        "content": args.prompt,
        "repo_ids": repo_ids,
        "permission_mode": args.permission,
    }
    if args.session:
        body["session_id"] = args.session

    answer = []
    event = "message"
    failed = False
    session_id = None
    with c.stream("POST", "/api/v1/chat/message", json=body) as response:
        if response.status_code != 200:
            print(f"请求失败（{response.status_code}）：{response.text[:300]}", file=sys.stderr)
            return 2
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
                continue
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if args.json:
                print(json.dumps({"event": event, "data": payload}, ensure_ascii=False))
            if event == "meta":
                session_id = payload.get("session_id")
            elif event == "token":
                answer.append(payload.get("text", ""))
            elif event == "error":
                failed = True
                if not args.json:
                    print(f"[error] {payload.get('message')}", file=sys.stderr)

    if not args.json:
        print("".join(answer))
        if session_id:
            print(f"\n[session {session_id}]", file=sys.stderr)
    return 1 if failed else 0


def cmd_verify(args) -> int:
    c = client()
    repo = resolve_repo(c, args.repo)
    r = c.post(f"/api/v1/repos/{repo['id']}/verify")
    if r.status_code != 200:
        print(f"验证请求失败（{r.status_code}）：{r.text[:300]}", file=sys.stderr)
        return 2
    result = r.json()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"验证{result.get('status')} · exit {result.get('exit_code')} · {result.get('image')}")
        print((result.get("stdout") or "")[-2000:])
    return 0 if result.get("status") == "passed" else 1


def cmd_trajectory(args) -> int:
    c = client()
    r = c.get(f"/api/v1/chat/sessions/{args.session}/trajectory")
    if r.status_code != 200:
        print(f"获取轨迹失败（{r.status_code}）：{r.text[:300]}", file=sys.stderr)
        return 2
    events = r.json()
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        for e in events:
            print(f"{e['id']:<6} {e['kind']:<16} {json.dumps(e['payload'], ensure_ascii=False)[:160]}")
    return 0


def cmd_export(args) -> int:
    c = client()
    repo = resolve_repo(c, args.repo)
    r = c.get(f"/api/v1/repos/{repo['id']}/export")
    if r.status_code != 200:
        print(f"导出失败（{r.status_code}）：{r.text[:300]}", file=sys.stderr)
        return 2
    out = args.out or f"{repo['name']}.zip"
    with open(out, "wb") as fh:
        fh.write(r.content)
    print(out)
    return 0


def cmd_agent(args) -> int:
    """本地执行器：长轮询领取服务器派发的命令，在本机执行并回传。

    这是 Agent「够到用户电脑」的通道：用户运行 nova.py agent 后，
    对话里的 local_run_command 工具就能在本机真实执行命令。
    """
    import subprocess

    root = Path(args.dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    poll = max(float(args.interval or 3), 1.5)
    timeout = max(int(args.timeout or 120), 5)
    confirm = not args.yes

    print(f"Nova 本地执行器已启动")
    print(f"  根目录：{root}")
    print(f"  服务器：{os.getenv('NOVA_URL', 'http://localhost:8000')}")
    print(f"  执行前确认：{'开启（每条命令需在终端按 y 确认，--yes 可跳过）' if confirm else '关闭（--yes，命令将直接执行）'}")
    print("  Ctrl+C 停止")
    c = client()
    while True:
        try:
            r = c.get("/api/v1/local/exec/pending", timeout=35)
            if r.status_code != 200:
                time.sleep(poll)
                continue
            pending = r.json()
            for item in pending:
                kind = item.get("kind", "shell")
                if kind == "write":
                    rel = (item.get("file_path") or "").strip()
                    content = item.get("content") or ""
                    target = (root / rel).resolve()
                    if not rel or (target != root and root not in target.parents):
                        _post_result(c, item["id"], ok=False, exit_code=-1,
                                     output=f"路径越界：{rel} 不在根目录内")
                        continue
                    stamp = time.strftime('%H:%M:%S')
                    print(f"\n[{stamp}] 收到文件写入请求:")
                    print(f"  目标：{target}（{len(content.encode('utf-8'))} 字节）")
                    if confirm:
                        answer = input("  允许写入本机文件？[y/N] ").strip().lower()
                        if answer != "y":
                            _post_result(c, item["id"], ok=False, exit_code=-1, output="用户拒绝了本次文件写入")
                            print("  已拒绝")
                            continue
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content, encoding="utf-8")
                        _post_result(c, item["id"], ok=True, exit_code=0,
                                     output=f"written {len(content.encode('utf-8'))} bytes -> {target}")
                        print("  写入完成")
                    except Exception as exc:  # noqa: BLE001
                        _post_result(c, item["id"], ok=False, exit_code=-1, output=f"写入失败：{exc}")
                    continue

                command, cwd = item["command"], item.get("cwd", ".")
                workdir = (root / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd)
                inside = workdir == root or root in workdir.parents
                if not inside:
                    _post_result(c, item["id"], ok=False, exit_code=-1, output=f"目录越界：{workdir} 不在根目录内")
                    continue
                stamp = time.strftime('%H:%M:%S')
                print(f"\n[{stamp}] 收到命令（{workdir}）:")
                print(f"  $ {command}")
                if confirm:
                    answer = input("  允许在本机执行？[y/N] ").strip().lower()
                    if answer != "y":
                        _post_result(c, item["id"], ok=False, exit_code=-1, output="用户拒绝了本次命令执行")
                        print("  已拒绝")
                        continue
                try:
                    proc = subprocess.run(
                        command, shell=True, cwd=str(workdir),
                        capture_output=True, text=True, timeout=timeout,
                    )
                    stderr_part = ("\n[stderr]\n" + proc.stderr) if proc.stderr else ""
                    output = ((proc.stdout or "") + stderr_part).strip()
                    _post_result(c, item["id"], ok=proc.returncode == 0, exit_code=proc.returncode, output=output)
                    print(f"  完成，exit {proc.returncode}")
                except subprocess.TimeoutExpired:
                    _post_result(c, item["id"], ok=False, exit_code=-1, output=f"命令超时（>{timeout}s）")
                    print("  超时")
                except Exception as exc:  # noqa: BLE001
                    _post_result(c, item["id"], ok=False, exit_code=-1, output=f"执行器错误：{exc}")
        except KeyboardInterrupt:
            print("\n已停止")
            return 0
        except httpx.HTTPError:
            time.sleep(poll)
        time.sleep(poll)


def cmd_local(args) -> int:
    from app.local.config import load_or_create
    from app.local.launcher import run

    config = load_or_create(args.config)
    if args.pg_backend:
        config["pgBackend"] = args.pg_backend
    try:
        return run(config, host=args.host, port=args.port)
    except (RuntimeError, ValueError) as exc:
        print(f"本地启动失败：{exc}", file=sys.stderr)
        return 1


def _post_result(c: httpx.Client, request_id: str, *, ok: bool, exit_code: int, output: str) -> None:
    try:
        c.post(f"/api/v1/local/exec/{request_id}/result",
               json={"ok": ok, "output": output[:100000], "exit_code": exit_code}, timeout=30)
    except httpx.HTTPError as exc:
        print(f"  回传结果失败：{exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(prog="nova", description="Nova Agent headless CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_repos = sub.add_parser("repos", help="列出仓库")
    p_repos.add_argument("--json", action="store_true")
    p_repos.set_defaults(func=cmd_repos)

    p_run = sub.add_parser("run", help="非交互式对话")
    p_run.add_argument("prompt")
    p_run.add_argument("--repo", help="仓库名称或 ID")
    p_run.add_argument("--session", help="继续指定会话")
    p_run.add_argument("--permission", choices=["readonly", "ask", "auto"], default="readonly")
    p_run.add_argument("--json", action="store_true", help="输出 JSONL 事件流")
    p_run.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify", help="在沙箱中运行仓库测试")
    p_verify.add_argument("--repo", required=True)
    p_verify.add_argument("--json", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    p_trace = sub.add_parser("trajectory", help="查看会话轨迹")
    p_trace.add_argument("--session", required=True)
    p_trace.add_argument("--json", action="store_true")
    p_trace.set_defaults(func=cmd_trajectory)

    p_export = sub.add_parser("export", help="导出仓库 zip")
    p_export.add_argument("--repo", required=True)
    p_export.add_argument("--out")
    p_export.set_defaults(func=cmd_export)

    p_agent = sub.add_parser("agent", help="本地执行器：让对话里的 Agent 能在你本机执行命令")
    p_agent.add_argument("--dir", default=".", help="执行器根目录（Agent 的命令只能在此目录及子目录内运行）")
    p_agent.add_argument("--yes", action="store_true", help="跳过逐条确认（信任对话派发的命令）")
    p_agent.add_argument("--interval", type=float, default=3.0, help="轮询间隔秒数（默认 3）")
    p_agent.add_argument("--timeout", type=int, default=120, help="单条命令执行超时秒数（默认 120）")
    p_agent.set_defaults(func=cmd_agent)

    p_local = sub.add_parser("local", help="以本地模式启动后端（内嵌 PostgreSQL）")
    p_local.add_argument("--config", help="nova-config.json 路径（默认 %%APPDATA%%/Nova/nova-config.json）")
    p_local.add_argument("--host", default="127.0.0.1")
    p_local.add_argument("--port", type=int, default=0, help="0 = 随机空闲端口")
    p_local.add_argument("--pg-backend", choices=["pgserver", "pg_ctl"])
    p_local.set_defaults(func=cmd_local)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())