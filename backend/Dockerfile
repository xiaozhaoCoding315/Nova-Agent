# Multi-stage build: frontend (Vite) -> backend (FastAPI serving dist in prod)
FROM node:20-slim AS frontend-build
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Backend source at /app (matches `python run.py` from repo root backend/)
COPY backend/ ./

# Frontend dist must land at /frontend/dist: app/main.py resolves
# parents[2]/frontend/dist == /frontend/dist inside the container.
COPY --from=frontend-build /web/dist /frontend/dist

ENV APP_ENV=prod PYTHONUNBUFFERED=1
RUN chown -R nobody:nogroup /app /frontend
USER nobody

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"

CMD ["python", "run.py"]
