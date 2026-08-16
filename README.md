# Nova Agent — AI 全栈技术助手智能体

面向程序员的 AI Agent 系统，自研 DAG 调度引擎与四层记忆架构，打通「精准检索 → 持久记忆 → 可靠执行 → 安全运行」完整链路。

## 功能亮点

### 混合图增强 RAG 检索管线
三路并行召回——**Qdrant 稠密向量** + **PostgreSQL BM25**（自研 jieba 中文分词）+ **Neo4j 知识图谱**多跳扩展；RRF (k=10) 融合多路结果，ILIKE 兜底解决中文分词边界问题。多路检索互相补充，单路故障不中断整体请求。

### 四层分层记忆架构
短期会话记忆 → 长期语义记忆（PostgreSQL，TTL 30~365 天）→ 图谱记忆（Neo4j 实体关系）→ DAG 运行时断点记忆。MD5 + Embedding 双重去重，记忆权重动态衰减模拟遗忘曲线，跨会话持久存储用户历史与偏好。

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

- Python 3.12+
- Node.js 18+
- Docker（沙箱功能需要）
- PostgreSQL + pgvector 扩展
- Qdrant
- Neo4j

### 后端

```bash
cd backend

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key 和数据库连接信息

# 启动
python run.py
```

### 前端

```bash
cd frontend

# 安装依赖
npm install

# 开发模式启动
npm run dev

# 生产构建
npm run build
```

### Docker

```bash
cd backend
docker build -t nova-agent .
docker run -p 8000:8000 --env-file .env nova-agent
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
