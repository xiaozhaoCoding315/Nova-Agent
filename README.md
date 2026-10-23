# Nova Agent — 开发者 AI 工作台

一个**可自托管**的 AI 开发助手：读懂你的代码、定位你的报错、验证你的代码。不是通用聊天机器人，而是围绕「代码检索 → 报错诊断 → 沙箱执行验证」闭环设计的开发者工具。

## 解决什么问题

写代码时最常卡住的四件事，Nova 都有对应的确定性能力（不是"让模型自由发挥"）：

| 场景 | 怎么用 | 背后机制 |
|---|---|---|
| **读懂陌生代码库** | 导入仓库（ZIP / Git URL），直接问「X 功能在哪个文件实现的？」 | 符号级代码索引（函数/类/接口）+ 语义与关键词双路检索，回答携带 `文件:行号` 引用 |
| **排查报错** | 贴 Python / JVM / Node / Go 堆栈 | 确定性解析错误类型、消息与调用帧 → 在仓库中定位对应文件 → 结合检索给出修复建议 |
| **验证代码/生成测试** | 「给这个函数写单测，并跑通」 | LLM 写代码 → **Docker 沙箱真实执行** → 读取 stdout/退出码 → 自我纠错迭代（≤5 轮），直到测试全绿 |
| **日常杂活** | JSON/YAML 校验转换、SQL 审阅、抓取在线文档 | json_tool / sql_tool / fetch_url，全部确定性实现，结果即真相 |

## 核心特性

### 代码感知的混合检索
- **符号索引**：Python 用 AST、Java/TS/JS/Go 等用结构化正则，按函数/类边界提取符号表（名称、类型、起止行号）
- **双路召回 + RRF 融合**：Qdrant 稠密向量（语义）+ PostgreSQL 全文（jieba 中文分词预处理）并行检索，单路故障自动降级
- **引用可核对**：每条命中都带真实 `路径:行号`，前端可一键复制引用

### Agent 循环 + Function-Calling
- 6 个工具：`run_code`（沙箱执行）、`diagnose_error`（堆栈解析+仓库定位）、`search_code`（符号+混合检索）、`json_tool`、`sql_tool`、`fetch_url`（带 SSRF 防护）
- 工具调用全链路可视：SSE 实时推送 `tool_call` / `tool_result` 事件，前端渲染工具卡片（入参 / 结果 / 耗时）
- 工具执行纳入容错框架：分级超时（LLM 90s / 检索 10s / 工具 30s）、指数退避重试、熔断降级；业务性失败（参数错误、配额）与基础设施故障区分统计

### Docker 安全沙箱（绝不降级）
- LLM 生成的代码只在锁定容器中执行：**禁网络 + 只读根文件系统 + 丢弃全部 capabilities + 非 root uid + pid/内存/CPU 限额**
- 沙箱镜像预装 numpy / pytest，「写测试 → 运行 → 迭代」开箱即用
- Docker 不可用时工具**如实标记不可用**，绝不退化为在宿主机执行

### 产品化能力
- **登录认证**：JWT（httpOnly cookie）+ bcrypt；`admin` / `demo` 双角色，demo 账号供演示访问且带限额（10 条/小时、每日 token 预算、沙箱次数）
- **会话持久化**：历史会话与消息落库，刷新不丢；支持停止生成（断流后已生成内容仍会保存）
- **真实健康检查**：PG / Qdrant / LLM / Embedding / 沙箱逐项探活，降级可见
- **审计与配额**：登录、对话、工具调用、仓库导入/删除全量审计；用量与配额在设置页实时可见

### 两层记忆
- 会话记忆：持久化消息 + 标题自动生成
- 长期记忆：对话中抽取用户偏好/事实，MD5 + 向量相似度去重（阈值 0.92），重要性访问加权、闲置衰减、TTL 过期清理（小时级维护循环）

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · 自研 Agent 循环（无 LangChain 黑盒） |
| 前端 | React 18 · TypeScript · Vite · TailwindCSS · Zustand · react-markdown + highlight.js |
| 存储 | PostgreSQL 16（业务/会话/记忆/全文检索）· Qdrant（稠密向量） |
| LLM | 阿里云百炼 `qwen3.8-max`（OpenAI 兼容，默认单通道；可配置 deepseek/longcat 降级链） |
| 沙箱 | Docker（一次性容器，强隔离） |
| 部署 | Docker Compose（app + postgres + qdrant + 沙箱镜像）· 可选 Caddy 自动 HTTPS |

## 快速开始

### 方式一：Docker Compose 一键部署（推荐）

```bash
cp .env.docker.example .env   # 填入 LLM API Key，修改 SECRET_KEY 与两个账号密码
docker compose up -d --build  # 构建并启动全部服务
# 访问 http://<服务器IP>:8000
```

首次启动自动完成幂等初始化：建库建表、创建 Qdrant collection、生成 admin/demo 账号。

启用 HTTPS（有域名时）：`cp Caddyfile.example Caddyfile` 改成你的域名，然后 `docker compose --profile https up -d`，并在 `.env` 中设 `COOKIE_SECURE=true`。

### 方式二：本地开发

```bash
# 后端（本机进程，热重载）
cd backend
pip install -r requirements.txt
cp .env.example .env          # 配置 PG/Qdrant 地址与 LLM Key
python run.py                 # http://localhost:8000

# 前端（Vite 开发服务器，代理到 8000）
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

说明：
- 沙箱工具需要本机 Docker 在运行；未运行时设置页会如实显示「沙箱不可用」，其余功能不受影响
- 首次启动设 `AUTO_INIT_DB=true` 自动建表，或手动执行 `python -m app.db.init_db`

## 配置项（.env 关键项）

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` | LLM Key（至少一个；DashScope 同时提供 embedding） |
| `DASHSCOPE_MODEL` | 阿里云百炼模型名（默认 `qwen3.8-max`） |
| `LLM_MODEL_PRIORITY` | 模型通道顺序，默认 `dashscope`；可写 `dashscope,deepseek,longcat` 启用降级链 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理员账号（启动时注入/更新） |
| `DEMO_USERNAME` / `DEMO_PASSWORD` | 演示账号（可公开给面试官/朋友使用） |
| `SECRET_KEY` | JWT 签名密钥（≥32 位随机串） |
| `COOKIE_SECURE` | 启用 HTTPS 后设为 true |
| `DEMO_DAILY_TOKENS` / `DEMO_HOURLY_MESSAGES` / `DEMO_SANDBOX_DAILY` | 演示账号限额（0 = 不限） |
| `SANDBOX_ENABLED` | 沙箱总开关 |
| `MAX_UPLOAD_MB` / `MAX_REPO_FILES` | 仓库导入上限 |

## API 概览

| 端点 | 说明 |
|---|---|
| `POST /api/v1/auth/login` `logout` `GET me` | 登录 / 登出 / 当前用户 |
| `GET/POST /api/v1/chat/sessions` | 会话列表 / 新建 |
| `GET /api/v1/chat/sessions/{id}/messages` | 历史消息 |
| `POST /api/v1/chat/message` | 对话（SSE：`meta/retrieval/token/tool_call/tool_result/usage/error/done`） |
| `POST /api/v1/repos/upload` / `POST /api/v1/repos/git` | 导入仓库（ZIP / 公开 Git URL） |
| `GET /api/v1/repos` `/{id}` `/{id}/tree` `/{id}/file` `/{id}/search` | 仓库列表 / 详情 / 文件树 / 文件内容 / 仓库内搜索 |
| `GET /api/v1/status/health` / `usage` | 依赖探活 / 用量配额 |

## 项目结构

```
backend/app/
├── api/v1/            auth · chat · repos · status
├── core/
│   ├── agent/loop.py  Agent 主循环（检索→工具轮次→持久化）
│   ├── rag/           双路召回 + RRF（dense / keyword）
│   ├── indexing/      仓库索引：walker / symbols / chunker / pipeline
│   ├── memory/        会话 + 长期事实（去重/衰减/清理）
│   ├── tools/         6 个工具 + 注册表（校验/容错/审计）
│   ├── sandbox/       Docker 一次性容器执行器
│   ├── harness/       超时 / 重试 / 熔断
│   ├── security/      认证 / 限流配额 / 风险规则 / 审计
│   └── llm/           多厂商降级链 + 工具流式（真实 token 统计）
├── db/                PostgreSQL 连接 · Qdrant · 幂等初始化
└── models/            Pydantic 模型
frontend/src/
├── views/             登录 · 对话 · 工作区 · 设置
├── components/        消息/工具卡片/Markdown/文件树/代码查看器…
├── stores/            auth · chat · repos（Zustand）
└── lib/               API 客户端 · SSE 解析（含中断与错误处理）
docs/DESIGN.md         架构设计文档（数据模型/API/安全/部署）
```

## 测试

```bash
cd backend && python -m pytest tests/ -q
```

- 单元测试（无需数据库）：认证/限流、Agent 循环事件协议与停止语义、6 个工具、索引与分块、ZIP 安全、SSRF 防护、熔断重试
- 集成测试（标记 `integration`，连不上 PG/Qdrant 时自动跳过）：建库建表幂等性、账号种子

## 安全说明

- 代码执行只在锁定沙箱中进行；Docker 不可用时工具不可用，不存在宿主机执行路径
- `fetch_url` 有 SSRF 防护：仅公网 http(s)、逐跳校验重定向、拒绝内网地址、限制响应大小与类型
- ZIP 导入有路径穿越防护、文件数与大小上限；Git 仅支持公开仓库浅克隆
- 部署暴露公网前请务必：改 `SECRET_KEY`、改两个账号密码、按需收紧 `CORS_ORIGINS`

## License

个人项目，供学习与演示使用。