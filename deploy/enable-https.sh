#!/usr/bin/env bash
# Nova Agent HTTPS 上线预检与启用（在大陆 ECS 上、ICP 备案通过后运行）。
#
#   bash deploy/enable-https.sh            # 只检查，不改任何东西
#   bash deploy/enable-https.sh --apply    # 修可修的 .env、启动 Caddy，失败自动回滚
#
# 它检查四类东西：DNS/ICP 是否就绪、80/443 是否空闲、Caddyfile 是否有效、
# .env 里 APP_BIND / TRUSTED_PROXIES / CORS_ORIGINS / COOKIE_SECURE 是否配套。
# 不会自动去改博客项目的 compose；80 被博客占用时会停下来提示手工让出。
set -euo pipefail

ROOT="${NOVA_DIR:-/opt/nova-agent}"
DOMAIN="${NOVA_DOMAIN:-nova.zxycoder.cn}"
BLOG_DOMAIN="${BLOG_DOMAIN:-zxycoder.cn}"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

cd "$ROOT"
if [ ! -f .env ]; then
  echo "找不到 $ROOT/.env" >&2
  exit 1
fi

blocked=0
say() { printf '%s\n' "$*"; }
ok() { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
stop() { printf '  [stop] %s\n' "$*"; blocked=1; }
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }

say "Nova HTTPS 预检 · 目录 $ROOT · 域名 $DOMAIN"

say ""
say "1. 配置"
app_bind="$(env_value APP_BIND)"
trusted="$(env_value TRUSTED_PROXIES)"
cors="$(env_value CORS_ORIGINS)"
cookie="$(env_value COOKIE_SECURE)"
subnet="$(docker network inspect nova-agent_default --format '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null || true)"

if [ "$app_bind" = "127.0.0.1" ]; then
  ok "APP_BIND=127.0.0.1"
else
  warn "APP_BIND=${app_bind:-<空>}（apply 会改成 127.0.0.1，避免 :8000 明文旁路）"
fi
if [ -n "$subnet" ]; then
  ok "Docker 网段 $subnet"
  case "$trusted" in
    *"${subnet%/*}"*) ok "TRUSTED_PROXIES 包含该网段" ;;
    *) warn "TRUSTED_PROXIES=${trusted:-<空>} 未包含 $subnet（apply 会补上）" ;;
  esac
else
  stop "找不到 nova-agent_default 网段，先确认 docker compose 已启动"
fi
case "$cors" in
  *"https://$DOMAIN"*) ok "CORS_ORIGINS 包含 https://$DOMAIN" ;;
  *) warn "CORS_ORIGINS=${cors:-<空>} 未包含 https://$DOMAIN（apply 会追加）" ;;
esac
if [ "$cookie" = "true" ]; then
  ok "COOKIE_SECURE=true"
else
  warn "COOKIE_SECURE=${cookie:-<空>}（apply 会设为 true）"
fi

say ""
say "2. DNS"
for host in "$DOMAIN" "$BLOG_DOMAIN" "www.$BLOG_DOMAIN"; do
  ip="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}')"
  if [ -n "$ip" ]; then
    ok "$host -> $ip"
  else
    stop "$host 无法解析，先在阿里云云解析里加 A 记录"
  fi
done

say ""
say "3. ICP 备案"
ip="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}')"
if [ -n "$ip" ]; then
  body="$(curl -s -m 8 -H "Host: $DOMAIN" "http://$ip/" || true)"
  if printf '%s' "$body" | grep -qi 'Non-compliance ICP Filing'; then
    stop "ICP 备案未通过：80 端口仍被接入商按 Host 头拦截"
  else
    ok "未触发 ICP 拦截（或已备案）"
  fi
else
  stop "没有解析地址，跳过 ICP 检查"
fi

say ""
say "4. 端口"
for port in 80 443; do
  if ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN; then
    owner="$(docker ps --filter "publish=$port" --format '{{.Names}}' | head -1)"
    if printf '%s' "$owner" | grep -qi caddy; then
      ok "端口 $port 由 Caddy 占用（HTTPS 已在运行）"
      continue
    fi
    stop "端口 $port 已被占用${owner:+（$owner）}；Caddy 需要 80 做跳转与证书验证"
    if [ "$port" = "80" ] && [ -n "$owner" ]; then
      say "         如果是博客容器，先注释它 compose 里的 \"80:3000\" 映射再重启博客；"
      say "         Caddy 会用 blog-app-1:3000 直接访问博客。"
    fi
  else
    ok "端口 $port 空闲"
  fi
done

say ""
say "5. Caddy"
if [ -f Caddyfile ]; then
  ok "Caddyfile 存在"
else
  stop "缺少 Caddyfile"
fi
if docker image inspect caddy:2-alpine >/dev/null 2>&1; then
  if docker run --rm -v "$ROOT/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine \
      caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
    ok "Caddyfile 校验通过"
  else
    stop "Caddyfile 校验失败"
  fi
else
  warn "本机还没有 caddy:2-alpine 镜像；apply 时会拉取"
fi
if docker compose --profile https config >/dev/null 2>&1; then
  ok "docker compose https profile 可解析"
else
  stop "docker compose https profile 解析失败（blog_default 外部网络是否存在？）"
fi

if [ "$APPLY" != "1" ]; then
  say ""
  if [ "$blocked" = "1" ]; then
    say "预检未通过。解决上面的 [stop] 项后，再运行：bash deploy/enable-https.sh --apply"
    exit 1
  fi
  say "预检通过。执行：bash deploy/enable-https.sh --apply"
  exit 0
fi

say ""
say "6. 应用配置并启动 Caddy"
if [ "$blocked" = "1" ]; then
  say "预检未通过，未做任何改动。"
  exit 1
fi

backup=".env.bak-https-$(date +%Y%m%d_%H%M%S)"
cp .env "$backup"
say "已备份 .env -> $backup"

set_env() {
  local key="$1" value="$2"
  if grep -qE "^$key=" .env; then
    sed -i "s|^$key=.*|$key=$value|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

set_env APP_BIND 127.0.0.1
set_env COOKIE_SECURE true
if [ -n "$subnet" ]; then
  case "$(env_value TRUSTED_PROXIES)" in
    *"${subnet%/*}"*) ;;
    *) set_env TRUSTED_PROXIES "$subnet" ;;
  esac
fi
if ! printf '%s' "$(env_value CORS_ORIGINS)" | grep -q "https://$DOMAIN"; then
  current="$(env_value CORS_ORIGINS)"
  if [ -n "$current" ]; then
    set_env CORS_ORIGINS "${current},https://$DOMAIN"
  else
    set_env CORS_ORIGINS "https://$DOMAIN"
  fi
fi

docker compose up -d --no-build app
docker compose --profile https up -d caddy

say "等待证书与 HTTPS 健康检查（最多 120 秒）…"
healthy=0
for _ in $(seq 1 24); do
  if curl -fsS -m 8 "https://$DOMAIN/api/v1/status/health" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 5
done

if [ "$healthy" = "1" ]; then
  say "HTTPS 已生效：https://$DOMAIN"
  say "把桌面客户端与手机配对链接都改用这个地址；确认无问题后可删除 $backup。"
  exit 0
fi

say "HTTPS 健康检查失败，自动回滚到直连模式…"
cp "$backup" .env
docker compose --profile https stop caddy >/dev/null 2>&1 || true
docker compose up -d --no-build app
say "已回滚 .env 并恢复 app。查看日志：docker compose logs --tail=100 caddy"
say "常见原因：ICP 未生效、80 被占用、DNS 未指向本机、安全组未放行 443。"
exit 1
