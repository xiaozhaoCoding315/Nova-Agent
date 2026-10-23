# Verification image for repo builds/tests. No network needed at runtime:
# common web/test dependencies are preinstalled so generated FastAPI projects
# can actually run pytest inside the sandbox.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        fastapi==0.115.0 \
        uvicorn==0.30.6 \
        pydantic==2.9.2 \
        pytest==8.3.3 \
        httpx==0.27.2 \
        numpy==2.1.3 \
        ruff==0.8.6 \
        mypy==1.13.0

WORKDIR /workspace