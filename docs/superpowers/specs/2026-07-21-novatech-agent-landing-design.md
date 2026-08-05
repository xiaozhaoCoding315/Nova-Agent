# NovaTech Agent 落地完善设计

> 创建日期: 2026-07-21
> 状态: 草稿
> 范围: 6大亮点功能对齐 + 短板补齐

## 1. 背景与审计结论

NovaTech Agent 代码量充足（后端135测试通过、前端TS编译通过），数据库有真实数据（PG 174文档块、Qdrant 174向量、Neo4j 41实体）。

**审计发现**：核心链路（检索→LLM→回答）真实能跑通，但6大亮点中有4个存在"假对齐"——代码文件存在但功能不完整或未验证。

### 6大亮点对齐状态

| 亮点 | 对齐状态 | 核心差距 |
|------|---------|---------|
| 1 混合图RAG检索 | ✅ 已对齐 | 缺集成测试锁定 |
| 2 RAG全链路评测 | ⚠️ 假对齐 | RAGAS分数0.1-0.2异常低，疑似空壳 |
| 3 四层分层记忆 | ⚠️ 缺两层 | 图记忆、运行时状态未联动 |
| 4 动态DAG ReAct | ⚠️ 缺竞速 | Race策略未集成到DAG执行 |
| 5 Harness容错引擎 | ✅ 已对齐 | 缺集成测试锁定 |
| 6 Docker沙箱安全 | ⚠️ 部分缺失 | 审计日志未端到端验证 |

## 2. 完善优先级

| 优先级 | 改善点 | 依赖 |
|--------|--------|------|
| P0 | 数据库初始化脚本 `init_db.py` | 无 |
| P1 | 亮点2 — RAGAS评测修复与校准 | P0 |
| P2 | 亮点3 — 补全图记忆 + 运行时状态 | P0 |
| P3 | 亮点4 — DAG集成Race竞速 | P0 |
| P4 | 亮点6 — 审计日志端到端验证 | P0 |
| P5 | 集成测试套件（每亮点一条） | P1-P4 |

## 3. 各亮点完善设计

### P0: 数据库初始化 (`backend/app/db/init_db.py`)

**目标**：一键可复现地创建所有数据库结构，幂等可重跑。

**PostgreSQL**:
- `documents` 表：id UUID, content text, source varchar, metadata jsonb, search_vector tsvector, created_at
- `search_vector` 自动更新触发器（中文使用 `simple` 配置 + jieba 分词辅助）
- GIN 索引 on search_vector
- `agent_facts` 表：id, session_id, fact, category, importance, created_at, last_accessed
- `eval_queries` / `eval_results` / `eval_corpora` 评测数据表

**Qdrant**:
- `novatech_docs` collection：vectors=1024, distance=Cosine
- 幂等：已存在则跳过

**Neo4j**:
- `Entity` 节点：name 约束、entityIndex 全文索引
- 幂等：`CREATE CONSTRAINT IF NOT EXISTS`

**CLI**:
```bash
python -m app.db.init_db          # 初始化全部
python -m app.db.init_db --check  # 只检查连通性
```

### P1: RAGAS评测修复

**问题**：当前 faithfulness=0.1, answer_relevancy=0.2, context_precision=0.1, context_recall=0.1，分数异常低。

**诊断步骤**：
1. 检查 `app/core/evaluation/ragas.py` 的评测 prompt 是否合理
2. 检查是否使用了正确的评测 LLM（应使用强模型评判，非 LongCat 自身）
3. 检查指标计算逻辑（LLM 输出解析是否正确）

**修复方向**：
- 若 RAGAS 实现有 bug → 修复 prompt + 解析逻辑
- 若 RAGAS 依赖的评判模型不可用 → 降级到自实现简化版指标（基于检索重叠度）
- 确保评测结果能合理区分好/坏回答

**验证**：用已知好/坏回答对评测系统做 sanity check。

### P2: 四层记忆补全

**当前**：短期会话(PG+内存) + 长期语义(PG+TTL) ✅ | 图记忆 ⚠️ | 运行时状态 ⚠️

**图记忆补全** (`app/core/memory/graph_memory.py` → 接入对话流):
- 事实提取后写入 Neo4j（Entity 节点 + RELATES 关系）
- 增强现有 `graph_search`：检索时不仅匹配种子实体，还扩散到用户历史关联的实体子图
- 对话中提及的历史实体自动关联（与已提取的 agent_facts 联动）

**运行时状态记忆补全**:
- 复杂任务执行中，DAG 节点状态实时写入状态机
- 任务中断后可从断点恢复（状态持久化到 PG）
- 与 chat.py 联动：长任务执行时保留运行上下文

**四层联动验证**：一次对话中，短期上下文 → 长期事实召回 → 图记忆关联 → 运行时状态保持，四层全部参与。

### P3: DAG集成Race竞速

**当前**：`race.py` 有 RaceStrategy 实现，但 DAG 执行未使用。

**集成方案**:
- DAG 中无依赖的并行节点默认使用 RaceStrategy 竞速
- 多数据源/多模型并发时取最快有效结果
- 竞速失败时 fallback 到次快 provider

**验证**：同一任务用 Race 模式 vs 普通模式执行，对比延迟和成功率。

### P4: 审计日志端到端验证

**目标**：安全事件全链路可追溯。

**验证场景**:
1. 用户输入含危险代码 → security 拦截 → 审计日志记录 block 事件
2. 沙箱执行代码 → 审计日志记录 execution 事件
3. 查询审计日志 `/audit/log` → 返回完整事件链

**修复**：确保 `app/core/security/audit.py` 在所有安全决策点被调用。

### P5: 集成测试套件

**位置**：`backend/tests/integration/`

**每个亮点一条真实连通测试**（连接真实数据库，不 mock）:
- `test_integration_retrieval.py` — 三路检索 + RRF
- `test_integration_evaluation.py` — RAGAS 评测
- `test_integration_memory.py` — 四层记忆联动
- `test_integration_dag.py` — DAG 竞速执行
- `test_integration_sandbox.py` — 沙箱 + 审计

**fixture**：`tests/conftest.py` 提供真实 DB 连接 + 测试数据准备。

## 4. 技术约束

- 数据库：192.168.150.128（Qdrant:6333, PG:5432, Neo4j:7687）
- LLM 降级链：LongCat → DeepSeek → DashScope
- 本机无 Docker → 沙箱使用 direct fallback 模式
- Windows 环境 → 所有文件 IO 使用 UTF-8 编码，修复 GBK 问题
- Python 3.12 + async/await

## 5. 不在本次范围

- 前端 UI 重构（已能正常工作）
- 多智能体协作（设计文档中的远期目标）
- 生产部署/Dockerfile 优化
- 性能压测

## 6. 验收标准

- [ ] `python -m app.db.init_db` 一键初始化成功
- [ ] RAGAS 评测分数合理（好回答 > 0.6，坏回答 < 0.3）
- [ ] 四层记忆在一次对话中全部参与
- [ ] DAG Race 竞速模式延迟低于普通模式
- [ ] 审计日志完整记录安全事件链
- [ ] 5条集成测试全部通过
