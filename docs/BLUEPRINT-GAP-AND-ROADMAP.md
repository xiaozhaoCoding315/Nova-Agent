# Nova Agent ×《全栈编程 Agent 设计方案》差距分析与演进路线

> 扫描日期：2026-10-23  
> 代码基线：`refactor/v2-dev-assistant`  
> 扫描范围：`全栈编程Agent设计方案.html`、`README.md`、`docs/DESIGN.md`、`backend/app`（240 个文件）、`backend/tests`（119 个文件）、`frontend/src`（36 个文件）  
> 本次验证：后端 `python -m pytest tests -q` → **161 passed**；前端 `npm run build` → **通过**（约 510 KB JS，存在 chunk 体积警告）  
> 结论：**不重写**。Nova 已经越过蓝图 M1，处在 M2 中后段；优势是“证据化交付”，最大缺口是“任务编排 + 全栈契约 + 多栈执行”。

> **P0 进展更新（2026-10-23）**：`jobs` 表 + JobRunner 已接入 FastAPI lifespan，`/jobs` 列表/详情/取消/重试已上线，8 处裸 `asyncio.create_task` 已替换；facts 改为 `(user_id, hash)` 用户隔离；`core/memory/summary.py` 与摘要注入已实现。后端 **173 passed**，真实队列取消 261ms、崩溃恢复实测通过。本文 A1/A2/B2 的原始描述保留为历史基线，实施状态以本节为准。

> **P1 进展更新（2026-10-23）**：`change_requests` / `change_tasks`（迁移 4）、SPEC 起草与冻结、Planner 计划校验、任务模板、串行执行器、未落盘 Gate、统一 edit 提案、只读审查、`/changes` API 与前端「变更中心」已实现。真实 `todo-api` 变更 5 任务全部 Gate passed、审查 pass，应用/撤销均通过；后端 **183 passed**。本文 A3/A4/B1/B6 的部分能力已被该工作流覆盖，完整统一提案服务与 patch 编辑仍待后续。

> **P2.1 进展更新（2026-10-23）**：关键 API 响应模型、OpenAPI 快照（60 paths / 65 schemas）、`contracts/openapi.json`、`api-schema.d.ts`、`contract:generate/check` 与契约快照测试已完成；重复 operation ID 已修复。后端 **186 passed**，契约漂移检查实测会失败并在恢复后通过。Node 沙箱与目标仓库契约 Gate 仍属 P2.2/P2.3。

---

## 0. 先给结论

### 0.1 应该保留并放大的能力

1. **证据化交付**：引用行号校验、命令与退出码、DeliveryReport，这是当前最硬的差异化。
2. **变更影响雷达 + 项目大脑**：依赖图、符号引用、测试定位、阅读顺序，直接可作为 Planner/Navigator 的上下文底座。
3. **红-绿修复闭环**：真实复现、真实跑测试、3 次修复、人工批准，已经验证了“先证明再交付”的产品哲学。
4. **只读 Reviewer**：`pass / warn / block` + 依据，且没有写入/执行工具，边界正确。
5. **Docker 沙箱 + Git 交付 + 轨迹 + CLI**：安全、可撤销、可审计、可自动化，都是平台化基础。

### 0.2 必须补齐的四件事

1. **SPEC 与验收定义（DoD）**：现在只有 bug 描述，没有目标、In/Out、接口契约、可判定验收。
2. **通用任务编排**：现在只有固定的红-绿流水线，没有 Planner、依赖关系、任务模板、取消与恢复。
3. **全栈契约对齐**：前后端类型手写，没有单一事实源，也没有漂移检测，这是蓝图最核心的卖点。
4. **Node/前端执行**：验证与沙箱只支持 Python，全栈闭环在“跑前端测试/构建”这一步断掉。

### 0.3 必须先重构的基础

1. **后台任务执行器**：`asyncio.create_task` 裸奔，无队列、无取消、无重启恢复。
2. **数据库迁移**：手写 DDL 顺序有硬伤，且没有版本管理。
3. **权限策略**：从“模式 + 工具类别”升级为“能力 + 路径 + 网络 + 钩子”。
4. **编辑与审批模型**：整文件覆盖、三套审批流，需要补丁式编辑与统一提案语义。

### 0.4 明确不做

- 不做 Neo4j / 图数据库：现有 PostgreSQL + Qdrant 足够，换图库只增加运维成本。
- 不做“多智能体自由对话”表演：编排必须是确定性状态机，角色只是提示词与工具集的分层。
- 不做 DAG 大屏 / 评测平台：蓝图要的是任务依赖与证据，不是 v1 的演示面板。
- 不做 IDE 插件 / 实时补全：资源集中在“闭环验收 + 全栈一致性”。
- 不做全自动部署：部署必须人工批准 + 隔离预览 + 可回滚。

---

## 1. 当前实现处在蓝图的什么位置

| 蓝图阶段 | 目标 | Nova 现状 | 判断 |
|---|---|---|---|
| M1 单文件修复闭环 | 读需求 → 定位 → 改 → 跑测试/lint → 证据 | 已超额完成：多文件红-绿、Reviewer、Git、影响分析 | ✅ 完成 |
| M2 多文件 + DAG + 索引 + 记忆雏形 | Planner 拆任务、Navigator 召回、Reviewer、3 次重试、三层记忆 | 索引/召回/Reviewer/3 次重试已有；Planner、DAG、记忆摘要缺失 | ◐ 约 60–70% |
| M3 全栈契约对齐 | 单一契约源派生前端类型/后端校验/迁移，前后端协同，隔离构建与冒烟 | 仅 Python 验证；Builder 仅 Python 后端；无契约源 | ❌ 约 5–10% |
| M4 自主部署 + 开放生态 | 部署审批、MCP、记忆晋升/遗忘、指标、模型路由 | 多厂商降级、trace/usage 已有；部署/MCP/晋升/指标缺失 | ❌ 约 10% |

> 结论：Nova 不是“落后一个版本”，而是“底层能力很强、上层任务模型太窄”。不需要推倒重来，需要把已有模块组装成一条更通用的任务链。

---

## 2. 能力对照矩阵

状态：✅ 完成 / ◐ 部分完成 / ❌ 缺失

| 蓝图模块 | 目标 | 当前实现 | 状态 | 建议动作 |
|---|---|---|---|---|
| 6.1 SPEC 与需求澄清 | 目标、In/Out、接口契约、验收用例、NFR，确认后冻结 | Builder 有“方案”，但变更任务只有 bug 描述；无 In/Out、无验收冻结 | ❌ | P1 新增 SPEC 工作流 |
| 6.2 Planner + DoD | 拆任务 DAG，每个任务带可判定验收 | 红-绿是固定 5 步流水线；无通用 Planner、无依赖、无 DoD | ◐ | P1 做 ChangePlan（DAG-lite） |
| 6.3 Navigator 仓库理解 | 符号图 + 向量 + 依赖图 + RRF，增量索引 | AST/正则符号、Qdrant + PG 全文 + RRF、依赖图、brain、impact 均有；无增量、3000 embedding 上限 | ◐ | P1/P2 增量索引与容量治理 |
| 6.4 Editor 改动执行 | 最小 diff、复用抽象、禁止越界、防幻觉依赖 | 整文件写入、diff、审批、快照、冲突检测；无补丁式编辑、无 scope 校验 | ◐ | P1 补丁式编辑 + 范围校验 |
| 6.5 全栈契约对齐 | OpenAPI/类型/ORM 单一事实源，漂移即告警 | 前端 `types.ts` 手写；无契约生成、无漂移检测 | ❌ | **P2 最高优先级新能力** |
| 6.6 自验证闭环 | lint/type/test/build/冒烟，失败摘要回喂，最多 3 次 | Python：compileall + pytest + 可选 ruff/mypy；3 次修复；无 build/冒烟/Node | ◐ | P1/P2 扩展 Gate 与多栈 |
| 6.7 Reviewer 只读审查 | 只读工具，对照 SPEC/契约审 diff，输出 VERDICT/BLOCKING | 只读、结构化 `pass/warn/block` + 依据；未对照 SPEC/契约，未专项查越界/删测试 | ◐ | P1 契约/范围感知审查 |
| 6.8 沙箱与权限 | 三档沙箱 + 审批策略分离 + 能力拦截 + 钩子 | 沙箱强；权限仅 `readonly/ask/auto` + `read/write/execute/network` 类别 | ◐ | P2 能力权限策略引擎 |
| 6.9 三层记忆 | 原始日志 → 日摘要 → 持久记忆，晋升/遗忘 | 消息 + facts；`sessions.summary` 列存在但 `set_summary` 从未调用；无日摘要/晋升 | ◐ | P1 摘要接线，P3 三层 |
| 6.10 幂等与部署 | 外部动作幂等键，超时 unknown，部署审批 | 无幂等账本、无部署器 | ❌ | P3 Deployer + 幂等 |
| L1 交互层 | CLI/IDE/Web 任务面板，展示 DAG 状态 | Web 四视图 + CLI；无 IDE；任务页只有红-绿步骤，无计划/验收 | ◐ | P1 任务中心 UI + CLI |
| L2 编排层 | Coordinator 拆 DAG、调度 Worker、判定 DoD | 单 Agent ReAct 循环；无 Coordinator | ❌ | P1 确定性编排器 |
| L3 专业 Worker | Planner/Navigator/Editor/Tester/Reviewer/Deployer | Navigator/Editor/Tester/Reviewer 以模块存在，非角色化；无 Planner/Deployer | ◐ | P1 角色化提示词 + 工具集 |
| L4 上下文与记忆 | 索引 + 三层记忆 | 索引强；记忆两层且摘要未接线 | ◐ | 同上 |
| L5 工具层 | 文件/Grep/终端/Git/包管理/迁移/MCP | 11 个工具；无 MCP、无数据库迁移工具；`install_deps` 仅管理员联网 | ◐ | P3 MCP + 迁移 |
| L6 沙箱与执行 | 隔离工作区 + 权限矩阵 + 网络边界 + 钩子 | 沙箱隔离强；权限矩阵与钩子缺失 | ◐ | P2 权限引擎 |
| L7 验证门 | lint/type/test/build/冒烟，结构化证据 | Python 闭环强；Node/前端不支持；无 build/冒烟 | ◐ | P2 多栈 Gate |
| 版本安全 | 每任务独立分支，diff 呈现，一键回滚 | 有 Git init/commit/diff/rollback/export；无每任务分支/worktree；回滚是 `reset --hard` | ◐ | P2 分支/worktree + 安全回滚 |
| 可观测指标 | 接受改动率/返工率/人工分钟 | 有 trace/usage/audit；无产品指标聚合 | ❌ | P3 指标 |

### 2.1 已经超出蓝图的能力（不要丢）

| 能力 | 价值 |
|---|---|
| 引用真实性校验 | 把“模型说引用了”变成“行号真实存在”，直接对治幻觉 |
| DeliveryReport | 每轮自动汇总命令、退出码、改动、未验证项、token/耗时 |
| 变更影响雷达 | 依赖面 + 符号引用 + 相关测试 + 风险等级 + 建议命令 |
| 项目大脑 | 模块地图、入口、热点、阅读顺序、依赖图、术语表 |
| 红-绿真实复现 | 先证明测试在修复前失败，再证明修复后通过 |
| Builder 0→1 | 方案 → 文件提案 → 逐文件审阅 → 批准写入/索引 |
| Git 交付 + 轨迹 | 初始化/提交/diff/回滚/导出 + 全链路轨迹 |
| Headless CLI | CI 友好的 `repos/run/verify/trajectory/export` |

---

## 3. 关键差距与根因（按影响排序）

### G1. 任务模型太窄：只能修 bug，不能做功能/重构/全栈

- `backend/app/core/tasks/engine.py` 的流水线是固定的：定位 → 生成测试与补丁 → 红 → 绿 → 审批。
- `backend/app/api/v1/tasks.py` 只有创建、列表、详情、审查、应用、拒绝，**没有取消、没有重试、没有队列**。
- `frontend/src/views/TasksView.tsx` 的入口只有“仓库 + bug 描述”。
- 结果：蓝图里的 SPEC、Planner、DoD、任务模板都无法落地；用户想“加一个接口 + 前端页面 + 测试”时，系统没有承载物。

### G2. 全栈契约缺失：蓝图最核心的卖点没有实现

- `frontend/src/lib/types.ts` 是手写类型；`frontend/src/lib/api.ts` 是手写客户端。
- 后端 FastAPI 自带 `/openapi.json`，但没有生成前端类型，也没有 CI 漂移检查。
- 没有“契约源 → 前端类型 / 后端校验 / DB 迁移”的链路。
- 结果：前后端字段漂移只能靠人肉发现；无法讲“任一层漂移，验证门直接告警”的故事。

### G3. 执行栈太窄：Python 之外无法真实验证

- `backend/app/core/verify/profiles.py:48-54` 检测到 Node 直接返回 `unsupported`。
- 沙箱镜像只有 `nova-sandbox` / `nova-builder`，均为 Python 栈；`run_code` 也只面向 Python。
- README 已如实写明 JS/Java 只做静态分析，但产品上这意味着“全栈闭环”在最后一步断裂。
- 结果：Builder 只能生成 Python 后端；React/Vite/Express 项目无法跑 lint/typecheck/test/build。

### G4. 后台任务不可靠：重启即丢，无法取消

- `api/v1/tasks.py:64`、`api/v1/repos.py:74/95/129`、`api/v1/builder.py:44/69/93/115`、`api/v1/chat.py:157/205`、`api/v1/git_ops.py:78` 全部使用裸 `asyncio.create_task`。
- 没有 job 表、没有 worker、没有心跳、没有 `FOR UPDATE SKIP LOCKED`、没有取消接口。
- `tasks.status` 默认 `running`；进程重启后任务永久停在 running，前端只能看到“运行中”。
- 结果：演示时一次重启就出现“僵尸任务”；多任务并发也没有资源上限。

### G5. 数据库初始化与记忆有硬伤

- `backend/app/db/init_db.py` 的 `_DDL` 中，`edits`（第 59 行）在 `repos`（第 103 行）之前创建，且 `edits.repo_id REFERENCES repos(id)`。在全新的 PostgreSQL 上，`CREATE TABLE edits` 会报 `relation "repos" does not exist`；而 `transaction()` 把全部 DDL 放在一个事务里，初始化会整体失败。README 的“首次启动自动完成幂等初始化”在空库上不成立。
- `facts` 表（第 90-100 行）没有 `embedding` 列，但 `core/memory/facts.py:43/89` 会查询和写入 `embedding`。空库上长期记忆写入会失败，且异常被 `except` 吞掉，表现为“记忆时好时坏”。
- `facts.hash` 是全局唯一（第 94 行），`add_fact` 只按 hash 查重，不区分 user_id。两个用户说同一句话会互相碰撞，B 用户的事实可能被丢弃或更新到 A 用户身上。
- 没有版本化迁移，只有 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` 列表；后续改表只能继续追加，顺序和幂等性会越来越脆弱。

### G6. 记忆只有两层，摘要函数是死代码

- `core/memory/session.py:12` 只注入最近 12 条消息；`set_summary`（第 144 行）从未被调用。
- 没有“日摘要”、没有“晋升/遗忘”任务；facts 的检索按重要性排序，不按语义相关性。
- 结果：长会话会丢失早期决策；蓝图的三层记忆无法演示。

### G7. 权限是“模式 + 类别”，不是“能力 + 路径 + 网络”

- `core/tools/base.py:34/44/128`：`permission_mode` 只有 `readonly/ask/auto`，工具只有 `read/write/execute/network` 类别；`readonly` 只拦 write/execute。
- 没有路径范围（repo root / 子目录）、没有网络域名白名单、没有命令级 allow/deny、没有 pre/post hook、没有“退出码 2 阻断”。
- 结果：无法回答蓝图的“拦了 git push，它改用 curl 打 API 怎么办”；也无法做“凭据只注入单条命令环境”。

### G8. 编辑整文件覆盖，审批流有三套

- `write_files` 以完整文件内容写入；对大文件会产生巨大 diff，也不利于“最小改动”。
- `edits`（对话内修改）、`tasks`（红-绿）、Builder `proposal` 是三套表、三套 API、三套前端审批语义。
- 结果：审计口径不统一、UI 重复、冲突检测/回滚逻辑难以复用；scope creep 只能靠提示词。

### G9. 索引与沙箱复制有静默截断

- `config.py:65` 的 `index_embed_max_chunks=3000`：超过 3000 的 chunk 不会进 Qdrant，稠密召回直接缺失，但索引状态仍显示成功。
- `core/tools/run_code.py:17-19`：复制仓库进沙箱上限 300 文件 / 2 MB / 单文件 200 KB；超出直接 `return`，没有“已截断”的告警。验证可能跑在“半个仓库”上，产生假失败。
- 每次应用补丁都全量重建索引；大仓库慢且费 embedding。
- 结果：大仓库的检索与验证可信度下降，且用户不知道。

### G10. 缺少产品指标与多 worker 一致性

- 有 trace/usage/audit，但没有“接受改动数、返工率、每个被接受改动的人工分钟、首次 Gate 通过率、单任务成本”的聚合。
- `core/security/limits.py` 的小时配额用进程内 `defaultdict(deque)`；多 worker/多副本下配额会绕过。
- 结果：无法用数据证明“Agent 真的提升了交付效率”，也无法安全扩容。

---

## 4. 目标形态：单 Agent 聊天 + 确定性变更编排

```text
Web / CLI
   │
   ├── Chat 模式（保留）：单 Agent ReAct → 检索 → 工具 → 证据 → 回答
   │
   └── Change 模式（新增）：
         Change Orchestrator（确定性状态机）
           SPEC → PLAN（DAG-lite） → EXECUTE → GATE → REVIEW → APPROVE → APPLY → VERIFY → DELIVER
             │        │                 │          │         │          │          │
             │        │                 │          │         │          │          └─ Git/报告/指标
             │        │                 │          │         │          └─ 冲突检测/快照/回滚
             │        │                 │          │         └─ 人工审批（统一 Proposal）
             │        │                 │          └─ 只读 Reviewer（对照 SPEC/契约）
             │        │                 └─ Editor / Tester（复用 write_files、sandbox、verify）
             │        └─ Planner（复用 index、impact、brain；输出带验收的任务）
             └─ SPEC（目标/In-Out/接口/验收/NFR）
```

### 4.1 五条设计原则

1. **Chat 与 Change 分模式**：聊天保持低延迟单 Agent；只有“要改仓库”才进入编排，避免把闲聊也变成多 Agent。
2. **DAG-lite 而不是通用 DAG**：任务有依赖、有 In/Out、有验收；默认串行执行，只有只读调研可并行，写操作绝不并行。
3. **LLM 提议，代码判定**：Planner 可以生成计划和命令，但 Gate 只执行白名单/已批准的命令，DoD 由退出码和测试结果判定。
4. **一套提案语义**：编辑、红-绿、Builder 最终都归一到“提案 → 审阅 → 批准/拒绝 → 应用/回滚”，表可以暂时不合并，服务与 UI 必须统一。
5. **复用优先**：索引、RAG、impact、brain、sandbox、evidence、review、git、memory 都是资产；编排层只做组合，不重写底层。

---

## 5. 分类行动清单

### A. 重构（架构与正确性）

#### A1. P0 可靠任务执行器（JobRunner）

**做什么**
- 新增 `jobs` 表：`id / user_id / kind / payload / status / progress / idempotency_key / attempts / heartbeat_at / error / created_at / started_at / finished_at`。
- 独立 worker loop（可与 API 同进程启动，也可拆进程）：`SELECT ... FOR UPDATE SKIP LOCKED` 取任务；按 kind 限制并发（index=1、task=1、builder=1）。
- 启动恢复：心跳超时的 `running` 任务回到 `queued` 或标记 `failed` 并写原因；已产生副作用的用幂等键核对。
- 取消：`POST /jobs/{id}/cancel`，worker 在节点之间检查取消标志，沙箱执行可 kill。
- 统一替换 `asyncio.create_task`：索引、红-绿、Builder、验证、应用后重建索引。

**主要文件**
- 新增 `backend/app/core/jobs/`（model、runner、handlers）。
- 改 `backend/app/main.py` lifespan、`api/v1/tasks.py`、`repos.py`、`builder.py`、`git_ops.py`、`chat.py`。
- 前端任务页增加取消/重试/进度。

**验收**
- 任务执行中 `kill -9` 进程，重启后任务不会永久停在 `running`；要么继续，要么带原因失败。
- 取消请求 5 秒内生效，沙箱进程被清理。
- 同一提案重复“应用”不会写两次（幂等键）。
- 并发 5 个任务时，索引/写入类任务按配置串行，不出现仓库写冲突。

#### A2. P0 数据库迁移与空库可启动

**做什么**
- 立即修 DDL 顺序：`users → sessions → messages → repos → repo_files → symbols → file_deps → chunks → edits → tasks → ...`。
- `ALTER TABLE facts ADD COLUMN IF NOT EXISTS embedding JSONB`；把 facts 唯一约束改为 `(user_id, hash)`。
- 引入 `schema_migrations` 表 + 编号 SQL（或 Alembic）；启动时检查版本，缺迁移直接 fail fast 并打印明确提示。
- 停止继续往 `_DDL` 追加；所有新列/索引走迁移。

**验收**
- 空 PostgreSQL → `python -m app.db.init_db` → 所有表/列存在。
- 第二次执行无副作用。
- CI 用临时 PG 跑一遍“空库初始化 + 重复初始化 + 迁移到最新”。
- `facts` 写入/去重/跨用户隔离有集成测试。

#### A3. P1 统一提案与审批语义

**做什么**
- 新增 `ProposalService` 接口：`create / get / list / approve / reject / revert / review`。
- 为 `edits`、`tasks`、Builder `proposal` 写适配器；表可保留，但 API 与前端统一。
- 统一审计事件：`proposal.created / approved / rejected / applied / reverted / reviewed`。

**验收**
- 三类提案在 UI 上使用同一个审阅组件与同一套状态机。
- 批准/拒绝/回滚都产生一致的审计记录。
- 不再出现“某个流程有审查、另一个没有”的割裂。

#### A4. P1 补丁式编辑与范围校验

**做什么**
- `write_files` 增加 `patch` 模式：unified diff 或 search/replace hunk；整文件写入保留为 fallback。
- 原子多文件应用；应用前做内容哈希冲突检测；失败全部回滚。
- 任务携带 `in_scope / out_scope`；写超出 In 清单的文件时默认 ask/block。
- 写入前检查 import/依赖是否存在，降低“幻觉包”。

**验收**
- 2000 行文件改 3 行，diff 只显示 3 行。
- 文件在生成后被外部修改 → 409，不覆盖。
- 越界文件 → 审批或阻断，并记录原因。

#### A5. P2 权限策略引擎

**做什么**
- `Capability`：`fs.read / fs.write / proc.exec / net.fetch / git.write / deploy / secrets.read`。
- 决策输入：工具、参数、仓库根、会话模式、用户角色、任务范围；输出 `allow / ask / deny + reason`。
- 路径范围：repo root、子目录、只读路径；网络：域名/IP 允许列表；命令：allow/deny 正则。
- pre/post hook：退出码 2 阻断，stderr 回喂 Agent；钩子是否执行要有输出验证。
- 密钥：`.env`/私钥拒绝读写；凭据只注入单条命令环境；输出做 secret redaction。

**验收**
- 绕过测试集：`git push` 被拦后改用 `curl`、Python `requests`、编码路径、符号链接、同前缀兄弟目录，全部按能力拦截。
- 每条决策都有审计记录（允许/询问/拒绝 + 原因）。
- 钩子未执行时能被检测到，不静默失败。

#### A6. P2 增量索引

**做什么**
- 用 Git diff + 文件内容哈希做增量：新增/修改文件重解析、重分块、重嵌入；删除文件清理 chunks/symbols/deps/Qdrant points。
- embedding 分批 + 并发上限；`index_embed_max_chunks` 可配置，统计 `embedded/total` 并在 UI 显示“已截断”。
- 索引状态分阶段：walk → symbols → chunks → embed → brain，失败可重试。

**验收**
- 1000 文件仓库改 1 个文件，重建 < 10 秒，只有该文件的 chunk 变化。
- 超过 embedding 上限时 UI 明确提示，不假装全量。
- 删除文件后检索不再命中。

#### A7. P2 契约生成与漂移检查

**做什么**
- 从 FastAPI `/openapi.json` 生成 `frontend/src/lib/api-schema.d.ts`（`openapi-typescript`）。
- `api.ts` 基于生成类型；CI 增加 `contract:check`：重新生成后与仓库文件 diff，不一致即失败。
- 后续再做 DB schema 与 Pydantic 的差异检查（先只读告警，不自动改库）。

**验收**
- 后端改一个响应字段 → 生成文件变化；不重新生成则 CI 失败。
- 前端使用旧字段时 TypeScript 编译失败。
- 契约检查纳入验证门与 CI。

#### A8. P3 可观测与指标

**做什么**
- 从 `trace_events`、`usage_log`、`tasks`、`edits` 聚合：接受改动数、返工率、首次 Gate 通过率、人工分钟、单任务 token/耗时。
- 日志统一带 `task_id / turn_id / repo_id`；可选 OpenTelemetry。
- 前端增加“交付指标”页或工作区卡片。

**验收**
- 任意一周能算出蓝图的三个核心数：被接受改动数、返工率、每个被接受改动的人工分钟。
- 单任务能导出完整证据链（命令、退出码、diff、审查、审批、耗时）。

---

### B. 拓展（新能力）

#### B1. P1 SPEC 工作流

**做什么**
- 新增 `change_requests`：`goal / in_scope / out_scope / interfaces / acceptance_cases / nfr / open_questions / approved_at / version`。
- 流程：自然语言需求 → LLM 起草 SPEC → 歧义点一次性提问 → 用户编辑/确认 → 冻结。
- 冻结后进入 Plan；修改 SPEC 必须新版本，不能边写边改。
- 前端：SPEC 面板，In/Out 用可编辑列表，验收用例逐条可勾选。

**验收**
- 没有批准的 SPEC，不能创建 Plan。
- 需求含糊时系统会提问，而不是直接写代码。
- SPEC 变更留下版本与 diff。

#### B2. P1 ChangePlan（DAG-lite）+ DoD

**做什么**
- 新增 `change_tasks`：`request_id / seq / title / kind / in_scope / out_scope / acceptance / depends_on / status / attempts / evidence`。
- Planner 输出 JSON；服务端校验：无环、依赖存在、每个任务至少一条可判定验收（命令 + 期望退出码/测试名）。
- 计划需人工批准；执行默认串行；失败只回喂失败摘要；单任务最多 3 次；超限上交并列出已尝试方案。
- 任务模板：`bugfix`（复用红-绿）、`feature`（SPEC + 计划）、`refactor`（行为不变 + 测试）、`test-add`、`docs`、`contract-change`。

**验收**
- 一个“新增 API + 测试 + 文档”的功能任务能端到端跑完：计划 → 执行 → Gate → Review → 批准 → 应用 → 验证 → 报告。
- 写不出验收命令的任务不能进入执行。
- 3 次失败后停止，不无限循环，不删测试。

#### B3. P2 全栈契约对齐（最高差异化）

**做什么**
- 契约源：仓库内 `contracts/openapi.yaml`（由 FastAPI 导出或 spec-first 编写），作为唯一事实源。
- 前端：`openapi-typescript` 生成类型，`openapi-fetch` 或轻量包装生成客户端；运行时用 zod 做边界校验。
- 后端：Pydantic 模型与契约做一致性检查；响应字段/状态码漂移在 Gate 告警。
- DB：第二阶段做 SQL schema 与模型/契约的差异检查，只提示迁移建议，不自动执行。
- UI：契约状态面板（当前版本、漂移文件、最近变更）。
- Gate 增加 `contract` 步骤；CI 同款检查。

**验收**
- 改后端响应字段 → 生成类型更新 → 前端编译通过；不更新则 `contract:check` 失败。
- 改前端请求字段 → 后端契约校验失败或 Gate 告警。
- 一个示例仓库能演示“契约变更 → 前端类型 → 后端校验 → 测试”全链路。

#### B4. P2 Node/TS 执行与验证

**做什么**
- 新增 `Dockerfile.node-sandbox`：Node 20 + pnpm/npm + 常用构建工具；镜像尽量 slim。
- Profile 检测：`package.json`、lockfile、`tsconfig.json`、workspace 配置；识别 monorepo 子包。
- 步骤：依赖安装（默认离线缓存；联网需管理员批准）→ lint → `tsc --noEmit` → test → build。
- 与 Python profile 并列；一个仓库可同时跑 Python 与 Node（前后端）。
- 失败输出结构化：命令、退出码、stdout/stderr 摘要、耗时。

**验收**
- 示例 React/Vite 项目：测试通过/失败都能如实报告；`npm run build` 真实执行。
- 示例 Express API：lint/typecheck/test 至少一项真实运行。
- 默认无网络；依赖安装有缓存卷；超时有上限。

#### B5. P3 契约驱动的 Builder（全栈脚手架）

**做什么**
- Builder 先生成 OpenAPI 契约，再生成 FastAPI 后端 + React 前端 + docker compose + 测试。
- 复用 B3 的生成器，保证前后端类型一致。
- 生成后自动跑 Python + Node Gate；可选启动预览容器、健康检查。
- 仍然是“提案 → 审阅 → 批准写入”，不自动部署到生产。

**验收**
- 一句需求生成可运行的全栈脚手架；前后端测试通过；`docker compose up` 健康检查通过。
- 契约与生成代码一致；删除任一生成文件后 Gate 能发现。

#### B6. P1/P2 任务模板体系

**做什么**
- 把“红-绿”从一个硬编码流程降级为 `bugfix` 模板；新增 feature/refactor/test/docs/contract 模板。
- 每个模板定义：输入、计划提示词、Gate 步骤、审批点、最大尝试次数、证据字段。
- 模板可由仓库配置覆盖（如 `nova.yaml`：测试命令、lint 命令、忽略目录）。

**验收**
- 至少 bugfix、feature、refactor 三个模板可从 UI/CLI 使用。
- 模板配置错误时启动前报错，不等到执行中。

#### B7. P3 三层记忆

**做什么**
- 第一层：原始消息（已有）。
- 第二层：会话滚动摘要——每 20–30 条或 token 超阈值触发，写入 `sessions.summary`；提示词注入“摘要 + 最近 N 条”。
- 第三层：facts（已有）+ 日摘要；每周晋升（同一偏好在 ≥2 次日摘要出现才晋升）、遗忘（TTL/低重要性/已闭环）、矛盾检测。
- facts 检索改为“语义相关 + 重要性”混合；修复 embedding 列与跨用户 hash。
- UI：记忆列表、删除、来源链接。

**验收**
- 100 条消息的会话仍能答出早期关键决策；摘要 ≤ 40 行。
- 重复偏好只保留一条；过期/低价值事实被清理。
- 用户可查看/删除自己的事实。

#### B8. P3 Deployer + 幂等账本

**做什么**
- `external_actions` 表：`idempotency_key / action / target / status(pending|succeeded|failed|unknown) / request / response / timestamps`。
- 部署：隔离 compose 项目 → build → up → 健康检查 → 返回预览 URL；默认 ask 人工批准；一键 teardown/rollback。
- 超时置 `unknown`；重试前先查目标状态，避免重复创建。
- Git commit/push、依赖安装等外部写操作也接入幂等键。

**验收**
- 部署示例应用，健康检查通过后可访问；失败能回滚。
- 模拟超时后重试，不会重复创建资源。
- 所有部署动作有审批与审计。

#### B9. P3 MCP 外接工具

**做什么**
- MCP client：服务发现、工具列表、调用、超时、错误映射。
- 服务 allowlist；每个 MCP 工具映射到能力（读/写/网络），走同一权限引擎。
- 审计：server、tool、参数摘要、结果状态。

**验收**
- 接入一个本地 MCP server（如 filesystem/sqlite），工具可见可调用。
- 未授权 server 被拒绝；越权工具按能力拦截。
- 超时/断连不影响主流程。

#### B10. P3 指标与周报

**做什么**
- 指标：接受改动数、首次 Gate 通过率、返工率、人工分钟/被接受改动、token 成本/任务、p95 时长。
- 按周聚合；CLI `nova metrics --week`；前端卡片。
- 用数据决定下一阶段优先级，而不是感觉。

**验收**
- 连续两周能导出指标；能与上一周对比。
- 指标口径写进文档，避免自欺。

---

### C. 完善（已有但未闭环）

| 编号 | 事项 | 现状 | 动作 | 优先级 |
|---|---|---|---|---|
| C1 | 空库初始化 | `edits` 先于 `repos`；`facts.embedding` 缺失 | 修 DDL/迁移；加集成测试 | P0 |
| C2 | 任务取消/恢复/进度 | 无取消、无队列、重启卡 running | 随 A1 完成 | P0 |
| C3 | 会话摘要 | `set_summary` 未调用 | 随 B7 接线 | P1 |
| C4 | 前端任务详情 | 只有红-绿步骤，无验收清单/尝试次数/取消 | 任务中心改造 | P1 |
| C5 | CLI | 只有 repos/run/verify/trajectory/export | 增加 `plan/task/gate/contract/deploy` | P1 |
| C6 | 测试 | 后端 161 个；前端无测试；缺空库/恢复/权限/契约测试 | Vitest + Playwright + 集成测试 | P1 |
| C7 | 红-绿泛化 | 硬编码 pytest/Python | 从 profile 读测试命令；支持 unittest/npm test | P2 |
| C8 | Builder 预览 | 不启动常驻服务 | 健康检查 + 预览 URL | P2 |
| C9 | Git 安全 | 回滚 `reset --hard`；无任务分支 | worktree/branch；revert + 备份 | P2 |
| C10 | 多 worker 配额 | 进程内 deque | PG 原子计数或 Redis | P2 |
| C11 | 索引/复制截断 | 3000 embedding、300 文件/2MB 静默截断 | 可配置 + 明确告警 | P2 |
| C12 | 文档 | DESIGN 仍写“不做 DAG”；README 边界会过时 | 更新决策记录与边界 | P2 |

---

### D. 改进（体验、性能、成本、安全）

1. **任务中心 UX**：首页从“聊天列表”升级为“最近变更 + 待审批 + 失败任务”；证据优先展示，diff 可逐文件审阅；支持键盘快捷键。
2. **模型路由**：Planner/Reviewer 用强模型，检索/摘要/格式化用小模型；按角色配置，不全程最贵模型；把成本记到任务维度。
3. **性能**：embedding 批量与并发、索引分阶段、DB 索引检查、前端按路由拆包（当前 510 KB 警告）。
4. **可靠性**：优雅停机（等在跑任务落库）、沙箱容器清理、失败重试上限、熔断与超时统一。
5. **安全**：CSRF/Origin 校验、输出 secret redaction、依赖漏洞扫描、网络允许列表、钩子执行验证、最小权限。
6. **代码质量**：统一错误响应结构、Pydantic 模型与 TS 类型同源、清理死代码/旧 pycache、CI 加 lint + typecheck + 测试。
7. **演示与评测**：准备 3 个黄金仓库（Python bug、Node 前端、全栈契约变更），每次改动跑回归；固定 demo 脚本。
8. **文档**：ADR（任务队列、契约源、权限模型）、运行手册、故障排查、README 边界更新。

---

## 6. 路线图

### 6.1 完整路线（单人全职估算）

| 阶段 | 周期 | 主题 | 关键交付 | 退出条件 |
|---|---|---|---|---|
| P0 | 1–1.5 周 | 正确性与任务可靠性 | DB 迁移、JobRunner、取消/恢复、摘要接线、空库测试 | 空库可启动；重启不卡任务；可取消；记忆可用 |
| P1 | 3–4 周 | 从“修 bug”到“改功能” | SPEC、ChangePlan、DoD、模板、补丁编辑、统一审批、任务 UI/CLI | 功能任务端到端；3 次上限；证据完整 |
| P2 | 5–7 周 | 全栈闭环 | 契约生成/漂移门、Node 执行、契约驱动 Builder、每任务分支 | OpenAPI→TS 漂移可拦截；Node 测试/构建真实执行；全栈示例通过 |
| P3 | 5–7 周 | 平台化 | 三层记忆、能力权限、Deployer/幂等、MCP、指标 | 预览部署可回滚；记忆可晋升；绕过测试全过；指标可导出 |

**总计约 14–19 周全职**；如果业余开发，按 6–9 个月估算。

### 6.2 推荐的最小可演示路径（8–10 周）

如果目标是“面试/作品集可演示”，不要等 P3 全做完。优先：

1. **P0**（1–1.5 周）：修空库、任务队列/取消/恢复。
2. **P1 的 SPEC + ChangePlan + 任务 UI**（3 周）：能演示“加一个功能”而不只是“修一个 bug”。
3. **B3 契约对齐**（2–3 周）：改一个字段，前端类型自动更新，漂移被 Gate 拦截。
4. **B4 Node 验证**（1.5–2 周）：React/Vite 项目真实跑 test/build。
5. **C4 任务详情 + C5 CLI**（1 周）：证据链、审批、CI 可跑。

这条路径能在 8–10 周内形成三个完整 demo：

- **Demo A（已有，打磨）**：贴 bug → 红-绿 → Reviewer → 批准 → Git 交付 → 证据报告。
- **Demo B（P1）**：提功能需求 → SPEC 确认 → 计划/验收 → 执行 → Gate → 审批 → 应用。
- **Demo C（P2）**：改 OpenAPI 字段 → 前端类型生成 → 后端/前端测试 → 契约漂移门 → Node 构建。

> 这三个 demo 正好对应蓝图的“证据式验收闭环 + 全栈契约自动对齐”两个最硬卖点。

### 6.3 为什么是这个顺序

- **P0 先做**：空库起不来、重启卡任务，是演示与部署的“可信度杀手”，不修会抵消所有功能亮点。
- **P1 再做**：没有 SPEC/计划/验收，契约对齐和部署都没有承载物；红-绿只能算一个模板。
- **契约先于部署**：契约对齐是差异化、可复用、风险低；部署涉及信任与运维，放在最后。
- **Node 先于全栈 Builder**：没有真实验证，生成全栈项目只会制造“看起来能跑”的假象。
- **记忆/权限/MCP 后置**：重要但不阻塞主叙事；等主链路稳定后再平台化。

---

## 7. 验收指标

| 维度 | 指标 | 目标（黄金仓库） |
|---|---|---|
| 交付 | 任务成功率 | ≥ 70% |
| 质量 | 首次 Gate 通过率 | ≥ 50% |
| 返工 | 平均修复轮次 | < 2 |
| 安全 | 权限绕过测试 | 100% 拦截 |
| 契约 | 漂移检测覆盖 | 100% CI |
| 性能 | 小仓库任务 p95 | < 10 分钟 |
| 成本 | 单任务 token | 有预算、可对比 |
| 记忆 | 摘要长度 | ≤ 40 行，关键决策不丢 |
| 体验 | 审批耗时 | < 2 分钟 |

> 指标口径要写进文档；否则“接受率/返工率”很容易变成自欺。

---

## 8. 风险与对策

| 风险 | 表现 | 对策 |
|---|---|---|
| 范围蔓延 | 又想加 DAG 大屏、又想加 IDE | 锁定 P0/P1 范围；P3 之前不做新面板 |
| 多 Agent 复杂度 | 角色互相等待、成本翻倍 | 逻辑角色 + 确定性状态机；只有只读调研并行 |
| 契约生成边界 | 泛型/联合类型/错误模型生成不理想 | 先 API-only；黄金仓库回归；生成失败降级为告警 |
| Node 沙箱体积/网络 | 镜像大、依赖安装慢 | slim 镜像、lockfile 离线缓存、联网仅管理员 |
| DB 迁移风险 | 老库升级失败 | 备份 + 迁移测试 + 启动前检查；先修空库 |
| LLM 成本/延迟 | 任务链太长 | 角色路由、摘要压缩、缓存、每任务预算 |
| 安全 | 能力拦截被绕过 | 绕过测试集 + 钩子验证 + 审计 + 红队用例 |
| 单人精力 | 做不完 | 采用 8–10 周演示路径；P3 延后 |

---

## 9. 下一步 10 件事（可直接开工）

- [ ] 修 `init_db.py` DDL 顺序；加 `facts.embedding` 与 `(user_id, hash)` 唯一约束；补空库集成测试。
- [ ] 新增 `jobs` 表与 JobRunner；替换所有裸 `asyncio.create_task`；加取消/重试/恢复接口。
- [ ] 把 `set_summary` 接进 Agent 上下文；会话超过阈值自动摘要。
- [ ] 定义 `change_requests` / `change_tasks` / `acceptance` 的 schema 与 API。
- [ ] 把红-绿改成 `bugfix` 模板；新增 `feature`/`refactor` 模板骨架。
- [ ] 前端任务中心：SPEC 面板、计划/验收清单、尝试次数、证据、取消。
- [ ] `write_files` 增加 patch 模式与 scope 校验。
- [ ] 从 `/openapi.json` 生成前端类型；加 `contract:check`。
- [ ] 新增 Node 沙箱镜像与 verify profile；用 React/Vite 示例回归。
- [ ] 更新 `docs/DESIGN.md` 决策记录（DAG-lite 的范围）与 README 已知边界。

---

## 附录 A：当前代码地图（与本文相关）

| 领域 | 主要文件 | 说明 |
|---|---|---|
| Agent 循环 | `backend/app/core/agent/loop.py` | 单 Agent ReAct、SSE、证据、持久化 |
| 工具 | `backend/app/core/tools/*` | 11 个工具、注册表、路径/风险校验 |
| 索引 | `backend/app/core/indexing/*` | walker/symbols/chunker/imports/brain/pipeline |
| 检索 | `backend/app/core/rag/*` | dense + keyword + RRF |
| 影响分析 | `backend/app/core/impact/*` | 依赖图 + 符号引用 |
| 红-绿 | `backend/app/core/tasks/engine.py` | 固定流水线、3 次修复 |
| 验证 | `backend/app/core/verify/*` | Python profile + 沙箱执行 |
| 审查 | `backend/app/core/review/*` | 只读 Reviewer |
| 编辑 | `backend/app/core/editing/*` | diff/审批/快照/冲突 |
| Builder | `backend/app/core/builder/*` | 方案 + 文件提案 |
| Git | `backend/app/core/git_ops/*` | init/commit/diff/rollback/export |
| 记忆 | `backend/app/core/memory/*` | 消息 + facts |
| 安全 | `backend/app/core/security/*` | 认证/配额/路径/风险/审计 |
| DB | `backend/app/db/init_db.py` | 手写 DDL（待迁移） |
| API | `backend/app/api/v1/*` | auth/chat/repos/tasks/builder/git/status |
| 前端 | `frontend/src/views/*` | chat/workspace/tasks/settings |
| 设计文档 | `docs/DESIGN.md` | v2 决策记录（需更新 DAG 决策） |

## 附录 B：关键证据（代码位置）

- `backend/app/db/init_db.py:59-76`：`edits` 建表；`:103-115`：`repos` 建表；前者 FK 引用后者。
- `backend/app/db/init_db.py:90-100`：`facts` 无 `embedding` 列；`backend/app/core/memory/facts.py:43,89` 使用该列。
- `backend/app/core/memory/facts.py:64,89-92`：按全局 `hash` 查重/写入，未带 `user_id`。
- `backend/app/core/memory/session.py:12,144`：最近 12 条；`set_summary` 未被调用。
- `backend/app/api/v1/tasks.py:64`：裸 `asyncio.create_task`；全文件无取消接口。
- `backend/app/core/verify/profiles.py:48-54`：Node 返回 unsupported。
- `backend/app/core/tools/run_code.py:17-19`：300 文件 / 2 MB 截断。
- `backend/app/config.py:65`：`index_embed_max_chunks=3000`。
- `backend/app/core/tools/base.py:34,44,128`：权限模式与工具类别。
- `docs/DESIGN.md:4,24`：v2 明确“砍 DAG/Neo4j/评测/图谱前端”；本文建议以“ChangePlan DAG-lite”局部回归，并在文档中更新该决策的边界。

---

> 本文只做差距分析与路线规划，没有改动业务代码。建议先把 P0 的四个问题修掉，再按“8–10 周演示路径”推进；P3 的平台化能力等主链路稳定后再做。
