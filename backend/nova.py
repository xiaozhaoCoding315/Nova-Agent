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



# ---------------- local bridge: 本地目录 <-> Nova 仓库 双向同步 ----------------

BRIDGE_FILE = ".nova-bridge.json"
BRIDGE_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
                 "build", ".nova-bridge.json", ".idea", ".vscode"}


def _zip_dir(root: Path, out: Path) -> int:
    import zipfile
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(root)
            if any(part in BRIDGE_IGNORE for part in rel.parts):
                continue
            if path.stat().st_size > 4 * 1024 * 1024:
                continue
            zf.write(path, str(rel))
            count += 1
    return count


def _load_bridge(root: Path) -> dict:
    f = root / BRIDGE_FILE
    if not f.is_file():
        print("未初始化：先运行 nova bridge init <目录>", file=sys.stderr)
        sys.exit(2)
    return json.loads(f.read_text(encoding="utf-8"))


def _save_bridge(root: Path, data: dict) -> None:
    (root / BRIDGE_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest(root: Path) -> dict:
    import hashlib
    items = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = str(path.relative_to(root)).replace(os.sep, "/")
        if any(part in BRIDGE_IGNORE for part in rel.split("/")):
            continue
        items[rel] = hashlib.md5(path.read_bytes()).hexdigest()
    return items


def cmd_bridge_init(args) -> int:
    root = Path(args.dir).resolve()
    if not root.is_dir():
        print(f"目录不存在：{root}", file=sys.stderr)
        return 2
    c = client()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        tmp = Path(tf.name)
    count = _zip_dir(root, tmp)
    if count == 0:
        print("目录里没有可同步的文件", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return 2
    with open(tmp, "rb") as fh:
        r = c.post(
            "/api/v1/repos/upload",
            files={"file": (f"{root.name}.zip", fh, "application/zip")},
        )
    tmp.unlink(missing_ok=True)
    if r.status_code != 200:
        print(f"创建仓库失败（{r.status_code}）：{r.text[:200]}", file=sys.stderr)
        return 2
    repo = r.json()
    _save_bridge(root, {
        "repo_id": repo["id"], "repo_name": repo.get("name", root.name),
        "url": os.getenv("NOVA_URL", "http://localhost:8000"),
        "local_manifest": _manifest(root),
    })
    print(f"已关联：{root} <-> {repo.get('name')} ({repo['id']})，索引建立后即可对话")
    return 0


def cmd_bridge_push(args) -> int:
    root = Path(args.dir).resolve()
    cfg = _load_bridge(root)
    c = client()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        tmp = Path(tf.name)
    count = _zip_dir(root, tmp)
    with open(tmp, "rb") as fh:
        r = c.put(
            f"/api/v1/repos/{cfg['repo_id']}/files",
            files={"file": (f"{cfg.get('repo_name', 'bridge')}.zip", fh, "application/zip")},
        )
    tmp.unlink(missing_ok=True)
    if r.status_code != 200:
        print(f"推送失败（{r.status_code}）：{r.text[:200]}", file=sys.stderr)
        return 2
    cfg["local_manifest"] = _manifest(root)
    _save_bridge(root, cfg)
    print(f"已推送 {count} 个文件（服务端正在重建索引）")
    return 0


def cmd_bridge_pull(args) -> int:
    import zipfile
    root = Path(args.dir).resolve()
    cfg = _load_bridge(root)
    c = client()
    r = c.get(f"/api/v1/repos/{cfg['repo_id']}/export")
    if r.status_code != 200:
        print(f"拉取失败（{r.status_code}）：{r.text[:200]}", file=sys.stderr)
        return 2
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        tf.write(r.content)
        tmp = Path(tf.name)
    local = _manifest(root)
    written = skipped = 0
    with zipfile.ZipFile(tmp) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        for m in members:
            rel = m.filename.replace(os.sep, "/")
            if any(part in BRIDGE_IGNORE for part in rel.split("/")):
                continue
            target = root / rel
            if target.exists():
                import hashlib
                if hashlib.md5(target.read_bytes()).hexdigest() == hashlib.md5(zf.read(m)).hexdigest():
                    skipped += 1
                    continue
                if rel in local and not args.force:
                    print(f"本地已修改，跳过（--force 覆盖）：{rel}", file=sys.stderr)
                    skipped += 1
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(m))
            written += 1
    tmp.unlink(missing_ok=True)
    cfg["local_manifest"] = _manifest(root)
    _save_bridge(root, cfg)
    print(f"已拉取：写入 {written} 个文件，跳过 {skipped} 个")
    return 0


def cmd_bridge_watch(args) -> int:
    root = Path(args.dir).resolve()
    cfg = _load_bridge(root)
    interval = max(int(args.interval or 5), 2)
    print(f"监听 {root}（每 {interval}s 检查一次，Ctrl+C 退出）")
    last = _manifest(root)
    while True:
        try:
            time.sleep(interval)
            current = _manifest(root)
            if current != last:
                print(f"[{time.strftime('%H:%M:%S')}] 检测到本地改动，推送…")
                code = cmd_bridge_push(args)
                if code == 0:
                    last = _manifest(root)
            r = client().get(f"/api/v1/repos/{cfg['repo_id']}")
            if r.status_code == 200:
                repo = r.json()
                if repo.get("updated_at") and repo["updated_at"] != cfg.get("last_pulled_at"):
                    pass  # pull 仍需手动触发，避免覆盖未保存的本地编辑
        except KeyboardInterrupt:
            print("已停止")
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

    p_bridge = sub.add_parser("bridge", help="本地目录 <-> Nova 仓库桥接")
    b_sub = p_bridge.add_subparsers(dest="bridge_cmd", required=True)
    b_init = b_sub.add_parser("init", help="关联本地目录（上传并创建仓库）")
    b_init.add_argument("dir")
    b_init.set_defaults(func=cmd_bridge_init)
    b_push = b_sub.add_parser("push", help="推送本地改动到仓库")
    b_push.add_argument("dir")
    b_push.set_defaults(func=cmd_bridge_push)
    b_pull = b_sub.add_parser("pull", help="拉取仓库改动到本地（默认不覆盖本地已改文件）")
    b_pull.add_argument("dir")
    b_pull.add_argument("--force", action="store_true")
    b_pull.set_defaults(func=cmd_bridge_pull)
    b_watch = b_sub.add_parser("watch", help="监听本地改动并自动推送")
    b_watch.add_argument("dir")
    b_watch.add_argument("--interval", type=int, default=5)
    b_watch.set_defaults(func=cmd_bridge_watch)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())