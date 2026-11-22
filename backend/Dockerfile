# ---------- Stage 1: build frontend ----------
FROM node:20-alpine AS frontend-build
WORKDIR /web
COPY frontend/package*.json ./
# 国内服务器直连 registry.npmjs.org 经常超时；默认走 npmmirror，
# 海外构建可用 --build-arg NPM_REGISTRY=https://registry.npmjs.org 覆盖。
ARG NPM_REGISTRY=https://registry.npmmirror.com
# 1Mbps 的 ECS 上 npm 偶尔会卡在 read 超时；放宽重试与单次超时，
# 并用 --prefer-offline 优先复用构建缓存里的包。
RUN npm config set registry "$NPM_REGISTRY" \
 && npm config set fetch-retries 8 \
 && npm config set fetch-retry-mintimeout 10000 \
 && npm config set fetch-retry-maxtimeout 120000 \
 && npm config set fetch-timeout 600000 \
 && npm ci --no-audit --no-fund --prefer-offline
COPY frontend/ ./
# ICP 备案号是构建期变量（Vite 在打包时把 import.meta.env 静态替换），
# 所以只能在这里注入；留空则不渲染。改了它必须重建镜像，改 .env 不生效。
ARG VITE_ICP_BEIAN=
ENV VITE_ICP_BEIAN=$VITE_ICP_BEIAN
RUN npm run build

# ---------- Stage 2: official docker CLI (drives the code sandbox) ----------
FROM docker:27-cli AS dockercli

# ---------- Stage 3: runtime base (without the frontend build) ----------
# 拆成 runtime-base + runtime 两个阶段，是为了在 2G/1Mbps 的 ECS 上
# 先单独缓存 apt/pip 这些大层，再在第二次构建里只跑 npm，避免两个
# 大下载阶段同时抢带宽导致 npm read timeout。
FROM python:3.12-slim AS runtime-base

# 国内服务器构建：Debian 官方源在境内很慢，统一切到阿里云镜像
RUN sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources \
 && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update \
 && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 install -y --no-install-recommends \
      util-linux git \
      pandoc libreoffice-writer-nogui fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY backend/ ./
COPY thesis-templates/ /app/thesis-templates

RUN useradd -m -u 10001 nova \
 && mkdir -p /app/data/logs /app/data/repos \
 && chown -R nova:nova /app/data

ENV APP_ENV=prod \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/frontend_dist \
    LOG_DIR=/app/data/logs \
    REPOS_DIR=/app/data/repos \
    SANDBOX_IMAGE=nova-sandbox:latest

COPY backend/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=6s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/status/health', timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "run.py"]

# ---------- Stage 4: final image (adds the built frontend) ----------
FROM runtime-base AS runtime
COPY --from=frontend-build /web/dist /app/frontend_dist