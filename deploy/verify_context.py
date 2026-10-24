"""Verify the context SSE event end-to-end on the deployed server."""
import json
import re
import urllib.request

import paramiko

import os

HOST = os.environ.get("NOVA_SSH_HOST", "")
PASSWORD = os.environ["NOVA_SSH_PASSWORD"]  # 不落盘：从环境变量读取

SCRIPT = r'''#!/usr/bin/env python3
import json, re, urllib.request

BASE = "http://127.0.0.1:8000/api/v1"

def call(path, payload=None, token=None, method=None):
    req = urllib.request.Request(BASE + path, method=method or ("POST" if payload is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Cookie", "nova_token=" + token)
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=120) as resp:
            set_cookie = resp.headers.get("Set-Cookie", "")
            body = json.loads(resp.read().decode())
            return resp.status, body, set_cookie
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()), ""

admin_pw = ""
for line in open("/opt/nova-agent/.env"):
    if line.startswith("ADMIN_PASSWORD="):
        admin_pw = line.split("=", 1)[1].strip()

status, body, set_cookie = call("/auth/login", {"username": "admin", "password": admin_pw})
token = re.search(r"nova_token=([^;]+)", set_cookie).group(1)
print("login:", status)

status, body, _ = call("/chat/sessions", {}, token=token)
sid = body["id"]
print("session:", status, sid[:8])

req = urllib.request.Request(BASE + "/chat/message", method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("Cookie", "nova_token=" + token)
payload = json.dumps({"session_id": sid, "content": "用一个词回答：你好", "permission_mode": "readonly"}).encode()
found = False
with urllib.request.urlopen(req, data=payload, timeout=120) as resp:
    event = None
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event == "context":
            print("context:", line[5:].strip()[:420])
            found = True
        elif line.startswith("data:") and event == "done":
            break
print("context event found:", found)
'''


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username="root", password=PASSWORD, timeout=15)
    sftp = ssh.open_sftp()
    with sftp.file("/tmp/verify_context.py", "w") as f:
        f.write(SCRIPT)
    sftp.close()
    _, out, err = ssh.exec_command("python3 /tmp/verify_context.py", timeout=180)
    print(out.read().decode("utf-8", "replace"))
    e = err.read().decode("utf-8", "replace").strip()
    if e:
        print("[stderr]", e[:500])
    ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
