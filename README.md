# Nova Agent — AI 全栈技术助手智能体

面向程序员的 AI Agent 系统，自研 DAG 调度引擎与四层记忆架构，打通「精准检索 → 持久记忆 → 可靠执行 → 安全运行」完整链路。

## 功能亮点

### 混合图增强 RAG 检索管线
三路并行召回——**Qdrant 稠密向量** + **PostgreSQL BM25**（自研 jieba 中文分词）+ **Neo4j 知识图谱**多跳扩展；RRF (k=10) 融合多路结果，ILIKE 兜底解决中文分词边界问题。多路检索互相补充，单路故障不中断整体请求。

### 四层分层记忆架构
短期会话记忆 → 长期语义记忆（PostgreSQL，TTL 30~365 天）→ 图谱记忆（Neo4j 实体关系）→ DAG 运行时断点记忆。MD5 + Embedding 双重去重，记忆权重动态衰减模拟遗忘曲线，跨会话持久存储用户历史与偏好。

### Agent Skill 工具集（Function-Calling）
可扩展 Skill 插件机制：`ToolRegistry` 统一注册与参数校验（JSON Schema），LLM 基于 Function-Calling 自主选择工具，SSE 实时推送 `tool_call` / `tool_result` 事件，前端展示工具调用卡片（工具名 / 入参 / 结果 / 耗时）。内置三个工具——**计算器**（AST 白名单安全求值，杜绝 eval 注入）、**数据库查询**（只读 SELECT、表白名单、强制 LIMIT）、**文档解析**（按名称/关键词定位知识库文档并返回分块预览）。工具执行全程纳入 Harness 容错（30s 超时、指数退避重试、熔断降级），单工具故障不影响对话主链路；Agent 循环最多 4 轮防失控，工具调用全量写入审计日志。

### 自研 DAG ReAct 执行引擎
零第三方框架依赖，自研 DAGWorkflow 调度核心。支持 Kahn 拓扑排序、循环检测、异步并行执行、节点重试与异常传递。内置多 LLM 厂商竞速调度与任务自动分解器，状态机完整追踪节点生命周期。

### Harness 容错引擎 + Docker 安全沙箱
分级超时控制（LLM 60s / 检索 10s / 工具 30s / DB 5s），指数退避重试（最多 3 次），熔断降级（5 次失败断路，60s 后半开）。Docker 容器强隔离（禁用网络、只读文件、丢弃全部权限），搭配风险正则校验与全量审计日志。

### RAG 评测体系与可视化前端
检索指标：Recall@K、MRR、NDCG@10；生成层基于 RAGAS 做 LLM 多维度评测。前端 React18 + TypeScript + TailwindCSS，SSE 流式输出，六面板 Dashboard 覆盖对话、知识库、记忆图谱、评测、DAG 流程图、系统监控。

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | Python · FastAPI |
| **前端框架** | React 18 · TypeScript · TailwindCSS · Vite |
| **向量数据库** | Qdrant · PostgreSQL + pgvector |
| **图数据库** | Neo4j |
| **LLM 接入** | OpenAI 兼容接口 · 多厂商竞速调度 |
| **容器化** | Docker |
| **状态管理** | Zustand |
| **3D 可视化** | Three.js · React Three Fiber |

## 项目结构

```
nova-agent/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST API 路由
│   │   │   ├── chat.py      # 对话接口
│   │   │   ├── knowledge.py # 知识库管理
│   │   │   ├── memory.py    # 记忆查询
│   │   │   ├── graph.py     # 知识图谱
│   │   │   ├── evaluation.py# 评测接口
│   │   │   ├── harness.py   # 容错控制
│   │   │   ├── sandbox.py   # 沙箱执行
│   │   │   ├── tasks.py     # DAG 任务
│   │   │   └── ...
│   │   ├── core/
│   │   │   ├── agent/       # DAG 引擎 · 任务分解 · 竞速调度（状态三件套：DAGNode.status 节点态 / TaskStateMachine 校验状态机 / TaskStateManager 持久化存储 Layer 4）
│   │   │   ├── rag/         # 稠密/关键词/图谱检索 · RRF 融合
│   │   │   ├── memory/      # 四层记忆 · 去重 · 衰减 · 上下文组装
│   │   │   ├── harness/     # 超时 · 重试 · 熔断
│   │   │   ├── sandbox/     # Docker 容器沙箱
│   │   │   ├── security/    # 风险校验 · 审计日志
│   │   │   ├── evaluation/  # RAGAS 评测 · 数据集管理
│   │   │   ├── llm/         # LLM 工厂 · 降级策略
│   │   │   └── embedding/   # 向量嵌入
│   │   ├── db/              # PostgreSQL · Neo4j 连接
│   │   ├── models/          # 领域模型 · Pydantic Schema
│   │   └── utils/           # 中文分词 · 文本分割 · 实体抽取
│   ├── tests/               # 单元测试 + 集成测试
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── chat/        # 对话窗口 · 消息气泡 · 输入框
│   │   │   ├── knowledge/   # 知识库面板 · 上传
│   │   │   ├── memory/      # 记忆面板 · 图谱画布 · 时间线
│   │   │   ├── eval/        # 评测面板 · 指标条
│   │   │   ├── tasks/       # DAG 画布 · 任务创建
│   │   │   ├── admin/       # 管理面板
│   │   │   ├── layout/      # 布局组件
│   │   │   └── particles/   # 粒子特效
│   │   ├── hooks/           # SSE 流式订阅
│   │   ├── services/        # API · SSE 客户端
│   │   ├── stores/          # Zustand 状态管理
│   │   └── styles/          # 全局样式 · 赛博朋克主题
│   └── package.json
└── docs/                    # 设计文档
```

## 快速开始

### 前置条件

- Docker + Docker Compose（一键部署，推荐）
- 开发模式另需：Python 3.12+、Node.js 18+、PostgreSQL/pgvector、Qdrant、Neo4j 实例

### Docker Compose 一键部署（推荐）

全套服务（PostgreSQL+pgvector / Qdrant / Neo4j / backend+前端）一条命令拉起：

```bash
cp .env.docker.example .env   # 填入你的 LLM API Key（DeepSeek/DashScope 至少一个）
docker compose up -d --build  # 构建并启动全部服务
# 访问 http://localhost:8000
```

首次启动自动完成幂等初始化：建表、创建 Qdrant collection、Neo4j 约束。数据库已有独立实例时，可改用 `docker-compose.vm.yml`（只跑 backend，`host.docker.internal` 直连宿主机数据库）。

> 说明：Docker 沙箱代码执行功能需要容器内访问 Docker 运行时，compose 部署下该功能自动降级并在 `/sandbox/status` 如实上报，其余功能不受影响。

### 开发模式（本机调试）

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # 编辑 .env 填入 API Key 与数据库连接
python run.py                 # 默认 dev 模式，访问 http://localhost:8000/docs
```

前端：

```bash
cd frontend
npm install
npm run dev                   # Vite 开发服务器 http://localhost:5173
npm run build                 # 生产构建到 dist/
```

## API 概览

| 端点 | 说明 |
|------|------|
| `GET /api/v1/health` | 健康检查 |
| `POST /api/v1/chat` | 对话（SSE 流式） |
| `POST /api/v1/knowledge/upload` | 知识库上传 |
| `GET /api/v1/knowledge/search` | 知识检索 |
| `GET /api/v1/memory/session` | 会话记忆 |
| `GET /api/v1/memory/long-term` | 长期记忆 |
| `GET /api/v1/graph/entities` | 图谱实体 |
| `POST /api/v1/tasks` | 创建 DAG 任务 |
| `GET /api/v1/tasks/{id}` | 任务状态 |
| `POST /api/v1/evaluation/run` | 运行评测 |
| `POST /api/v1/sandbox/execute` | 沙箱代码执行 |
