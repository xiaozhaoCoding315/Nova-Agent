# FastAPI 快速参考

FastAPI 是一个现代、快速（高性能）的 Python Web 框架，用于构建 API，基于标准的 Python 类型提示。

## 核心特性

- **高性能**：与 NodeJS 和 Go 并肩，得益于 Starlette 和 Pydantic。
- **快速编码**：将开发速度提高约 200% 至 300%。
- **更少的Bug**：减少约 40% 的人为（开发者）错误。
- **直观**：强大的编辑器支持，自动补全无处不在。
- **简易**：设计易于使用和学习，减少阅读文档的时间。
- **短代码**：最小化代码重复，每个参数声明多个功能。
- **健壮的**：获取可用于生产的代码，带有自动交互式文档。

## 基本路由

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/items/{item_id}")
async def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}
```

## HTTP 方法装饰器

| 装饰器 | 用途 |
|--------|------|
| `@app.get()` | 读取资源 |
| `@app.post()` | 创建资源 |
| `@app.put()` | 更新资源（完整） |
| `@app.patch()` | 更新资源（部分） |
| `@app.delete()` | 删除资源 |

## 路径参数与验证

路径参数使用 `{}` 语法定义。FastAPI 使用 Python 类型提示进行验证：

```python
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # user_id 自动转换为 int，无效值返回 422
    return {"user_id": user_id}
```

## 查询参数

未在路径中声明的函数参数自动解释为查询参数：

```python
@app.get("/items/")
async def read_items(skip: int = 0, limit: int = 10):
    return fake_items[skip : skip + limit]
```

## 请求体（Pydantic 模型）

```python
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    description: str | None = None
    price: float
    tax: float | None = None

@app.post("/items/")
async def create_item(item: Item):
    return item
```

## 依赖注入

FastAPI 强大的依赖注入系统：

```python
from fastapi import Depends

async def common_parameters(q: str | None = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

@app.get("/items/")
async def read_items(commons: dict = Depends(common_parameters)):
    return commons
```

## 异步支持

FastAPI 同时支持 `async def` 和普通 `def`：

```python
# 异步端点
@app.get("/async")
async def async_endpoint():
    result = await some_async_operation()
    return result

# 同步端点（在线程池中运行）
@app.get("/sync")
def sync_endpoint():
    result = some_blocking_operation()
    return result
```

## 中间件

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 响应模型

使用 `response_model` 过滤输出数据：

```python
class UserIn(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    username: str

@app.post("/user/", response_model=UserOut)
async def create_user(user: UserIn):
    return user  # password 字段被自动过滤
```

## 运行应用

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

访问自动生成的文档：
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 与 NovaTech 的集成

NovaTech Agent 使用 FastAPI 作为后端框架，结合：
- **Qdrant** 向量数据库实现语义检索
- **PostgreSQL** 持久化存储
- **Neo4j** 图数据库实现知识图谱检索
- **SSE (Server-Sent Events)** 实现流式聊天响应
