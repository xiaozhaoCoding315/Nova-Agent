#!/usr/bin/env bash
# 阿里云 ECS（Ubuntu 22.04/24.04）一键准备环境并启动 Nova Agent
# 用法：把整个项目上传到服务器后，以 root 执行：
#   bash deploy/setup-aliyun.sh [项目目录，默认 /opt/nova-agent]
# 前提：实例已换成 Ubuntu 系统；安全组已放行 8000 端口（TCP）。
set -euo pipefail

PROJECT_DIR="${1:-/opt/nova-agent}"

if [[ "$(id -u)" != "0" ]]; then
  echo "请用 root 运行：sudo bash deploy/setup-aliyun.sh" >&2
  exit 1
fi

echo "==> 1/5 基础工具"
apt-get update -y
apt-get install -y git curl ca-certificates

echo "==> 2/5 安装 Docker（阿里云镜像源）"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
fi
systemctl enable --now docker

echo "==> 3/5 配置镜像加速（国内拉取 Docker Hub 必需）"
mkdir -p /etc/docker
if [[ ! -f /etc/docker/daemon.json ]] || ! grep -q registry-mirrors /etc/docker/daemon.json; then
  cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run"
  ]
}
EOF
  systemctl daemon-reload && systemctl restart docker
fi
echo "提示：可在阿里云控制台「容器镜像服务 → 镜像加速器」获取你的专属加速地址，替换上表第一个。"

echo "==> 4/5 创建 2G swap（2G 内存机器上构建前端镜像必需）"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> 5/5 启动 Nova Agent"
cd "$PROJECT_DIR"
if [[ ! -f .env ]]; then
  cp .env.docker.example .env
  echo "已生成 .env —— 请先编辑填入 LLM Key、SECRET_KEY、账号密码，再重新执行本脚本："
  echo "  vim $PROJECT_DIR/.env && sudo bash deploy/setup-aliyun.sh $PROJECT_DIR"
  exit 0
fi
docker compose up -d --build
echo
echo "完成。访问 http://<公网IP>:8000 ；安装包下载页 http://<公网IP>:8000/downloads"
echo "查看日志：docker compose -f $PROJECT_DIR/docker-compose.yml logs -f app"
