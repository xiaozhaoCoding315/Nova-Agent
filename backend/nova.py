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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())