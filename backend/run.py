"""启动 NovaTech Agent 后端服务"""
import os
import sys

# 确保当前目录在 sys.path 第一位，避免包名冲突
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 下 psycopg 需要 SelectorEventLoop
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

APP_ENV = os.getenv("APP_ENV", "dev")
APP_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    if APP_ENV == "prod":
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            workers=1,  # Windows 下多 worker 不稳定，个人自用单 worker 足够
            log_level="info",
        )
    else:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
            reload_dirs=[APP_DIR],
        )
