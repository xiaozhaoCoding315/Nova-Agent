# NovaTech RAG 架构说明

本文档描述 NovaTech Agent 的检索增强生成（RAG）架构设计。

## 概述

NovaTech Agent 是一个新型动态调度技术记忆智能体，采用混合检索策略结合 LLM 回退链，为技术领域问题提供精准回答。

## 架构组件

```
用户提问
    │
    ▼
┌─────────────────────────────────┐
│        RAG Router               │
│   (查询分析与路由决策)           │
└──────┬──────────┬───────────────┘
       │          │
       ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│  Dense   │ │ Keyword  │ │  Graph   │
│ Retrieval│ │ Retrieval│ │ Retrieval│
│ (向量)   │ │ (BM25)   │ │ (Neo4j)  │
└────┬─────┘ └────┬─────┘ └────┬─────┘
     │             │            │
     ▼             ▼            ▼
┌─────────────────────────────────┐
│     RRF Fusion (倒数排名融合)    │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     LLM Fallback Chain          │
│  LongCat → DeepSeek → DashScope │
└────────────────┬────────────────┘
                 │
                 ▼
          SSE 流式响应
```

## 三路检索

### 1. 密集检索 (Dense Retrieval)

- **存储**：Qdrant 向量数据库
- **嵌入模型**：DashScope text-embedding-v3 / OpenAI 兼容
- **适用**：语义相似、概念性问题
- **分数类型**：余弦相似度

```python
# 示例：语义搜索
results = dense_search("什么是依赖注入", top_k=5)
```

### 2. 关键词检索 (Keyword Retrieval)

- **存储**：PostgreSQL + 全文搜索
- **算法**：BM25 / TF-IDF 变体
- **适用**：精确术语匹配、API 名称、错误代码
- **分数类型**：BM25 相关性分数

```python
# 示例：关键词搜索
results = keyword_search("FastAPI Depends Depends", top_k=5)
```

### 3. 图检索 (Graph Retrieval)

- **存储**：Neo4j 图数据库
- **算法**：基于关系的图遍历
- **适用**：知识图谱查询、实体关系、依赖链
- **分数类型**：图中心性 / 路径权重

```python
# 示例：图关系搜索
results = graph_search("FastAPI 依赖的组件", top_k=5)
```

## RRF 融合算法

Reciprocal Rank Fusion (倒数排名融合) 合并多路检索结果：

```
RRF_score(d) = Σ 1/(k + rank_i(d))
```

其中 `k=60` 为平滑常数，`rank_i(d)` 为文档在第 i 个列表中的排名。

核心优势：
- 无需分数归一化
- 跨列表的互补信号被保留
- 在多个列表中排名靠前的文档获得更高分数

## LLM 回退链

当主模型失败时自动回退：

```
优先顺序（可配置）：
1. LongCat-2.0（本地/自托管）
2. DeepSeek（推理增强）
3. DashScope（通义千问，兜底）
```

配置示例：
```env
LLM_MODEL_PRIORITY=longcat,deepseek,dashscope
```

每个模型提供独立的 API key 和 base_url，通过统一的 OpenAI 兼容接口调用。

## 会话记忆 (Memory)

短期记忆：当前会话的对话历史
长期记忆：跨会话的知识积累（后续版本实现）

## 知识管理

文档上传 → 分块 (Chunking) → 嵌入 (Embedding) → 索引 (Qdrant + Postgres + Neo4j)

建议分块策略：
- 代码块：按函数/类边界
- 文档：按标题 + 固定长度重叠
- Markdown：按 `##` 标题分割

## SSE 流式协议

聊天响应使用 Server-Sent Events 协议：

```
event: retrieval
data: {"type":"retrieval","data":[{...}]}

event: token
data: {"type":"token","content":"FastAPI"}

event: done
data: {"type":"done","session_id":"...","retrieval_time_ms":45.2,"tokens":128}
```

三个事件按顺序发送：先发送检索结果，再流式发送 LLM token，最后发送完成信息。

## 部署架构

```
docker-compose
├── novatech-backend  (FastAPI, :8000)
├── novatech-frontend (Vite/React, :5173)
├── qdrant            (:6333)
├── postgres          (:5432)
└── neo4j             (:7687, :7474)
```

所有外部存储默认指向 `192.168.150.128`，可通过环境变量或 `.env` 文件覆盖。

## 路线图

- [x] FastAPI 骨架与配置
- [x] RRF 融合算法
- [x] 三路检索（Dense / Keyword / Graph）
- [x] 嵌入模块（DashScope / OpenAI 兼容）
- [x] LLM 回退链
- [x] SSE 流式聊天端点
- [x] 前端赛博朋克 UI 与 Three.js 粒子背景
- [x] 知识库与会话记忆存根路由
- [ ] 真实向量索引与嵌入流水线
- [ ] WebSocket 实时通知
- [ ] 多轮对话上下文管理
- [ ] 用户认证与多租户
