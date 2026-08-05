# NovaTech Agent MVP 设计文档

> 创建日期: 2026-07-10
> 状态: 已确认
> 范围: MVP — 对话 + 检索核心

## 1. 概述

NovaTech Agent 是面向程序员的全链路技术学习与知识沉淀AI智能体。本MVP聚焦最小可用版本：**对话交互 + 三路召回检索 + AI生成回答**，在1-2周内交付可运行的核心链路。

## 2. 架构设计

### 2.1 系统分层

```
┌─────────────────────────────────────────────────┐
│              前端 (React + TypeScript)            │
│         Vite + TailwindCSS + Three.js            │
│         赛博朋克粒子动效 + 左右分栏布局             │
├─────────────────────────────────────────────────┤
│              通信层 (HTTP + SSE)                   │
├─────────────────────────────────────────────────┤
│              后端 (Python + FastAPI)               │
│  ┌──────────┬──────────┬──────────┬────────────┐ │
│  │ 对话管理  │ 检索引擎  │ AI适配层  │ 记忆管理    │ │
│  │ Router   │ Router   │ Router   │ Router     │ │
│  └──────────┴──────────┴──────────┴────────────┘ │
├─────────────────────────────────────────────────┤
│              数据层                                │
│  ┌─────────┐ ┌──────────────┐ ┌───────────────┐  │
│  │ Qdrant  │ │ PostgreSQL   │ │   Neo4j       │  │
│  │(向量检索)│ │(关键词+BM25) │ │(知识图谱)      │  │
│  │:6333    │ │:5432         │ │:7687          │  │
│  └─────────┘ └──────────────┘ └───────────────┘  │
└─────────────────────────────────────────────────┘
         ↓
  [Longcat2.0 → DeepSeek → DashScope (降级链)]
```

### 2.2 AI模型适配策略

采用**优先级降级链**：
1. 首先尝试 Longcat2.0
2. 失败则降级到 DeepSeek (DEEPSEEK_API_KEY)
3. 再降级到通义千问 (DASHSCOPE_API_KEY)
4. 全部失败则报错提示

通过环境变量 `LLM_MODEL_PRIORITY=longcat,deepseek,dashscope` 灵活配置。

### 2.3 检索三路召回流程

```
用户提问 → ① Dense向量召回(Qdrant, Top-10)
         → ② BM25关键词召回(PostgreSQL FTS, Top-10)   ──→ 三路并行异步执行
         → ③ Graph图检索(Neo4j多跳扩散, Top-10)
         → RRF融合排序(k=60) → Top-5 上下文 → 喂给LLM生成回答
```

## 3. 技术选型

### 3.1 前端

| 模块 | 技术 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 用户指定 |
| 构建 | Vite 5 | 极速HMR，开发体验好 |
| 样式 | TailwindCSS 3 | 原子化CSS，快速构建科技感UI |
| 动效 | Framer Motion | 声明式动画，React原生集成 |
| 3D粒子 | Three.js + @react-three/fiber | 赛博朋克粒子背景 |
| 状态管理 | Zustand | 轻量，零boilerplate |
| API请求 | Axios + React Query | 请求缓存+自动重试 |
| 图标 | Lucide React | 现代线性图标 |

### 3.2 后端

| 模块 | 技术 | 理由 |
|------|------|------|
| 框架 | Python + FastAPI | 用户指定，异步原生 |
| 检索向量 | Qdrant | 轻量高性能向量数据库 |
| 检索关键词 | PostgreSQL + pgvector/FTS | 替ES，用户自有服务 |
| 检索图谱 | Neo4j | 知识图谱引擎 |
| AI适配 | OpenAI SDK (兼容接口) | 降级链，兼容多模型 |
| 配置管理 | pydantic-settings | 环境变量驱动 |
| 日志 | structlog | 结构化日志 |

### 3.3 服务地址

| 服务 | 地址 | 备注 |
|------|------|------|
| Qdrant | 192.168.150.128:6333 | 向量检索 |
| PostgreSQL | 192.168.150.128:5432 | 关键词检索+BM25 |
| Neo4j | 192.168.150.128:7687 | 知识图谱 |

- 用户名和密码后续用户提供
- 用户负责启动和验证服务可用性

## 4. 项目目录结构

### 4.1 前端 (frontend/)

```
frontend/
├── src/
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── MainContent.tsx
│   │   │   └── Header.tsx
│   │   ├── chat/
│   │   │   ├── ChatWindow.tsx
│   │   │   ├── MessageBubble.tsx
│   │   │   ├── InputBox.tsx
│   │   │   └── TypingIndicator.tsx
│   │   ├── particles/
│   │   │   ├── ParticleField.tsx
│   │   │   └── GlowOrb.tsx
│   │   └── knowledge/
│   │       ├── KnowledgePanel.tsx
│   │       └── MemoryPanel.tsx
│   ├── hooks/
│   │   ├── useChat.ts
│   │   ├── useSSE.ts
│   │   └── useTheme.ts
│   ├── services/
│   │   ├── api.ts
│   │   └── sse.ts
│   ├── stores/
│   │   ├── chatStore.ts
│   │   └── appStore.ts
│   ├── styles/
│   │   ├── globals.css
│   │   └── cyberpunk.css
│   ├── types/
│   │   └── index.ts
│   ├── App.tsx
│   └── main.tsx
├── public/
├── index.html
├── tailwind.config.ts
├── tsconfig.json
├── vite.config.ts
└── package.json
```

### 4.2 后端 (backend/)

```
backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── api/v1/
│   │   ├── router.py
│   │   ├── chat.py
│   │   ├── knowledge.py
│   │   └── memory.py
│   ├── core/
│   │   ├── rag/
│   │   │   ├── retriever.py
│   │   │   ├── dense.py
│   │   │   ├── keyword.py
│   │   │   ├── graph.py
│   │   │   └── rrf.py
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   ├── longcat.py
│   │   │   ├── deepseek.py
│   │   │   ├── dashscope.py
│   │   │   └── fallback.py
│   │   ├── memory/
│   │   │   ├── session.py
│   │   │   └── semantic.py
│   │   └── embedding/
│   │       └── embedder.py
│   ├── models/
│   │   ├── schemas.py
│   │   └── domain.py
│   ├── db/
│   │   ├── qdrant.py
│   │   ├── postgres.py
│   │   └── neo4j.py
│   └── utils/
│       ├── logger.py
│       └── text_splitter.py
├── tests/
├── data/sample_docs/
├── requirements.txt
├── Dockerfile
└── .env.example
```

### 4.3 根目录

```
Nova Agent/
├── frontend/
├── backend/
├── docker-compose.yml
├── .gitignore
└── README.md
```

## 5. 核心API设计

### 5.1 接口列表

```
POST   /api/v1/chat/message           # 发送对话消息 (SSE流)
GET    /api/v1/chat/history           # 获取对话历史
DELETE /api/v1/chat/session/{id}      # 清除会话
POST   /api/v1/knowledge/upload       # 上传技术文档
GET    /api/v1/knowledge/list         # 知识库文档列表
DELETE /api/v1/knowledge/{doc_id}     # 删除文档
GET    /api/v1/memory/summary         # 获取用户画像摘要
GET    /api/v1/health                 # 健康检查
```

### 5.2 SSE聊天流式协议

```
客户端                                FastAPI后端
   │                                      │
   │──POST /chat/message {question}──────→│
   │                                      │──→ 三路并行检索
   │                                      │──→ RRF融合排序
   │                                      │──→ 组装Prompt
   │                                      │──→ 调用LLM流式
   │←──SSE: {type:"retrieval", data:[..]}─│
   │←──SSE: {type:"token", content:"..."}──│
   │←──SSE: {type:"done"}─────────────────│
```

### 5.3 请求/响应格式

**请求：**
```json
{
  "message": "FastAPI的中间件怎么用？",
  "session_id": "optional-session-id",
  "stream": true
}
```

**SSE响应事件：**
```json
// 检索结果
{"type": "retrieval", "data": [{"source": "fastapi-doc.md", "score": 0.92, "chunk": "..."}]}
// 流式token
{"type": "token", "content": "在FastAPI中..."}
// 完成
{"type": "done", "session_id": "xxx", "retrieval_time_ms": 234, "tokens": 156}
```

## 6. 视觉系统设计

### 6.1 色彩体系

| 用途 | 色值 | 名称 |
|------|------|------|
| 背景 | #0a0a0f | 深黑蓝 |
| 主色 | #00f0f0 | 霓虹青 |
| 辅色 | #ff006e | 霓虹粉 |
| 强调 | #8b5cf6 | 赛博紫 |
| 文字 | #e0e0e0 | 亮灰 |

### 6.2 动效体系

- 粒子背景: Three.js 流动粒子网格
- 输入框: 霓虹光晕脉冲 (0.5s循环)
- 消息气泡: 滑入+渐显 (Framer Motion)
- 打字机: 逐字输出 + 光标闪烁
- Sidebar: 滑入+模糊玻璃 (backdrop-blur)
- 加载状态: 霓虹Dot脉冲

### 6.3 布局结构

```
┌────────────┬─────────────────────────────────────────────┐
│  Header    │  (在线状态 / 设置)                           │
├────────────┼─────────────────────────────────────────────┤
│  Sidebar   │  主内容区 (粒子背景)                          │
│  ───────── │                                             │
│  💬 对话    │  [消息气泡区域 - 滚动]                        │
│  📚 知识库  │  ┌─────────────────────────────────┐        │
│  🧠 记忆    │  │ 🤖 系统/AI回答 (打字机动效)      │        │
│  🔧 任务    │  └─────────────────────────────────┘        │
│  📊 评测    │  ┌─────────────────────────────────┐        │
│            │  │ 👤 用户提问                      │        │
│            │  └─────────────────────────────────┘        │
│  240px宽   │                                             │
│  毛玻璃边框 │  ╔═══════════════════════════════════════╗  │
│            │  ║ 输入你的技术问题...              [📎] ║  │
│            │  ╚═══════════════════════════════════════╝  │
└────────────┴─────────────────────────────────────────────┘
```

## 7. 环境变量配置

```env
# LLM模型降级链
LLM_MODEL_PRIORITY=longcat,deepseek,dashscope
LONGCAT_API_KEY=xxx
LONGCAT_BASE_URL=xxx
LONGCAT_MODEL=LongCat-2.0
DEEPSEEK_API_KEY=已配置于系统环境
DASHSCOPE_API_KEY=已配置于系统环境

# PostgreSQL
POSTGRES_HOST=192.168.150.128
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=待用户提供
POSTGRES_DB=novatech

# Qdrant
QDRANT_HOST=192.168.150.128
QDRANT_PORT=6333
QDRANT_API_KEY=待用户提供

# Neo4j
NEO4J_HOST=192.168.150.128
NEO4J_PORT=7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=待用户提供

# 嵌入模型
EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL=text-embedding-v3

# 应用
DEBUG=true
LOG_LEVEL=INFO
SECRET_KEY=change-me-in-production
CORS_ORIGINS=http://localhost:5173
```

## 8. 文档上传处理流水线

```
上传Markdown → 清洗(去广告/空行/无效标签)
            → 智能Chunk切片(代码块/标题为界)
            → 向量化(Embedding模型)
            → 存入Qdrant(向量) + PostgreSQL(原文+FTS索引)
            → 实体抽取(框架/函数/报错) → Neo4j(图谱构建)
```

## 9. MVP会话记忆（简化版）

- 会话内: 完整对话上下文(内存存储，服务端可控)
- 会话间: 用户提问摘要 + 关键事实 → 存入PostgreSQL
- 后续迭代: 接入Neo4j Memory Graph实现图记忆

## 10. 实施路线图

| 步骤 | 内容 | 预计时间 |
|------|------|---------|
| 1 | 项目初始化(前后端骨架+docker-compose) | 0.5天 |
| 2 | 后端核心(FastAPI + 三路检索引擎 + AI适配) | 2天 |
| 3 | 前端布局(分栏+路由+状态管理) | 1天 |
| 4 | 前端对话UI(消息气泡+输入框+流式渲染) | 1.5天 |
| 5 | 赛博朋克视觉(Tailwind主题+粒子背景+动效) | 1天 |
| 6 | 联调测试(端到端打通+文档上传测试) | 1天 |
| **合计** | | **~7天** |

## 11. 不在MVP范围内

以下功能留待后续迭代：
- DAG动态工作流 (核心亮点4)
- Harness容错引擎 (核心亮点5)
- Docker沙箱安全 (核心亮点6)
- RAG全链路评测平台 (核心亮点2)
- 四层分层记忆完整版 (核心亮点3中的图记忆)
- 工具风险分级
- 任务规划与管理
- 多智能体协作
