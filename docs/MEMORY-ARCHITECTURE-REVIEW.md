# Nova Agent 记忆架构评审

**日期**：2026-11-22  
**对照对象**：Anthropic 2026 年公开的 Claude Code / Claude API / Agent SDK 记忆与上下文做法  
**评审范围**：`backend/app/core/memory/*`、`backend/app/core/agent/*`、`backend/app/core/rag/*`、`backend/app/core/reflection/*`、`backend/app/api/v1/memory.py`、`frontend/src/settings/sections/MemorySection.tsx`  
**研究底稿**：[`docs/research/2026-11-22-claude-code-memory.md`](research/2026-11-22-claude-code-memory.md)（只使用一手来源；API 文档因本地网络地区重定向，经官方 `llms-full.txt` 读取）

> **结论先行**：Nova 的“原始消息 → 滚动摘要 → 日摘要 / facts → lessons”分层是成立的，混合检索和上下文计量也做得比多数同类项目扎实。但当前有两个会直接产生错误答案的结构性问题：**上下文先按固定 12 条截断、摘要却可能在之后才生成**，以及**长期事实只有 user 级作用域、没有 repo / 论文项目 / 产品模式作用域**。这两个问题应优先于“再加一层记忆”来修。Anthropic 的公开做法真正值得抄的不是“用 Markdown 存记忆”，而是四个原则：人类指令与代理学习分开、顶层索引 + 按需展开、压缩必须可恢复、记忆必须可审计可纠正。

---

## 1. Anthropic 公开了什么

### 1.1 先分清四层，避免把不同机制混为一谈

截至 2026-11-22，Anthropic 没有发布一份覆盖所有产品的单一“记忆架构规范”。公开材料至少分四层：

| 层 | 代表机制 | 解决什么问题 |
|---|---|---|
| Claude Code 产品 | `CLAUDE.md` / `AGENTS.md` / `.claude/rules/`、auto memory / `MEMORY.md`、自动压缩、子代理隔离 | 让编码会话跨会话保留指令与学习 |
| Claude API | memory tool（`/memories` 文件工具）、context editing、server-side compaction | 让开发者自己拼长任务上下文与持久记忆 |
| Claude Agent SDK | 继承 Claude Code 的指令与 auto memory；session / transcript；SDK 自动压缩；子代理 `memory` 字段 | 在 SDK 里复用产品级行为 |
| 工程研究 | 《Effective context engineering》《The components of agent memory》等 | 给出模式、评估与开放问题，不是产品规格 |

因此，下面的“Anthropic 做法”是**可观察的公开机制与工程原则**，不是一份官方架构标准。评审时不应把研究文章里的 dreaming / wiki 当成 Claude Code 已经落地的功能。

### 1.2 Claude Code：人类写的指令 vs Claude 自己写的学习

Claude Code 把跨会话知识分成两类，这个划分非常关键：

| | `CLAUDE.md` 类文件 | auto memory |
|---|---|---|
| 谁写 | 人 | Claude 自己 |
| 内容 | 指令、规则、项目约定 | 学习、纠正、偏好、项目背景 |
| 作用域 | managed / user / project / local | 按 git 仓库一个目录，worktree 共享 |
| 何时进上下文 | 每个会话启动时 | 开启 auto memory 的会话，加载 `MEMORY.md` 前 200 行或 25KB |
| 典型用途 | 构建命令、代码规范、架构约束 | 用户偏好、被纠正的做法、代码里推不出来的项目决策 |

**指令层的关键细节**（[Claude Code memory docs](https://code.claude.com/docs/en/memory)）：

- 四层作用域：managed policy、`~/.claude/CLAUDE.md`、`./CLAUDE.md` 或 `./.claude/CLAUDE.md`、`./CLAUDE.local.md`。
- 所有发现的文件是**拼接**，不是后者覆盖前者；越靠近工作目录的内容越晚读到。冲突时 Claude 可能任选一条，所以文档要求定期审计、删除矛盾指令。
- 子目录里的 `CLAUDE.md` 不在启动时加载，而是在 Claude 读到/写到该目录文件时按需加载。
- 支持 `@path` 导入，递归最多 4 跳；支持 `AGENTS.md`；支持 `.claude/rules/*.md`，带 `paths:` frontmatter 的规则只在匹配文件被读写时加载。
- 单个 `CLAUDE.md` 建议 200 行以内；超过 4 MiB 直接跳过；路径规则/子目录文件另有更小的字符上限。
- 文档明确说：这些文件是 **context，不是 enforced configuration**。要强制阻止动作，用 `PreToolUse` hook、权限或 managed settings。

**auto memory 的关键细节**：

- 位置：`~/.claude/projects/<project>/memory/`，`<project>` 由 git 仓库推导，所以同一仓库的 worktree/子目录共享一份；非 git 仓库用项目根目录。
- 结构：`MEMORY.md` 是索引，一行一条；每个主题一个文件（如 `user_role.md`、`feedback_testing.md`）。
- 启动时只加载 `MEMORY.md` 前 200 行或 25KB；主题文件**不**在启动时加载，Claude 需要时用普通文件工具按需读取。
- 四类笔记写在 frontmatter 的 `type`：`user`（角色、专长、偏好）、`feedback`（纠正、确认过的方法）、`project`（进行中的工作、截止日期、代码/git 推不出的决策）、`reference`（外部信息在哪里找）。
- Claude 会跳过能从代码库推导的内容（架构、文件路径、调试修复），也会跳过 `CLAUDE.md` 已经说了的内容；不是每个会话都写。
- 写入带 YAML frontmatter 的文件时，Claude Code 记录 `modified` 时间戳；文件是普通 Markdown，用户可通过 `/memory` 浏览、编辑、删除。
- auto memory 是 machine-local，不跨机器/云共享；`cleanupPeriodDays` 清理旧 transcript，但**不清理** memory 文件。
- 子代理可以有独立记忆：`memory: user | project | local`，主会话的 auto memory 不会进入子代理（fork 例外）。

这套设计的本质是：**顶层只放“我知道什么、去哪里找”的短索引，细节放到下面按需展开**。Anthropic 在《The components of agent memory》里明确说，顶层记忆会注入每个会话，必须保持小，否则既耗 token 又会降低遵从度；dreaming 的很多工作就是“把细节下移，留下链接”。

### 1.3 压缩、上下文编辑与记忆工具

这是三个不同层次，不能混用：

| 机制 | 做什么 | 关键点 |
|---|---|---|
| Claude Code 自动压缩 / `/compact` | 接近上限时把会话历史摘要，替换旧回合 | 保留请求、关键代码、近期交流；早期详细指令可能丢；可用 `/compact focus on ...`、`/rewind`、`/autocompact`、`/clear` |
| API context editing | 服务端按阈值清除旧 tool results / thinking blocks | 不生成摘要；最旧的先清；可保留最近 N 个 tool 对；可排除某些工具；响应报告 `applied_edits` |
| API server-side compaction | 服务端用 Claude 写的摘要替换旧回合 | 默认 150k input tokens 触发，最低可设 50k；摘要可自定义 instructions；后续请求自动丢弃 compaction block 之前的内容 |
| API memory tool | 客户端执行的 `/memories` 文件工具 | 模型发 `view/create/str_replace/insert/delete/rename`，应用负责存储、路径校验、脱敏、过期 |

**压缩后什么能活下来**（[Explore the context window](https://code.claude.com/docs/en/context-window)）：

- 系统提示、output style 继续生效。
- 项目根 `CLAUDE.md`、无 `paths:` 的 rules、auto memory 从磁盘重新注入。
- skill 描述重建；plan 从磁盘重新注入；git status 刷新。
- `paths:` rules 和子目录 `CLAUDE.md` 按需重新加载。
- 最多重新读取 5 个最近读过/改过的文件；单文件超过 5,000 token 只留路径引用。
- 已调用 skill body 重新注入，但有 5,000 token/个、25,000 token/总预算。
- 后台命令/子代理继续运行；hooks 之前加入的内容随会话一起被摘要。

**压缩不是“删掉旧内容”**，而是“把关键决策、未解决 bug、实现细节保下来，丢掉冗余 tool 输出”。Anthropic 的建议是先把 recall 调高，再优化 precision；最轻的压缩是 tool result clearing。context editing 与 memory tool 设计成配合使用：接近清除阈值时，Claude 会收到提示，先把重要信息写进 memory，再清 tool results。

公开公告给出的内部评估数字：memory tool + context editing 比 baseline 提升 39%，context editing 单独提升 29%；100-turn web search 评估中减少 84% token 消耗（[Managing context](https://www.anthropic.com/news/context-management)）。这些是 Anthropic 内部评估，不是独立基准。

### 1.4 《The components of agent memory》给出的更深一层

2026-11-06 的[这篇文章](https://www.anthropic.com/research/components-of-agent-memory)不是产品文档，但它把“什么算 agent memory”讲清楚了：

- **memory 的定义**：Claude 从经验中获得、跨会话保留、以后能读到的知识；不包括权重更新、单次会话内的 in-context learning、以及 compaction（compaction 是替换旧回合的摘要，不是持久记忆）。
- **salience**：Claude 要判断“未来会不会有用”。不是每个会话都写；写太多会让记忆变成负担。文章里的反例是 Sonnet 3.7 在 Pokémon 里写了 413 个文件/225 个文件夹，只拿到 1 个 badge；Fable 5 只写 9 个文件/2 个文件夹 + 一个 `global.md`，拿到 4 个 badge。原因是前者把每场战斗、每个道具都存档，信息快速过期，Claude 花越来越多时间整理记忆而不是玩游戏。
- **memory hierarchy**：顶层注入、下层按需读/搜；顶层必须小，细节下移并留链接。
- **dreaming**：离线整合。可以拿 transcript 当 ground truth 纠正错误笔记；可以合并重复、用最新值替换过期/矛盾条目；可以构建 wiki 这类可遍历表示；可以把笔记提升到顶层；可以按目标塑形；可以跨多个 session 补链接。
- **steering**：告诉 Claude“记忆是干什么用的”，但不要规定“具体怎么写”。对强模型，固定规则（比如“只记录失败”）反而会削弱记忆带来的提升；对较弱的模型，提示“先读记忆、再显式验证假设”可能大幅提升。
- **评估**：CL-Bench 1.0 数据库任务、Pokémon、350k 文件/420M token 的 wiki、合同条款抽取（共享表 41/57，改成每个合同一页、逐字引用后 57/57）。这些是说明性/内部评估，不是统计基准。
- **开放问题**：什么时候写（当场写会打断任务，后台写又不一定立刻可用）；怎么保持最新（记忆可能一开始就错，也会随环境漂移；全量校验不现实，应按访问频率/易变程度调整 dreaming 节奏）；transcript search 可以作为记忆的基础，但需要 compute 维护表示、防止错误累积。

### 1.5 可以借鉴的七条原则

1. **人类指令与代理学习分开**：稳定的规则放“指令层”，可演化的经验放“记忆层”。不要把两者混成一张 facts 表。
2. **记忆必须可检查、可编辑、可删除**：普通文件/明文、用户能打开看、有来源和时间戳。
3. **顶层索引 + 渐进披露**：启动只注入短索引，细节按需读取；不要把所有 facts 都塞进 system prompt。
4. **压缩 = 摘要 + 重新注入，不是截断**：保留决策、未解决 bug、实现细节；压缩后仍能从磁盘/数据库恢复关键上下文。
5. **代理要有显式记忆操作**：会话中可以主动 search/read/write/forget，而不是只在回合结束后被动抽取。
6. **作用域、来源、版本、审计**：按项目/用户/组织隔离；能回答“这条记忆从哪来、什么时候写的、被谁改过”。
7. **用评估约束记忆质量**：recall、scope leak、stale rate、compaction retention、token cost；不要只验证“功能能跑”。

---

## 2. Nova 当前架构

### 2.1 分层与代码位置

| 层 | 存储/实现 | 写入 | 读取 | 作用域 | 用户可见 |
|---|---|---|---|---|---|
| 原始消息 | `messages` | 每轮持久化 | 最近 12 条 + 历史接口 | session / user | 聊天历史 |
| 会话滚动摘要 | `sessions.summary` + `summary_upto_id` | JobRunner 异步，≥20 条待摘要 | system prompt | session | 间接 |
| 日摘要 | `memory_daily` | 每小时维护循环，昨日 ≥8 条消息 | **不进 prompt** | user / day | 设置页可看/删 |
| 长期事实 | `facts` + `fact_days` | 回合结束后异步抽取 | 每轮 top 8 注入 | **user 全局** | 设置页可看/删 |
| 经验教训 | `lessons` | 每小时，从重试任务/被拒编辑抽取 | 每轮 top 5 注入 | user + 可选 repo | 不可见 |
| 项目大脑 | `repos.brain` | 索引完成后确定性生成 | **不进 prompt**，仅 API/UI | repo | 仓库页 |
| 仓库规则 | `AGENTS.md` / `CLAUDE.md` / `repos.rules` | 用户/仓库维护 | system prompt，≤8,000 字符 | repo | 间接 |
| 代码 RAG | Qdrant + PG 全文，RRF | 索引任务 | 每轮 top 5 注入 | repo / user | 检索卡片 |
| 回合内压缩 | `compact_messages` | 每轮 LLM 调用前 | 原地缩短 messages | 当前 turn | context 事件 |
| 上下文计量 | `context_info` | 每轮 | SSE/历史 | turn | 前端显示 |

主要代码：

- 上下文组装：`backend/app/core/agent/loop.py:139-217`、`backend/app/core/memory/context.py:27-100`
- 持久化与异步任务：`backend/app/core/agent/loop.py:403-472`
- 滚动摘要：`backend/app/core/memory/summary.py:17-102`
- 事实生命周期：`backend/app/core/memory/facts.py:16-251`
- 日摘要：`backend/app/core/memory/daily.py:14-108`
- 回合内压缩：`backend/app/core/agent/context_governor.py:14-97`
- 历史读取：`backend/app/core/memory/session.py:12-14`、`session.py:233-257`
- RAG：`backend/app/core/rag/retriever.py:22-57`
- 记忆 API/UI：`backend/app/api/v1/memory.py:13-68`、`frontend/src/settings/sections/MemorySection.tsx:7-116`
- 仓库规则：`backend/app/core/agent/rules.py:8-55`
- 经验教训：`backend/app/core/reflection/service.py:21-180`

### 2.2 已经做得好的地方

- **多租户隔离**：facts/lessons/memory_daily 都有 `user_id`，RAG 按 owner + repo 过滤，fail-closed；facts 唯一索引从全局 hash 改成 `(user_id, hash)`。
- **三层记忆是真实存在的**：不是只有一张 facts 表；有原始消息、滚动摘要、日摘要、事实、事实出现日期。
- **经验教训来自结果信号**：重试通过的任务、被用户拒绝的编辑，而不是模型自评；这比“让模型总结自己”可靠。
- **混合检索有引用**：dense + keyword + RRF，片段带路径/行号，前端可点。
- **上下文计量**：能告诉用户“这次 prompt 里系统提示/摘要/检索/事实/历史各占多少”，这是做 context engineering 的前提。
- **隐私方向正确**：默认无遥测、BYOK、本地优先；facts 写入和 prompt 注入都做了脱敏，RAG 过滤 secret path。

这些基础不应该推倒重来。下面的问题主要是“生命周期和边界”没设计完，而不是“层数不够”。

### 2.3 两个会直接产生错误答案的 P0

#### P0-1：先截断，后摘要，导致未摘要的消息永久丢失

当前流程：

1. `loop.py:173-176` 调用 `recent_messages(session_id, after_id=summary_upto_id, limit=12)`。
2. `session.py:233-257` 的实现是 `WHERE id > summary_upto_id ORDER BY id DESC LIMIT 12`，再反转。
3. 回合结束后，`loop.py:458-470` 才检查 `is_running()`，且只有待摘要消息 ≥ `SUMMARY_BATCH=20` 才 enqueue。
4. `summary.py:47-102` 要求至少 20 条待摘要消息才真正生成；失败只 `return 0`，没有重试。
5. 回合内如果超预算，`context_governor.py:35-97` 直接截断旧 tool 结果，甚至截断旧的 user/assistant 文本；没有摘要，也不持久化。

具体后果：

- 一个停在 19 条消息的会话，`summary_upto_id=0`，JobRunner 没开：prompt 只带第 8–19 条，第 1–7 条永久丢失，且不会生成摘要。
- 一个 100 条消息的会话，JobRunner 没开：只带最后 12 条，前 88 条丢失。
- 即使 JobRunner 开着，摘要也是“回合结束后”才排队；用户下一轮马上追问早期决策时，摘要可能还没生成。
- 摘要生成失败（LLM 超时、配额、解析失败）时，系统不会告诉用户“这段历史已经丢了”；下一轮仍然只带 12 条。

Anthropic 的对应做法是：接近上限就压缩，压缩后的摘要 + 最近文件/近期回合一起进入新上下文；压缩不是可选的后台美化，而是上下文组装的组成部分。Nova 现在把“压缩”做成了“截断”，把“摘要”做成了“事后异步任务”，两者没有接上。

**建议**：把“历史组装”改成一个 token-aware 的 `build_history(session, budget)`：

- 先算预算，再决定带多少条；不要固定 12。
- 如果 `summary_upto_id` 之后的消息已经超过预算，先同步生成/更新摘要（或至少生成一个确定性的“决策/文件/待办”提取），再截断。
- 摘要失败时，宁可多带原文/降低检索预算，也不要静默丢弃。
- 把每次压缩的输入范围、输出摘要、节省 token 写入 `compaction_records`，下一轮优先注入；前端显示“已压缩”事件。
- 回合内压缩也走同一套：先清 tool 原始输出，再摘要旧回合，最后才考虑缩短文本；最新用户请求永不截断。

验收：100 条消息、JobRunner 关闭的会话，仍能答出第 1 条消息里的关键决策；19 条消息的会话不丢前 7 条；摘要失败有可见告警和重试。

#### P0-2：长期事实只有 user 作用域，产品模式/项目/仓库会串味

当前 `facts` 表只有 `user_id`（`init_db.py:326-345`），没有 `scope_type/scope_id`、`product_mode`、`repo_id`、`thesis_project_id`。读取时 `facts.py:139-174` 只按 `user_id` 查；写入时 `facts.py:71-126` 也只带 `user_id`。

同时：

- `loop.py:451-457` 明确把 thesis 轮次排除在事实抽取之外，注释写的是“等 facts 有 product-mode scope 再做，否则论文文本会被 dev 会话召回”。
- `daily.py:39-47` 的日摘要按 `user_id` + 日期查所有 session，不区分 dev/thesis，也不区分项目。
- `memory_daily` 主键是 `(user_id, day)`，没有 scope。

具体后果：

- 用户在 dev 会话说“这个仓库用 pnpm”，去论文会话会被注入“这个仓库用 pnpm”这类无关事实；反过来，论文里的“参考文献用 GB/T 7714”“第 3 章方法用某模板”永远不会被记住，因为 thesis 轮次根本不抽取。
- 用户有多个仓库时，A 仓库的构建命令/测试习惯会进入 B 仓库的 prompt。
- 日摘要把 dev 和 thesis 混在一起，用户回看时无法区分，也无法按项目删除。
- 这不是“召回不准”，而是**产品边界泄漏**；在论文场景还可能把 dev 的写作偏好带进论文，违反“论文与开发分离”的设计意图。

Anthropic 的对应做法是：auto memory 按 git 仓库一个目录；子代理有独立 `memory` scope；Managed Agents 的 memory store 是 workspace-scoped，支持不同 access scope。原则是**按最小稳定边界隔离**，而不是所有东西都挂 user。

**建议**：

- facts 增加 `scope_type`（`global` / `repo` / `thesis_project` / `document` / `session`）和 `scope_id`；`global` 只放真正跨项目的用户偏好（语言、回答风格、常用工具）。
- 抽取时由 session 传入 scope：dev session 写 `repo:<id>`，thesis session 写 `thesis_project:<id>`；不确定时写 `global` 但降低置信度。
- 读取时过滤：`scope_type='global' OR (scope_type=:current_type AND scope_id=:current_id)`；不要把 thesis scope 的事实注入 dev，反之亦然。
- `memory_daily` 增加 `scope_type/scope_id`，或改成按 session/product_mode 聚合；UI 按 scope 分组。
- 迁移时把现有 facts 标成 `global` 或按最近来源 session 推断；不要直接丢弃。
- 加一组“scope leak”集成测试：dev 事实不出现在 thesis prompt，thesis 事实不出现在 dev prompt，A 仓库事实不出现在 B 仓库。

### 2.4 生命周期与检索的五个具体问题

#### (1) TTL 与衰减的数学不一致

`facts.py:16-21`：`DEFAULT_TTL_DAYS=90`，`DECAY_IDLE_DAYS=7`，`DECAY_AMOUNT=0.01`，`MIN_IMPORTANCE=0.1`。

`run_cleanup()` 同时做两件事：

- 7 天未用后，每小时 `importance -= 0.01`；降到 0.1 就删除。
- `created_at + ttl_days < now()` 也删除。

从 1.0 降到 0.1 需要 90 次衰减 = 90 小时 = 3.75 天；加上 7 天空闲阈值，**一条完全未用的事实大约 10.75 天就会消失**，而不是 90 天。若它被晋升到 1.3，约 12 天。另一方面，TTL 用的是 `created_at`，一条每天都被使用的事实到 90 天仍会被删。用户看到的“90 天 TTL”与实际行为不一致。

**建议**：明确产品语义，二选一：

- TTL 表示“最后使用后保留 N 天”：用 `GREATEST(created_at, last_used_at) + ttl_days`；衰减用半衰期而不是每小时固定值。
- 或者 TTL 表示“绝对保留期”，那就不要在 TTL 前用 importance 衰减删除；把“低价值清理”和“到期清理”分开，并在 UI 显示原因。

#### (2) 检索会给事实“自我强化”

`get_relevant_facts()` 每次被选中后执行 `importance = LEAST(importance + 0.1, 2.0)`（`facts.py:166-173`）。每轮最多 8 条，一条事实被选中 10 次就到 2.0。结果是：

- 经常被检索的事实越来越重要，即使它已经过时。
- 排序变成“谁被选过谁更靠前”，而不是“谁更相关/更可信”。
- 与 TTL 的删除逻辑叠加，容易出现“老事实一直活着，新事实进不了 top 80”。

**建议**：区分“相关性”和“重要性”。检索命中不应直接提升重要性；只有“被回答实际引用/用户确认/跨天重复出现”才提升。可以记录 `last_cited_at`、`cite_count`，用半衰期衰减；对“只是被放进 top 8”的情况不加分，或加很小的分并设上限。

#### (3) 语义去重命中后不强化、不合并

`facts.py:41-56` 的 `_is_semantic_duplicate()` 找到相似事实时直接返回 `True`；`add_fact()` 随后 `return False`（`facts.py:103-104`），既没有更新已有事实的 `last_used_at`，也没有记录 `fact_days`，更没有合并内容。结果是：

- 用户换一种说法重复同一偏好，系统认为“重复，丢弃”，但旧事实没有得到任何强化。
- 旧事实可能因为长期未用而衰减，新表述又进不来，最后这条偏好消失。
- 相似但不等价的事实（“用 pnpm” vs “用 npm”）可能被 0.92 阈值误判为重复，直接丢掉新信息。

**建议**：语义命中时更新已有事实（`last_used_at`、`fact_days`、`importance`），并比较内容：如果新内容包含旧内容没有的约束，合并或新建带 `supersedes_id` 的版本；如果明显矛盾，进入冲突处理，而不是静默丢弃。

#### (4) 500 条上限是“停止学习”，不是“淘汰”

`facts.py:91-94`：达到 `MAX_FACTS_PER_USER=500` 后直接 `return False`，不淘汰低价值事实。活跃用户会在某个时刻突然发现“新偏好记不住了”，而且没有任何提示。

**建议**：达到上限时按“低重要性 + 长期未用 + 未晋升”淘汰一条，或把多条同主题事实合并成一条摘要；至少记录 `facts_cap_reached` 并在 UI 提示。

#### (5) 候选集先按 importance 取 top 80，语义排序可能永远看不到相关事实

`facts.py:143-147` 先 `ORDER BY importance DESC, last_used_at DESC LIMIT 80`，再在这 80 条里做语义排序。一个刚写入、importance 只有 1.0、但和当前问题高度相关的事实，如果前面有 80 条 importance 1.1–2.0 的老事实，就根本进不了候选集。

**建议**：候选集改为“向量/关键词召回 + 重要性/新近度”混合，而不是先截断再语义排序；至少把 `importance` 排序改成 `last_used_at` + 分层抽样，保证新事实有机会进入候选。长期看，facts 应进 pgvector 或 Qdrant，而不是在 Python 里对 80 条 JSONB embedding 算 cosine。

### 2.5 其他结构性问题

| 问题 | 证据 | 影响 |
|---|---|---|
| 回合内压缩是截断，不是摘要 | `context_governor.py:67-91`：旧 tool 结果留 head/tail，旧 user/assistant 文本也留 500/500；没有 LLM 摘要，不持久化 | 长任务中段的决策、约束、失败原因可能被删；下一轮无法恢复 |
| 压缩不可观测、不可恢复 | `loop.py:543-557` 只记录 before/after/saved；没有压缩摘要/范围记录 | 用户不知道发生了什么；无法审计“为什么忘了” |
| 日摘要写而不读 | `daily.py` 只生成；全仓库只有 `memory.py` 和 cleanup 读 `memory_daily`，`loop.py` 不注入 | 花了 LLM token，却没有产品价值；应要么检索，要么停掉 |
| 项目大脑不注入 | `repos.brain` 只在索引/API 使用，`loop.py` 不读 | 一个低成本、高信号的项目记忆资产被浪费 |
| facts 没有来源/置信度/编辑 | `facts` 表无 source/confidence；`memory.py` 只有 GET/DELETE；UI 只有删除 | 用户无法判断“它为什么记得这个”，也无法纠正错误记忆 |
| 没有冲突/版本 | 只有 hash + cosine 去重；无 `supersedes_id`/`status` | 矛盾事实会共存；模型可能任选一条 |
| 没有记忆评估 | 测试覆盖功能，没有 recall/leak/stale/compaction 指标 | 无法知道“记忆变好还是变坏” |
| 原始消息/摘要输出/lessons 未统一脱敏 | `session.add_message` 原样存；`summary.py`/`daily.py` 对输入脱敏但输出不再脱敏；`reflection/service.py:73` 只截断不脱敏 | 密钥/隐私可能落到 messages、tool_json、lessons、摘要 |
| 没有用户级记忆设置 | 无 auto memory 开关、保留期、scope、do-not-remember | 用户无法控制“记什么、记多久、给哪个项目用” |
| 没有跨会话 episodic 检索 | 只有当前 session 最近 12 条 + facts；没有“上次那个会话怎么决定”的检索 | 长项目/多会话决策容易断片 |
| 子代理没有持久记忆 | `spawn_agents` 只读、每次全新上下文 | 重复的审查/调研经验无法积累 |

---

## 3. 差距矩阵

| 维度 | Anthropic 公开做法 | Nova 现状 | 影响 | 优先级 |
|---|---|---|---|---|
| 人类指令 vs 自动学习 | `CLAUDE.md`/rules 与 auto memory 分开 | 只有 repo rules + 自动 facts；没有用户级指令层 | 用户无法稳定表达“永远这样做” | P1 |
| 作用域 | 按 repo / subagent / workspace 隔离 | facts 仅 user 级；日摘要混所有模式 | 跨项目/跨产品串味 | **P0** |
| 顶层索引 | `MEMORY.md` 200 行/25KB + 主题文件按需 | facts 平铺，检索 top 8；无索引/主题 | 规模上来后召回差、prompt 膨胀 | P1 |
| 写入入口 | 会话中显式 memory tool + 回合后 auto memory | 只有回合后异步抽取；模型不能主动记 | 用户说“记住这个”无法可靠生效 | P1 |
| 更新/冲突 | 文件可编辑；Managed memory 有版本/redact；dreaming 合并 | 只有 hash/cosine 去重；无版本/冲突 | 矛盾记忆共存，错误难纠正 | P1 |
| 遗忘/保留 | 用户可删；无内建 TTL；应用可做 expiration | TTL 90 天 vs 有效 ~11 天；无用户控制 | 行为与承诺不一致 | **P0** |
| 压缩 | 摘要 + 重注入；tool result clearing；保留近期文件 | head/tail 截断；无摘要/记录 | 长任务丢决策 | **P0** |
| 压缩后恢复 | 从磁盘重注入 CLAUDE.md/auto memory/plan/文件 | 只靠下一次异步摘要 | 压缩后上下文断裂 | **P0** |
| 会话摘要可靠性 | 自动压缩是主路径；失败有边界/错误 | 依赖 JobRunner；<20 条不摘要；失败静默 | 13–19 条会话也会丢历史 | **P0** |
| 检索 | 文件系统 just-in-time；wiki + search | 混合 RAG，但 top_k 实际 5；facts 候选 top 80 | 召回受限，相关新事实进不来 | P1 |
| 日摘要/ episodic | auto memory 不按天；transcript 可检索 | 日摘要写而不读；无跨会话检索 | 成本高、价值低 | P1 |
| 项目记忆 | CLAUDE.md + auto memory + repo 文件 | 有 repo brain 但不注入 | 浪费低成本高信号资产 | P1 |
| 可观测/审计 | `/context`、`/memory`、Saved/Recalled、版本/审计 | context meter 有；记忆来源/使用不可见 | 用户无法信任/纠错 | P1 |
| 评估 | 内部评估 + 任务指标；文章给开放问题 | 无记忆专项 eval | 无法量化改进 | P1 |
| 安全/多租户 | 路径校验、workspace trust、SDK 隔离警告 | 多租户 SQL 隔离好；原始消息/lessons 脱敏不全 | 隐私风险 | P1 |
| 子代理记忆 | `memory: user/project/local` | 无 | 重复经验不积累 | P2 |

---

## 4. 改进建议

### P0：先修正确性（建议 1–3 天）

#### P0-A. Token-aware 历史组装，摘要先于截断

- **改什么**：新增 `build_history(session, budget)`，替代 `recent_messages(..., limit=12)` 的固定截断。
- **怎么做**：
  1. 按 token 预算从新到旧装消息；保留最后一条 user 消息和最近的 tool-call 配对。
  2. 如果剩余消息装不下且没有覆盖它们的摘要，同步调用摘要（可设超时/降级为确定性提取）；摘要成功后再截断。
  3. 摘要失败时，优先保留原文并压缩 RAG/facts 预算，不静默丢历史。
  4. 把 `summary_upto_id`、摘要、覆盖范围写入 compaction 记录。
- **涉及**：`backend/app/core/memory/session.py`、`summary.py`、`backend/app/core/agent/loop.py`、`context_governor.py`、`backend/app/core/jobs/service.py`。
- **验收**：19 条消息不丢前 7 条；100 条消息 + JobRunner 关闭仍能答出早期决策；摘要失败有告警；新增单测覆盖 12/13/19/20/100 条边界。

#### P0-B. 给 facts 和日摘要加作用域

- **改什么**：`facts` 增加 `scope_type`、`scope_id`、`source_session_id`、`source_message_id`、`confidence`；`memory_daily` 增加 `scope_type`、`scope_id`。
- **怎么做**：
  1. 迁移：现有 facts 默认 `global`，或按最近来源 session 推断 repo/thesis；不要删数据。
  2. 抽取：`extract_facts_from_turn` 接收 scope；dev 写 repo scope，thesis 写 thesis_project scope，纯用户偏好写 global。
  3. 读取：`get_relevant_facts(user_id, query, scope)` 过滤 global + 当前 scope；禁止跨 scope。
  4. 日摘要：按 scope 聚合；UI 按 scope 分组。
- **涉及**：`backend/app/db/init_db.py`、`backend/app/core/memory/facts.py`、`daily.py`、`backend/app/core/agent/loop.py`、`memory.py`、`MemorySection.tsx`。
- **验收**：dev/thesis/仓库 A/仓库 B 四组 scope leak 测试全为 0；thesis 偏好能在 thesis 会话召回；用户删除某 scope 的记忆不影响其他 scope。

#### P0-C. 把回合内压缩改成“可恢复的压缩”

- **改什么**：`compact_messages` 从“截断”升级为“两阶段压缩”。
- **怎么做**：
  1. 第一阶段只清旧 tool 原始输出，保留 tool 名称/参数/路径/退出码等引用。
  2. 第二阶段在超预算时调用 LLM 生成结构化摘要：目标、已确认决策、未解决 bug、改动文件、下一步；保留最近 N 轮原文。
  3. 摘要写入 `compaction_records`（session/turn/范围/摘要/节省 token），下一轮注入；SSE 发 `context_compacted` 事件。
  4. 最新 user 消息、当前计划、安全约束永不截断。
- **涉及**：`context_governor.py`、`loop.py`、`init_db.py`、前端 context 展示。
- **验收**：100 轮工具调用的长任务，压缩后仍能说出中段决策和未解决 bug；压缩记录可查；下一步计划不丢。

#### P0-D. 异步抽取/摘要改成可重试的持久任务

- **改什么**：去掉 `asyncio.create_task` 的 fire-and-forget，改为 JobRunner/outbox。
- **怎么做**：
  1. `facts.extract_facts_from_turn` 通过 `jobs` 表入队，带 `session_id/turn_id/user_message_id` 幂等键。
  2. 失败重试（指数退避），记录 attempt/error；超过上限进 dead-letter，UI 可重试。
  3. 摘要任务同样；JobRunner 未运行时，至少保留任务记录，启动后补跑。
  4. 指标：extraction_enqueued/succeeded/failed、summary_lag、summary_failures。
- **涉及**：`backend/app/core/agent/loop.py`、`backend/app/core/jobs/*`、`facts.py`、`summary.py`。
- **验收**：回合结束后 kill 进程，重启后抽取/摘要仍完成；不产生重复事实；失败可见。

#### P0-E. 修生命周期与检索的五个 bug

- **改什么**：TTL/衰减语义、检索加分、语义去重强化、500 上限淘汰、候选集召回。
- **怎么做**：
  1. TTL 用 `GREATEST(created_at, last_used_at)` 或明确“绝对到期”；衰减改半衰期，避免 ~11 天误删。
  2. 检索不直接 +0.1；记录 `last_cited_at/cite_count`，只对实际引用/用户确认加分。
  3. 语义去重命中时更新已有事实的 `last_used_at/fact_days`，并按内容决定合并/新版本/冲突。
  4. 达到 500 时淘汰低价值事实或合并同主题，不要静默停止学习。
  5. 候选集改为向量/关键词召回 + 重要性/新近度，不要先按 importance 截 80。
- **涉及**：`facts.py`、`init_db.py`、`backend/app/core/rag/*`。
- **验收**：TTL/衰减/去重/上限/候选集各有单测；90 天未用事实的实际行为与 UI 文案一致；重复表述能强化旧事实。

#### P0-F. RAG `top_k` 与实际注入一致

- **改什么**：`retriever.py:55` 的 `top_n=min(5, top_k)` 改成按调用方 `top_k` 和 token 预算决定，不要硬编码 5。
- **怎么做**：加 token 预算/MMR/去重；如果索引 embedding 有上限（`config.py:138` 的 `index_embed_max_chunks=3000`），在 repo status 里显示“部分索引”，不要显示 ready 却只索引了一部分。
- **验收**：`top_k=8` 时最多返回 8 条（受预算约束）；索引截断可见；检索评估集有 baseline。

### P1：把记忆变成可用的产品能力（建议 3–7 天）

#### P1-A. 记忆索引 + 按需读取

- 给 facts 增加 `topic`、`one_line`、`status`；生成一个紧凑的“记忆索引”区块（每条一行，带 id/scope），只注入高价值条目（例如 ≤40 行）。
- 详情不直接进 prompt；提供 `memory_search` / `memory_read` 工具，模型需要时按 id/topic 读取。
- 这相当于 Nova 版的 `MEMORY.md` + topic files，但底层仍是 PostgreSQL，不需要改成文件系统。
- 验收：facts 增长到 500 条时，system prompt 的记忆区块仍有界；模型能按需读到详情；索引不重复注入。

#### P1-B. 来源、编辑、纠错

- facts 增加 `source_session_id/source_message_id/source_type/confidence/extractor_version`。
- API：`POST /memory/facts`（显式记住）、`PATCH /memory/facts/{id}`（编辑/固定/降权）、`DELETE` 保留；`GET /memory/facts/{id}/sources`。
- UI：按 scope/type 分组；显示来源会话/消息、创建/最后使用时间、为什么被召回；支持“记住这个”“忘掉这个”“别再提这个”。
- 对话流：保存/召回时显示 “Saved 2 memories” / “Recalled 3 memories”，可展开。
- 验收：用户能纠正一条错误记忆并在下一轮生效；每条注入事实都能回溯到来源。

#### P1-C. 冲突、版本与夜间整合

- facts 增加 `status`（active/superseded/archived）、`supersedes_id`、`version`。
- 写入时同 scope/topic 高相似但内容冲突 → 不静默丢弃，标记冲突；优先保留新值，旧值标 superseded，保留历史。
- 夜间维护增加“整合”步骤：合并重复、把同主题事实归纳成一条、用最近 transcript 校验高风险事实、把稳定事实提升到索引层。
- 不建议一上来做全自动 dreaming；先做确定性合并 + 人工可见的冲突队列，再考虑 LLM 校验。
- 验收：矛盾事实不再共存；用户能看到“旧值 → 新值”；整合任务可回滚。

#### P1-D. 日摘要：要么检索，要么停掉

- 如果保留：在“昨天/上次/之前”类问题中检索最近 N 天日摘要；提供 `memory_search` 覆盖日摘要；按 scope 分组。
- 如果暂时不做检索：把日摘要生成改为可选/按需，避免每天为所有用户花 LLM token。
- 验收：用户问“我们昨天做到哪了”能拿到日摘要；或者日摘要不再默认生成，成本下降。

#### P1-E. 项目大脑进 prompt

- 在 dev 会话中注入一个很短的“项目大脑”区块：入口文件、热点文件、阅读顺序、主要语言/框架；不注入完整 JSON。
- 这是确定性生成、零 LLM 成本的 repo memory，比让模型每次重新检索更便宜。
- 验收：新会话第一轮就能说出项目入口和关键目录；项目大脑区块 token 占用可计量。

#### P1-F. 记忆评估集

- 建一个 golden set：真实/合成会话 + 问题 + 期望事实/决策。
- 指标：
  - `recall@8`：该召回的事实是否进 top 8。
  - `scope_leak`：dev/thesis/repo A/repo B 交叉注入数，目标 0。
  - `stale_rate`：被注入的过期事实比例。
  - `duplicate_rate`：语义重复事实比例。
  - `compaction_retention`：压缩后关键决策保留率。
  - `memory_token_share`：记忆区块占 prompt 比例。
- 在 CI 跑快速子集；完整评估离线跑。
- 验收：每次改记忆逻辑都有 before/after 数字，而不是只跑功能测试。

#### P1-G. 脱敏、导出、删除全部

- 原始消息入库前做可配置脱敏（至少对已知密钥/token 模式）；`tool_json`、摘要输出、lessons 统一过 `redact_text`。
- 提供 `GET /memory/export`（JSON/Markdown）和 `DELETE /memory/all`（按 scope 或全部），并写审计。
- 如果部署在多用户环境，考虑 PostgreSQL 磁盘加密或应用层加密；至少不要让明文密钥进 facts/messages。
- 验收：脱敏测试集 0 泄漏；导出包含来源；删除全部后 facts/daily/lessons/messages 均不可召回。

#### P1-H. 用户记忆设置

- 设置页：auto memory 开关、保留期、默认 scope、禁止记忆的类别/关键词、导出/删除。
- 项目级覆盖：某个 repo/thesis project 关闭自动记忆，或只允许显式记忆。
- 验收：关闭后新事实不再写入；已有记忆不被注入；用户能查看当前策略。

### P2：差异化与规模化（建议 2–4 周，按产品需要）

1. **分层指令**：增加用户级 instructions（类似 `~/.claude/CLAUDE.md`）、项目级 rules、组织级 policy；支持 `paths:` 作用域，只在相关文件被读写时注入。
2. **跨会话 episodic 检索**：对 messages/session summaries 做全文/向量检索，回答“上次我们怎么决定的”，带 session/message 引用。
3. **离线整合 / dreaming**：夜间任务合并重复、纠正漂移、生成主题 wiki/索引、提升稳定事实；高风险修改进人工队列。参考 Anthropic 的 transcript-as-ground-truth 和“顶层保持小”的原则。
4. **子代理记忆**：给重复出现的 review/research 子代理独立 scope（user/project/local），只让子代理读自己的记忆，主会话不自动继承。
5. **pgvector/ANN**：facts 和 session summaries 进向量索引；不要在 Python 里对 JSONB 做全量 cosine。
6. **团队记忆 store**：如果未来做团队版，增加 workspace-scoped store、权限、版本、审计、redact；这对应 Anthropic Managed Agents 的 memory store，而不是现在的单用户 facts。
7. **多代理写入冲突**：一个主题一个 writer，或按 contract/事实分片+逐字引用；Anthropic 的合同抽取实验里，共享表 41/57，分片后 57/57。
8. **记忆投毒防护**：把记忆当不可信上下文，标注来源/置信度；安全策略、权限、工具调用审批不能被记忆覆盖；对高风险记忆（部署、密钥、权限）要求用户确认。

---

## 5. 建议落地顺序

| 阶段 | 目标 | 主要工作 | 完成标志 |
|---|---|---|---|
| Sprint 1（P0，1–3 天） | 不再丢历史、不再串味 | token-aware 历史组装；facts/daily scope 迁移；压缩记录；持久化抽取/摘要；TTL/衰减/去重/上限修复；RAG top_k | 100 条会话 + JobRunner 关闭仍可答早期决策；scope leak=0；生命周期单测全过 |
| Sprint 2（P1，3–7 天） | 记忆可见、可纠错、可评估 | 记忆索引 + `memory_search/read`；来源/编辑/固定/忘记；冲突/版本；日摘要检索或停用；项目大脑注入；eval harness；脱敏/导出/删除全部；设置页 | 用户能纠正错误记忆；每条注入事实可回溯；eval 有 before/after；导出/删除可用 |
| Sprint 3（P2，按需） | 规模化与差异化 | 分层指令；跨会话 episodic 检索；夜间整合；子代理记忆；pgvector；团队 store；投毒防护 | 多项目/多用户下召回稳定；整合可审计；团队隔离通过 |

**依赖关系**：P0-B（scope）应先于 P1-A（索引）和 P1-C（冲突），否则索引和冲突处理会建在错误的作用域上。P0-A/C（压缩）应先于 P1-F（eval），否则评估的是旧链路。P1-G（脱敏）可以和 P0 并行，但上线前必须完成。

---

## 6. 不建议照搬的部分

- **不要把 PostgreSQL 换成 Markdown 文件系统**。Claude Code 是本地单机产品，文件系统天然合适；Nova 是多用户 Web/桌面服务，数据库在事务、隔离、并发、备份上更强。要抄的是“索引 + 按需读取 + 可编辑”的语义，不是存储介质。
- **不要重新引入 Neo4j / 记忆图谱**。项目已经明确删过图谱层；当前问题不是“关系不够”，而是作用域、压缩和生命周期没做好。
- **不要每个回合都抽取事实**。Anthropic 明确说不是每个会话都写；过度抽取会让记忆变成噪声和成本。加 salience gate（显式偏好/决策/纠正才写），比提高抽取上限更重要。
- **不要让记忆覆盖安全策略/权限**。记忆是 context，不是 enforced configuration；部署、密钥、权限、论文合规规则必须由代码/审批强制，不能被一条“记住：以后直接部署”绕过。
- **不要把 dev 和 thesis 混在一个记忆池**。这是产品边界，不是召回精度问题；必须 scope 隔离。
- **不要承诺“记忆一定准确”**。Anthropic 自己把错误记忆、漂移、投毒列为开放问题；Nova 应提供来源、编辑、删除、评估，而不是宣称不会忘/不会错。
- **不要用记忆功能绕过论文合规**。论文场景的记忆只能帮助保持用户已确认的题目、阶段、引用条目和写作偏好；不能用于代写提交、降重、伪造引用/数据或规避 AIGC 检测。

---

## 7. 验收指标（建议目标，不是当前实测）

| 指标 | 目标 | 说明 |
|---|---|---|
| 未摘要历史丢失 | 0 条 | 13/19/100 条会话边界测试 |
| scope leak | 0 | dev/thesis/repo A/repo B 交叉注入 |
| 压缩后关键决策保留 | ≥ 90% | golden set 中决策/未解决 bug/下一步 |
| 事实召回 recall@8 | 比当前 baseline +10% | 同一 golden set |
| 过期事实注入率 | < 5% | 人工标注 stale |
| 语义重复率 | < 2% | 抽样 |
| 记忆 token 占 prompt | ≤ 15% | context meter |
| 抽取成功率 | ≥ 99% | 含重试；失败可见 |
| 脱敏泄漏 | 0 | 密钥/token 测试集 |
| 用户纠错生效 | 下一轮生效 | 编辑/删除/固定 |
| 导出/删除全部 | 完整 | 覆盖 facts/daily/lessons/messages |

这些目标应在 Sprint 1/2 的 eval harness 中固化；没有测量之前，不要对外宣称“记忆架构升级完成”。

---

## 8. 代码证据索引

| 位置 | 事实 |
|---|---|
| `backend/app/db/init_db.py:326-345` | `facts` 只有 `user_id`，无 scope/source/confidence/status |
| `backend/app/db/init_db.py:347-357` | `memory_daily` 主键 `(user_id, day)`，无 scope |
| `backend/app/db/init_db.py:825-843` | `lessons` 有 repo_id/source_type/source_id，但无消息级来源/脱敏 |
| `backend/app/core/agent/loop.py:139-149` | RAG 调用 `top_k=8` |
| `backend/app/core/agent/loop.py:167-176` | facts + `recent_messages(limit=12)` |
| `backend/app/core/agent/loop.py:191-196` | 系统提示只注入 summary/rules/hits/facts |
| `backend/app/core/agent/loop.py:403-470` | 持久化、lessons 计分、thesis 排除、异步抽取、摘要入队 |
| `backend/app/core/agent/loop.py:543-557` | 回合内压缩只记录 before/after/saved |
| `backend/app/core/memory/session.py:12-14` | `HISTORY_LIMIT=12`、`ARCHIVE_THRESHOLD=30`（未使用） |
| `backend/app/core/memory/session.py:233-257` | 固定 limit 的最近消息读取 |
| `backend/app/core/memory/summary.py:17-20` | 保留 8 条、20 条一批、40 行/2000 字 |
| `backend/app/core/memory/summary.py:47-102` | 摘要依赖 JobRunner；失败返回 0 |
| `backend/app/core/memory/daily.py:14-16` | 日摘要阈值/长度 |
| `backend/app/core/memory/daily.py:39-47` | 按 user + 日期跨所有 session 取消息 |
| `backend/app/core/memory/daily.py:50-108` | 日摘要生成；不注入 prompt |
| `backend/app/core/memory/facts.py:16-21` | TTL 90 天、7 天衰减、0.01/小时、最小 0.1、上限 500 |
| `backend/app/core/memory/facts.py:41-56` | 语义去重只查最近 80 条 |
| `backend/app/core/memory/facts.py:71-126` | 写入；语义重复直接丢弃；500 上限直接拒绝 |
| `backend/app/core/memory/facts.py:139-174` | 先取 importance top 80，再语义排序；命中 +0.1 |
| `backend/app/core/memory/facts.py:177-222` | 回合后抽取；best-effort |
| `backend/app/core/memory/facts.py:225-251` | TTL/衰减/晋升 |
| `backend/app/core/agent/context_governor.py:14-19` | 0.8 预算、保留最近 8 条、head/tail 常量 |
| `backend/app/core/agent/context_governor.py:35-97` | 截断 tool 输出/旧文本；无摘要/持久化 |
| `backend/app/core/memory/context.py:42-50` | 会话摘要注入 |
| `backend/app/core/memory/context.py:63-70` | 仓库规则注入 |
| `backend/app/core/memory/context.py:72-90` | RAG 片段注入 |
| `backend/app/core/memory/context.py:92-98` | facts 注入 |
| `backend/app/core/rag/retriever.py:55` | 最终 `min(5, top_k)`，实际最多 5 条 |
| `backend/app/core/agent/rules.py:8-10` | 规则单仓库 4000 字符/总 8000 字符 |
| `backend/app/core/reflection/service.py:21-23` | lessons 每次最多 6 条、注入 5 条、80 字 |
| `backend/app/core/reflection/service.py:73` | lesson 只截断，不脱敏 |
| `backend/app/core/reflection/service.py:171-180` | lessons 过期/低命中删除 |
| `backend/app/api/v1/memory.py:13-68` | 只有列表/删除，无编辑/搜索/来源 |
| `frontend/src/settings/sections/MemorySection.tsx:7-116` | 记忆 UI 只读/删除，无编辑/来源/scope |
| `docs/DESIGN.md:253-260` | 设计文档只定义两层记忆 |
| `docs/DESIGN.md:851-879` | 三层记忆与已知边界：矛盾检测未自动化、日摘要不改写 |
| `docs/BLUEPRINT-GAP-AND-ROADMAP.md:442-452` | B7 计划包含来源链接/矛盾检测，尚未落地 |

---

## 9. 参考来源

**Claude Code 产品**

- [How Claude remembers your project](https://code.claude.com/docs/en/memory) — CLAUDE.md/AGENTS.md/rules、auto memory、MEMORY.md、200 行/25KB、四类笔记、子代理记忆。
- [Explore the context window](https://code.claude.com/docs/en/context-window) — 压缩后保留什么、`/compact`、`/autocompact`、`/clear`、子代理隔离。
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) — 每会话新上下文、自动压缩、压缩可能丢早期指令。
- [Subagents](https://code.claude.com/docs/en/sub-agents#enable-persistent-memory) — 子代理 `memory: user/project/local`。

**Claude API / Agent SDK**

- [Memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) — `/memories`、六个命令、客户端执行、路径校验、与 context editing 配合。
- [Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing) — tool result/thinking clearing、触发/保留/排除、`applied_edits`。
- [Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction) — on-demand / threshold / background；server-side 摘要。
- [Compaction at a token threshold](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold) — 默认 150k、最低 50k。
- [Agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop) — SDK 自动压缩、`compact_boundary`、`PreCompact`。
- [Managing context on the Claude Developer Platform](https://www.anthropic.com/news/context-management) — 2025-09-29 发布；39% / 29% / 84%。
- [Memory for Claude Managed Agents](https://claude.com/blog/claude-managed-agents-memory) — workspace-scoped store、权限、审计、版本、redact、导出。
- [Using agent memory](https://platform.claude.com/docs/en/managed-agents/memory) — memory store 挂载、不可变版本、并发。

**Anthropic Engineering**

- [The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory) — 2026-11-06；memory 定义、salience、dreaming、wiki、CL-Bench/Pokémon/合同评估、开放问题。
- [Effective context engineering for AI agents](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) — compaction、structured note-taking、sub-agents、just-in-time retrieval。
- [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) — initializer/coding agent、progress file、feature list、git、端到端验证。
- [Harness design for long-running application development](https://www.anthropic.com/research/harness-design-long-running-apps) — context reset vs compaction、structured handoff。
- [How we built our multi-agent research system](https://www.anthropic.com/research/multi-agent-research-system) — 子代理隔离、外部 artifact、token 成本。

**本仓库**

- [`docs/research/2026-11-22-claude-code-memory.md`](research/2026-11-22-claude-code-memory.md) — 本次调研的完整一手资料笔记与来源表。
- [`docs/DESIGN.md`](DESIGN.md) — Nova 现有记忆设计与已知边界。
- [`docs/BLUEPRINT-GAP-AND-ROADMAP.md`](BLUEPRINT-GAP-AND-ROADMAP.md) — B7 三层记忆计划。

> 说明：`platform.claude.com` 的 HTML 文档在本地网络会被地区重定向，API 正文通过 Anthropic 官方 `llms-full.txt` 汇总读取；Claude Code 文档使用 `code.claude.com` 的原始 Markdown。具体取读日期与来源 ID 见研究底稿。

---

## 10. P0 实施状态（2026-11-22）

| 项 | 状态 | 落地 |
|---|---|---|
| P0-A 历史/压缩顺序 | 已实现 | `session.build_history` 按 token 预算选历史；超预算先 `maybe_summarize(force=True)`；失败时保留最新消息并显式提示省略数量 |
| P0-B 记忆作用域 | 已实现 | 迁移 27；facts 作用域 + 来源 + 置信度；daily 作用域；loop 按产品/仓库读取与写入；API/设置页支持过滤 |
| P0-C 可恢复压缩 | 已实现 | `memory/compaction.py` 先摘要后截断；`compaction_records` 持久化并在本轮/下一轮注入；新增审计 API |
| P0-D 持久后台任务 | 已实现 | `facts_extract` Job、摘要重试与幂等键、指数退避 `available_at`、runner 不可用时的受控回退 |
| P0-E 生命周期/检索 | 已实现 | TTL 从最后使用起算；按天衰减；检索不提升重要性；语义去重强化；上限淘汰；候选集扩大 |
| P0-F RAG top_k | 已实现 | 按调用方 `top_k` 返回；索引截断写入 `stats.embed_truncated` 并告警 |

设计与实现细节见 [`docs/DESIGN.md`](DESIGN.md) §39。新增测试集中在 `test_memory_scope.py`、`test_memory_compaction.py`、`test_memory_summary.py`、`test_facts.py`、`test_memory_daily.py`、`test_jobs.py`、`test_retriever.py`、`test_local_retrieval.py`。验证结果：后端 1423 passed / 12 skipped，ruff、前端构建与契约检查、scripted eval 全部通过。

已在后续批次补齐：pgvector 事实召回（可选扩展 + JSONB 回退）、显式稳定的 global 偏好自动学习、仓库级日摘要与回溯注入、事实编辑/归档/版本/冲突替代、记忆评估集（`evals/memory_eval.py`，已进 `scripts/check.sh`）。设计与边界见 [`docs/DESIGN.md`](DESIGN.md) §40。补齐后全量回归：后端 1455 passed / 12 skipped，ruff、前端构建与契约检查、记忆评估通过。

再补齐 P1 产品能力（2026-11-22，迁移 29）：记忆索引 + `memory_search/read` 工具、对话内 Saved/Recalled 提示、日摘要检索、确定性夜间去重整合、项目大脑注入 dev prompt、统一脱敏与导出/删除全部、用户级记忆策略 API 与设置页（自动记忆、保留天数、默认作用域、屏蔽类别/关键词、作用域覆盖）。设计与边界见 [`docs/DESIGN.md`](DESIGN.md) §41；新增 `test_memory_policy.py`、`test_memory_index.py`、`test_memory_consolidation.py`、`test_memory_api_extra.py`、`test_repo_brain_prompt.py`。全量回归：后端 **1497 passed / 12 skipped**（`NOVA_TEST_FAST=1`），ruff、记忆评估、前端构建与契约检查全部通过。

再补齐 P2 差异化能力（2026-11-22，迁移 30）：分层人工指令（org/user/project + `paths:` 按需注入 + 设置页）、跨会话消息/会话摘要检索（关键词 + 可选向量）、日/会话摘要 pgvector 索引、确定性主题索引与高风险/合并/冲突人工复核队列、子代理角色私有记忆（`agent:<name>`）、记忆投毒防护（高风险写入 `pending`）与同作用域写入串行化。设计与边界见 [`docs/DESIGN.md`](DESIGN.md) §42；新增 `test_memory_instructions.py`、`test_instructions_api.py`、`test_memory_episodic.py`、`test_summary_vectors.py`、`test_memory_topics.py`、`test_memory_review.py`、`test_memory_review_api.py`、`test_subagent_memory.py`。全量回归：后端 **1566 passed / 12 skipped**（`NOVA_TEST_FAST=1`），ruff、记忆评估、scripted eval 7/7、前端构建与契约检查全部通过。

仍未做：**团队记忆 store**（本清单 P2-6）。Nova 当前没有 workspace/member 模型，workspace scope 会与现有 user/repo/thesis 权限重叠；等团队版需求明确后，再按“权限 + 版本 + 审计 + redact”一次性设计。

---

## 11. 一句话总结

Nova 不需要再“加一层记忆”，需要把现有三层记忆的**边界、顺序和可恢复性**做对：先保证摘要发生在截断之前，再保证 facts 按 repo/thesis 隔离，然后把压缩从截断升级为可持久化的摘要，最后补上来源、编辑、冲突和评估。做到这四件事，Nova 的记忆能力会从“有记忆功能”变成“记忆可信、可纠正、可解释”。
