"""启动 NovaTech Agent 后端服务"""
import sys
import os

# 确保当前目录在 sys.path 第一位，避免包名冲突
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 下 psycopg 需要 SelectorEventLoop
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        reload_dirs=[os.path.dirname(os.path.abspath(__file__))],
    )
