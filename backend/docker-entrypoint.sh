#!/bin/sh
set -e

# Named volumes are created root-owned on first use; fix ownership of the data
# dir once, then drop privileges to the unprivileged app user (uid 10001).
# setpriv ships with util-linux (installed in the image).
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R nova:nova /app/data 2>/dev/null || true
  exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi

exec "$@"