# ---------- Stage 1: build frontend ----------
FROM node:20-alpine AS frontend-build
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: official docker CLI (drives the code sandbox) ----------
FROM docker:27-cli AS dockercli

# ---------- Stage 3: runtime ----------
FROM python:3.12-slim AS runtime

# 国内服务器构建：Debian 官方源在境内很慢，统一切到阿里云镜像
RUN sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends util-linux git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /web/dist /app/frontend_dist

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