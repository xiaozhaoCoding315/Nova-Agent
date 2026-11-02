#!/usr/bin/env python3
"""阿里云 ECS 远程部署 Nova Agent（本机运行，通过 SSH 操作服务器）。

用法（在本机 Git Bash / PowerShell 运行）：
  python deploy/remote-deploy.py backup                                  # 备份数据库 / Qdrant / 仓库卷
  python deploy/remote-deploy.py upload  --dashscope-key sk-xxxx          # 打包上传 + 写 .env
  python deploy/remote-deploy.py build                                   # 后台启动 docker compose build
  python deploy/remote-deploy.py status                                  # 查看构建/服务状态
  python deploy/remote-deploy.py logs                                    # 看构建日志尾部
  python deploy/remote-deploy.py installer --file desktop/out/Nova-Agent-Setup-2.1.2.exe

可选参数：--host（默认 60.205.0.224）、--user（默认 root）、--password、
--remote-dir（默认 /opt/nova-agent）、--admin-password / --demo-password（缺省自动生成）、
--llm-provider dashscope|deepseek（默认 dashscope）。
"""
import argparse
import io
import secrets
import string
import sys
import tarfile
from pathlib import Path

import paramiko

EXCLUDE_DIRS = {
    ".git", ".claude", ".superpowers", ".github", ".idea", ".vscode",
    "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".ruff_cache",
    "logs", "data", "desktop", "out", "release", ".vite",
    ".venv", "venv",
}


def build_tarball(root: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:

        def filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
            parts = info.name.split("/")
            if any(part in EXCLUDE_DIRS for part in parts[:-1]) or parts[-1] in EXCLUDE_DIRS:
                return None
            if info.name.endswith((".pyc", ".log", ".env", "mcp_servers.json")):
                return None
            return info

        tar.add(root, arcname=".", filter=filter)
    return buf.getvalue()


def gen_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "!@#$%" for c in pw)):
            return pw


def render_env(args, secret_key: str, admin_pw: str, demo_pw: str) -> str:
    key_line = f"{args.llm_provider.upper()}_API_KEY={args.dashscope_key or ''}"
    return f"""# Nova Agent — 由 deploy/remote-deploy.py 生成
APP_ENV=prod
AUTO_INIT_DB=true
LOG_LEVEL=INFO

# ---- LLM（游客与未配置 Key 的用户使用服务端 Key，因此必须允许回退）----
LLM_ALLOW_SERVER_FALLBACK=true
LLM_MODEL_PRIORITY={args.llm_provider}
{key_line}
DASHSCOPE_MODEL=qwen3.8-max
EMBEDDING_MODEL=text-embedding-v3

# ---- 账号 ----
ADMIN_USERNAME=admin
ADMIN_PASSWORD={admin_pw}
DEMO_USERNAME=demo
DEMO_PASSWORD={demo_pw}
# 注册需邀请码（管理员在设置页生成）；游客每台设备/每 IP 仅一次
REGISTRATION_MODE=invite
REGISTRATION_INVITE_CODE=
MAX_USERS=50
GUEST_ENABLED=true
GUEST_TTL_HOURS=24
GUEST_HOURLY_MESSAGES=3
GUEST_DAILY_TOKENS=50000
GUEST_SANDBOX_DAILY=1
GUEST_JOB_HOURLY=2
GUEST_TOTAL_MESSAGES=3
GUEST_ONCE_IP_DAYS=7
GUEST_STORAGE_MB=100

# ---- 配额（0 = 不限）----
ADMIN_HOURLY_MESSAGES=60
DEMO_HOURLY_MESSAGES=10
ADMIN_DAILY_TOKENS=0
DEMO_DAILY_TOKENS=100000
ADMIN_SANDBOX_DAILY=0
DEMO_SANDBOX_DAILY=20
ADMIN_JOB_HOURLY=30
DEMO_JOB_HOURLY=5

# ---- 安全 ----
SECRET_KEY={secret_key}
COOKIE_SECURE=false

# ---- 沙箱 / 后台 ----
SANDBOX_ENABLED=true
SANDBOX_ALLOW_NETWORK=false
BUILDER_SMOKE_ENABLED=true
PREVIEW_TTL_MINUTES=120
SKILLS_ENABLED=true
MCP_ENABLED=true

# ---- 联网搜索 ----
ENABLE_WEB_SEARCH=true
WEB_SEARCH_PROVIDER=auto
"""


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    text = out + (f"\n[stderr]\n{err}" if err.strip() else "")
    return code, text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=["backup", "upload", "build", "status", "logs", "health", "installer"],
    )
    parser.add_argument("--host", default="60.205.0.224")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default=None, help="SSH 密码；省略时使用密钥/agent 认证")
    parser.add_argument("--remote-dir", default="/opt/nova-agent")
    parser.add_argument("--file", default="", help="installer 阶段：本地安装包路径")
    parser.add_argument("--dashscope-key", default="")
    parser.add_argument("--llm-provider", choices=["dashscope", "deepseek"], default="dashscope")
    parser.add_argument("--admin-password", default="")
    parser.add_argument("--demo-password", default="")
    args = parser.parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"==> 连接 {args.user}@{args.host}")
    if args.password:
        ssh.connect(args.host, username=args.user, password=args.password, timeout=15)
    else:
        print("    未提供 --password，使用 SSH 密钥 / agent 认证")
        ssh.connect(args.host, username=args.user, timeout=15)

    if args.phase == "backup":
        script = f"{args.remote_dir}/deploy/backup.sh"
        code, out = run(ssh, f"test -f {script} && echo FOUND || echo MISSING")
        if "MISSING" in out:
            print(f"!! 服务器上找不到 {script}，请先执行 upload 上传源码")
            ssh.close()
            return 1
        print("==> 备份 PostgreSQL / Qdrant / 仓库卷到 /opt/nova-backups")
        code, out = run(
            ssh,
            f"mkdir -p /opt/nova-backups && cd {args.remote_dir} && "
            "BACKUP_DIR=/opt/nova-backups bash deploy/backup.sh",
            timeout=900,
        )
        print(out[-4000:])
        code, out = run(ssh, "ls -lh /opt/nova-backups | tail -n 8")
        print(out.strip())
        ssh.close()
        return code

    if args.phase == "upload":
        code, out = run(ssh, "command -v docker || echo NO_DOCKER")
        print("Docker:", "未安装（稍后由 setup 脚本安装）" if "NO_DOCKER" in out else "已安装")
        print("==> 本机打包源码（不含 node_modules / 安装包 / 数据目录）")
        blob = build_tarball(".")
        print(f"    包大小 {len(blob) / 1048576:.1f} MB，开始上传（1Mbps 带宽约需 {len(blob) * 8 / 1_000_000 / 60:.0f} 分钟）")
        sftp = ssh.open_sftp()
        with sftp.file("/tmp/nova-src.tar.gz", "wb") as f:
            f.write(blob)
        sftp.close()
        print("==> 解压到服务器")
        # 先清掉旧源码目录：tar 只覆盖同名文件，本地已删除的旧组件会残留并参与构建。
        # 只清代码目录，data/、.env、日志和上传目录都不动。
        code, out = run(
            ssh,
            f"mkdir -p {args.remote_dir} && cd {args.remote_dir} && "
            "rm -rf frontend/src backend/app backend/tests && "
            "tar xzf /tmp/nova-src.tar.gz && ls | tr '\\n' ' '",
        )
        print(out.strip())
        # .env 只在首次生成，避免覆盖已填好的 Key
        code, out = run(ssh, f"test -f {args.remote_dir}/.env && echo EXISTS || echo MISSING")
        if "MISSING" in out:
            secret_key = secrets.token_hex(32)
            admin_pw = args.admin_password or gen_password()
            demo_pw = args.demo_password or gen_password()
            env = render_env(args, secret_key, admin_pw, demo_pw)
            sftp = ssh.open_sftp()
            with sftp.file(f"{args.remote_dir}/.env", "w") as f:
                f.write(env)
            sftp.close()
            print("==> 已生成 .env")
            if not args.dashscope_key:
                print("!! 注意：未提供 LLM Key，游客对话会报模型未配置。可重跑 upload 并带 --dashscope-key，或手动编辑 .env")
            print("=" * 52)
            print(f"  管理员账号：admin / {admin_pw}")
            print(f"  演示账号：  demo  / {demo_pw}")
            print("  （请妥善保存，Demo 密码不对外公开）")
            print("=" * 52)
        else:
            print("==> .env 已存在，保持不变")
        print("上传完成。下一步：python deploy/remote-deploy.py build")

    elif args.phase == "build":
        code, out = run(ssh, "command -v docker || echo NO_DOCKER")
        if "NO_DOCKER" in out:
            print("==> 服务器没有 Docker，先跑一键准备脚本（装 Docker/镜像加速/swap）")
            code, out = run(ssh, f"cd {args.remote_dir} && bash deploy/setup-aliyun.sh {args.remote_dir}", timeout=600)
            print(out[-2000:])
        cmd = (
            f"cd {args.remote_dir} && "
            "setsid docker compose up -d --build < /dev/null > build.log 2>&1 & "
            "echo BUILD_STARTED"
        )
        try:
            _, out = run(ssh, cmd, timeout=20)
            print(out.strip())
        except Exception:  # noqa: BLE001 - 后台构建仍会继续，连接超时不是失败
            print("BUILD_STARTED（未等待远端输出）")
        print("构建已在后台启动。镜像下载耗时取决于带宽，用 status/logs 查看进度。")

    elif args.phase == "status":
        code, out = run(ssh, f"cd {args.remote_dir} && docker compose ps --format 'table {{{{.Name}}}}\\t{{{{.Status}}}}' 2>/dev/null; echo ---; tail -n 12 build.log 2>/dev/null; echo ---; curl -s -o /dev/null -w 'health: %{{http_code}}\\n' http://127.0.0.1:8000/api/v1/status/health")
        print(out.strip())

    elif args.phase == "logs":
        code, out = run(ssh, f"tail -n 60 {args.remote_dir}/build.log 2>/dev/null || echo 暂无日志")
        print(out.strip())

    elif args.phase == "installer":
        source = Path(args.file).expanduser() if args.file else None
        if source is None or not source.is_file():
            print("!! installer 阶段需要 --file 指向本地安装包", file=sys.stderr)
            ssh.close()
            return 1
        remote_dir = f"{args.remote_dir}/data/downloads"
        remote_path = f"{remote_dir}/{source.name}"
        run(ssh, f"mkdir -p {remote_dir}")
        print(f"==> 上传 {source}（{source.stat().st_size / 1048576:.1f} MB）")
        sftp = ssh.open_sftp()
        try:
            sftp.put(str(source), remote_path)
        finally:
            sftp.close()
        code, out = run(ssh, f"ls -lh {remote_path}")
        print(out.strip())
        code, out = run(
            ssh,
            "curl -s -o /dev/null -w '%{http_code}' "
            f"http://127.0.0.1:8000/downloads/files/{source.name}",
        )
        print(f"下载接口 HTTP {out.strip()}")
        code, out = run(ssh, "curl -s http://127.0.0.1:8000/downloads | grep -c 'item'")
        print(f"下载页条目数：{out.strip()}")

    elif args.phase == "health":
        code, out = run(ssh, "curl -s http://127.0.0.1:8000/api/v1/status/health | head -c 600")
        print(out.strip())

    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
