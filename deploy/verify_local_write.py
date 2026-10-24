"""End-to-end verification: dispatch a local write request and confirm the file lands."""
import time

import paramiko

import os

HOST = os.environ.get("NOVA_SSH_HOST", "")
PASSWORD = os.environ["NOVA_SSH_PASSWORD"]  # 不落盘：从环境变量读取

SQL = """
INSERT INTO local_exec_requests (id, user_id, cwd, command, kind, file_path, content)
VALUES ('11111111-2222-3333-4444-555555555555', 1, '.', '[write file] output/hello.py',
        'write', 'output/hello.py', 'print("hello from nova")')
ON CONFLICT (id) DO NOTHING;
"""


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username="root", password=PASSWORD, timeout=15)

    sftp = ssh.open_sftp()
    with sftp.file("/tmp/dispatch.sql", "w") as f:
        f.write(SQL)
    sftp.close()

    ssh.exec_command("docker cp /tmp/dispatch.sql nova-agent-postgres-1:/tmp/dispatch.sql", timeout=30)
    time.sleep(2)
    _, out, err = ssh.exec_command(
        "docker exec nova-agent-postgres-1 psql -U postgres -d nova_agent -f /tmp/dispatch.sql",
        timeout=30,
    )
    print(out.read().decode("utf-8", "replace"))
    e = err.read().decode("utf-8", "replace").strip()
    if e:
        print("[err]", e[:300])

    time.sleep(12)
    _, out, _ = ssh.exec_command(
        "docker exec nova-agent-app-1 cat /tmp/nova-e2e/output/hello.py 2>/dev/null; echo ---; "
        "docker exec nova-agent-postgres-1 psql -U postgres -d nova_agent -c "
        "\"SELECT status, exit_code, left(output, 90) FROM local_exec_requests "
        "WHERE id = '11111111-2222-3333-4444-555555555555'\"; echo ---; "
        "docker exec nova-agent-app-1 tail -5 /tmp/nova-agent.log",
        timeout=60,
    )
    print(out.read().decode("utf-8", "replace"))
    ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
