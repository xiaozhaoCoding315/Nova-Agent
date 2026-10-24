#!/bin/sh
set -e

# Named volumes are created root-owned on first use; fix ownership of the data
# dir once, then drop privileges to the unprivileged app user (uid 10001).
# setpriv ships with util-linux (installed in the image).
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R nova:nova /app/data 2>/dev/null || true
  # 沙箱工具要访问宿主 docker daemon；socket 默认 root:docker，降权后不可读，
  # 交给运行用户属主（容器内 root 有 CAP_CHOWN，宿主 socket 属主会被改写）。
  if [ -S /var/run/docker.sock ]; then
    chown nova:nova /var/run/docker.sock 2>/dev/null || true
  fi
  exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi

exec "$@"