"""Deploy smoke test: run against the server over SSH."""
import json
import sys

import paramiko

import os

HOST = os.environ.get("NOVA_SSH_HOST", "")
PASSWORD = os.environ["NOVA_SSH_PASSWORD"]  # 不落盘：从环境变量读取

REMOTE = r'''
set -e
ADMIN_PW=$(grep '^ADMIN_PASSWORD=' /opt/nova-agent/.env | cut -d= -f2)
echo "=== admin login ==="
curl -s -c /tmp/admin.txt -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PW\"}" | head -c 120
echo
echo "=== admin creates invite (max 1 use) ==="
INVITE=$(curl -s -b /tmp/admin.txt -X POST http://127.0.0.1:8000/api/v1/admin/invites \
  -H "Content-Type: application/json" \
  -d '{"note":"smoke","max_uses":1,"expires_days":30}')
echo "$INVITE"
CODE=$(echo "$INVITE" | python3 -c "import sys,json;print(json.load(sys.stdin)['code'])")
echo "=== register with invite code: $CODE ==="
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"smoketest1\",\"password\":\"smokepass123\",\"invite_code\":\"$CODE\"}" | head -c 160
echo
echo "=== reuse same code (should fail) ==="
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"smoketest2\",\"password\":\"smokepass123\",\"invite_code\":\"$CODE\"}"
echo
echo "=== docker socket perms ==="
ls -l /var/run/docker.sock
docker exec nova-agent-app-1 ls -l /var/run/docker.sock
'''


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username="root", password=PASSWORD, timeout=15)
    _, out, err = ssh.exec_command(REMOTE, timeout=90)
    print(out.read().decode("utf-8", "replace"))
    e = err.read().decode("utf-8", "replace").strip()
    if e:
        print("[stderr]", e[:500])
    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
