# Claude Code 与 Claude Agent SDK 的记忆机制：Anthropic 一手资料梳理

**日期**：2026-11-22  
**研究问题**：Anthropic 公开文档如何设计 Claude Code / Claude Agent SDK 的记忆？包括 memory tool、context editing、compaction、CLAUDE.md 层级、auto memory / MEMORY.md、长任务记忆实践、检索/更新/去重/陈旧处理、隐私安全与评估。  
**方法**：只使用 Anthropic 一手来源（anthropic.com、code.claude.com、platform.claude.com、官方 `/llms-full.txt`）。先读页面原文再归纳；不引用二手解读。  
**取证说明**：`platform.claude.com` 的 HTML 页面在本网络被地区重定向（307 → `anthropic.com/app-unavailable-in-region`），因此 API 文档正文从同源官方汇总 `https://platform.claude.com/llms-full.txt` 读取（该文件 `Last-Modified: 2026-11-22T09:46:49Z`）。Claude Code 页面使用 HTML 内的 `dateModified`；API 页面本身无日期，标为 undated。  
**阅读提示**：【事实】= 来源直接陈述；【未验证】= 本轮一手资料未给出足够细节，不等于不存在。本文不评价任何具体产品，也不给产品建议。

---

## 1. 摘要（Summary）

【事实】截至 2026-11-22，Anthropic **没有发布一份覆盖 Claude Code、Claude API 与 Claude Agent SDK 的单一、规范性的“记忆架构”文档**；最接近的近期单篇是 Anthropic Engineering 的 **“The components of agent memory”（2026-11-06）**，但它是一篇带评估和开放问题的工程研究文章，不是产品规格。实际机制分散在四层材料里：**(a) Claude Code 产品**用 `CLAUDE.md` / `AGENTS.md` / `.claude/rules/` 做分层指令注入，用 auto memory（`MEMORY.md` 索引 + 主题文件）做跨会话学习，用自动压缩处理会话上下文，并用子代理隔离上下文；**(b) Claude API** 提供客户端执行的 memory tool（虚拟 `/memories` 目录）、服务端 context editing（清除旧 tool 结果/thinking）、服务端 compaction（摘要替换旧回合）以及 context awareness；**(c) Agent SDK** 沿用 Claude Code 的文件系统指令与 auto memory，并补充 sessions/transcripts、`SessionStore`、自动压缩和子代理 `memory` 字段；**(d) 工程博客**给出 compaction、structured note-taking、progress file/feature list、sub-agent、dreaming/wiki 等模式与评估。全文最关键的边界是：**Claude Code 的 auto memory 不是 API 的 memory tool；API 的 context editing 不是 Claude Code 的 `/compact`；Dreaming 目前是 Managed Agents 的研究预览，不是 Claude Code 或 Agent SDK 的既有功能。**

### 1.1 是否存在单一“已发布记忆架构”？

【事实】没有。`anthropic.com/engineering` 的列表确实在 2026-11-06 列出 **“The components of agent memory”**，但该文开头定义“agent memory”时明确把它与 **weights 更新、in-context learning、compaction** 区分开，正文讨论的是 salience、dreaming、wiki 和若干评估，并未给出 Claude Code / API / SDK 的统一架构规范 [S27][S30]。因此，本文把它视为“最接近的近期权威文章”，而不是“官方架构规格”。消费者侧 claude.ai 的 memory 不在本文范围。

---

## 2. 分层架构（Architecture by layer）

### 2.1 指令/规则层：CLAUDE.md、AGENTS.md、`.claude/rules/`

【事实】这一层是 **Claude Code 产品行为**，由 harness 在会话开始时确定性地读取并注入；它不是模型自己决定写入的记忆。Claude Code 把 `CLAUDE.md` 与 auto memory 都当作 **context，而不是强制配置**；要阻止某个动作，应使用 `PreToolUse` hook、权限或 managed settings [S1]。

| 作用域 | 位置 | 读取时机 | 共享范围 |
|---|---|---|---|
| Managed policy | macOS `/Library/Application Support/ClaudeCode/CLAUDE.md`；Linux/WSL `/etc/claude-code/CLAUDE.md`；Windows `C:\Program Files\ClaudeCode\CLAUDE.md`；或 managed settings 的 `claudeMd` 键 | 启动时，先于 user/project | 组织内所有用户；可被 MDM/Group Policy 等分发 |
| User | `~/.claude/CLAUDE.md` | 启动时 | 仅本机用户，所有项目 |
| Project | `./CLAUDE.md` 或 `./.claude/CLAUDE.md` | 启动时 | 通过版本控制共享给团队 |
| Local | `./CLAUDE.local.md` | 启动时 | 仅本人当前项目；文档建议加入 `.gitignore` |

【事实】加载顺序是“从最宽到最具体”，但 **所有发现的文件是拼接进上下文，而不是后者覆盖前者**；目录树中从文件系统根到工作目录排序，越靠近启动目录的内容越晚被读到；同一目录内 `CLAUDE.local.md` 追加在 `CLAUDE.md` 之后。工作目录及其祖先的 `CLAUDE.md` / `CLAUDE.local.md` 在启动时加载；子目录中的文件在 Claude 读取/写入/编辑该目录下文件时才按需加载 [S1]。文档明确说，如果两条指令冲突，Claude 可能任意选择其中一条，因此没有硬性的“更具体覆盖更宽”规则 [S1]。

【事实】`AGENTS.md` 可作为项目指令：默认情况下，只有当工作目录及其祖先没有 `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` 时才直接读 `AGENTS.md`；可用 `/config` 的 **Project instructions** 改为 `claude-md-and-agents-md` 等。直接读 `AGENTS.md` 需要 Claude Code v2.1.277+ [S1]。

【事实】导入与规则：

- `@path/to/file` 导入会被展开并和引用它的 `CLAUDE.md` 一起加载；相对路径相对“包含导入的文件”解析；递归导入最大 **4 跳**；Markdown 代码 span/围栏中的 `@` 不解析；路径含空格需反斜杠转义；被引号包住则不会导入 [S1]。
- 项目级 `CLAUDE.md` 中的外部导入（解析到工作目录之外）第一次遇到时会弹出审批对话框，拒绝后这些导入保持禁用且对话框不再出现；用户级文件（如 `~/.claude/CLAUDE.md`、`~/.claude/rules/`）的导入默认受信任，但 Cowork 会话会跳过解析到工作目录之外的导入，并跳过本身是符号链接/硬链接的 `~/.claude/CLAUDE.md`，以及指向工作目录外的 rules 符号链接 [S1]。
- `.claude/rules/*.md` 可按主题拆分；无 `paths:` frontmatter 的规则在启动时以与 `.claude/CLAUDE.md` 相同优先级加载；带 `paths:` 的规则只在 Claude 读取/写入/编辑匹配文件时加载。用户级 `~/.claude/rules/` 先于项目规则加载，两者也不互相覆盖 [S1]。
- 规则支持符号链接；指向工作目录外的链接按外部导入处理，需要一次项目级审批；指向 UNC/网络路径的 `CLAUDE.md` 或 rules 符号链接不会被跟随，以免访问网络主机 [S1]。
- 大小：文档建议每个 `CLAUDE.md` 控制在 **200 行以内**；单个文件超过 **4 MiB** 会被完全跳过；按需加载的子目录 `CLAUDE.md` / path-scoped rules 另有更小的每文件字符上限（200K 上下文窗口 40,000 字符；1M 窗口 200,000 字符，部分模型 150,000 字符）[S1]。
- `claudeMdExcludes` 可用绝对路径/glob 跳过祖先 `CLAUDE.md` 或 rules，可在 user/project/local/managed 各层配置并合并；但 **不能排除 managed policy 文件**。`claudeMd` 键只在 managed/policy settings 中生效 [S1]。
- 强制力边界：managed settings 的 `permissions.deny`、`sandbox.enabled`、`env` 等由客户端执行；`CLAUDE.md` 只影响模型行为，不是硬隔离层 [S1]。`/doctor prompt-audit`（Claude Code v2.1.283+）可检查过时、失效或互相矛盾的指令文件，但文档列出的默认审计范围是 `CLAUDE.md`、`CLAUDE.local.md`、`AGENTS.md` 及 `.claude/` / `~/.claude/` 下的 rules、skills、commands、subagents、output styles，其中不含 auto memory [S1]。

【事实】Agent SDK 通过 `settingSources`（Python `setting_sources`）继承这一层：默认/省略时等同 `["user", "project", "local"]`；传 `[]` 可关闭 user/project/local 设置；managed policy 与 `~/.claude.json` 仍会被读取。`CLAUDE.md` 与 rules 在各层之间是 **additive**，没有硬性优先级；冲突结果取决于 Claude 的解释。子代理可设 `omitClaudeMd: true` 跳过 user/project/local 的 `CLAUDE.md`（managed policy 仍加载，managed subagents 例外；主线程 agent 忽略该字段），或用 `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` 全部关闭 [S13][S15]。`CLAUDE.md` 被注入到对话中，而不是系统提示本身 [S15]。

### 2.2 会话上下文层

【事实】Claude Code 每个会话从 **新的上下文窗口** 开始；`CLAUDE.md` 和 auto memory 是把知识带过会话边界的两条主路径 [S1]。Claude Code 的上下文包含系统提示、工具定义、`CLAUDE.md`、auto memory、skills、读到的文件、命令输出和模型回复；子代理使用独立上下文窗口，只有最终结果回到主会话 [S2][S4]。

【事实】Claude API 的上下文窗口包含系统提示、`messages` 中的每条消息（含 tool results、图片、文档）、工具定义，以及本轮输出（含 thinking）；所有 token 都计入窗口。文档把上下文称为模型的“工作记忆”，并明确提到 **context rot**：token 越多，准确召回越差。部分模型（如 Claude Sonnet 5/4.6、Sonnet 4.5 deprecated、Haiku 4.5）会在系统提示中注入 `budget:token_budget`，并在每次工具调用后注入剩余 token 警告；较新的 Opus/Fable/Mythos/Haiku 5.5 等不注入这些标签，可改用 beta 的 task budgets [S22]。

【事实】Agent SDK 的上下文同样跨 turn 累积：系统提示、工具定义、CLAUDE.md（每请求完整出现，但可被 prompt caching）、对话历史、工具输入/输出、skill 描述。CLAUDE.md 和系统提示等稳定前缀会被自动 prompt cache；自动压缩在接近上限时发生 [S10]。

### 2.3 长期记忆层：三种不同的东西

这一层最容易被混为一谈。Anthropic 公开文档里至少有三套不同机制：

| 机制 | 所属产品 | 存储位置 | 谁写 | 如何读回 | 当前状态 |
|---|---|---|---|---|---|
| **Claude Code auto memory** | Claude Code 产品；Agent SDK 继承 | 本机 `~/.claude/projects/<project>/memory/`（可改 `autoMemoryDirectory`） | Claude Code 中的 Claude，用普通文件工具 | 启动时加载 `MEMORY.md` 前 200 行/25KB；主题文件按需用文件工具读取 | 本地会话默认开启；self-hosted 环境（Claude Tag 之外）默认关闭；可用 `autoMemoryEnabled` / `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` 关闭 [S1] |
| **API memory tool** | Claude API（客户端执行） | 开发者自己的存储；模型看到的是 `/memories` 虚拟前缀 | 模型发出工具调用，应用执行 | 模型调用 `view` / `create` / `str_replace` / `insert` / `delete` / `rename` | stable；无 beta header；所有模型可用；ZDR/HIPAA eligible [S16] |
| **Managed Agents memory store + dreams** | Managed Agents（范围外，单独产品） | Anthropic 管理的 memory store | agent 写入；dream 异步重组 | memory store + session transcripts | research preview；`dreaming-2026-04-21` 等 beta [S23] |

#### (a) Claude Code auto memory / MEMORY.md

【事实】auto memory 让 Claude 自己积累跨会话知识。笔记分四类，写在文件 frontmatter 的 `type` 字段：`user`（用户角色、专长、偏好）、`feedback`（纠正、确认过的方法）、`project`（进行中的工作、截止日期、无法从代码/git 推导的决策）、`reference`（外部信息在哪里找）[S1]。Claude 会跳过能从代码库推导的内容（架构、文件路径、调试修复），也会跳过 `CLAUDE.md` 已经说了的内容；它不会每个会话都写，而是判断“未来对话是否有用” [S1]。

【事实】目录结构：

```text
~/.claude/projects/<project>/memory/
├── MEMORY.md           # 索引，一行一条，会话启动时加载
├── user_role.md        # 一条记忆
├── feedback_testing.md # 一条记忆
└── ...                 # Claude 创建的其他主题文件
```

`<project>` 由 git 仓库推导，因此同一仓库的所有 worktree 和子目录共享一个 auto memory 目录；非 git 仓库使用项目根目录。auto memory 是 **machine-local**，不跨机器或云环境共享。文档还提供 `autoMemoryDirectory`（绝对路径或 `~/` 开头）和 `CLAUDE_CODE_PROJECT_DIR_NAME` 来改变/共享目录，但仓库提供的设置若把目录指向工作目录外，在 `permissions.blockReadsOutsideWorkingDirectories` 开启时既不会加载也不会写入 [S1][S5]。

【事实】`MEMORY.md` 是索引：会话启动只加载 **前 200 行或 25KB（先到者）**；主题文件如 `user_role.md` 不在启动时加载，Claude 需要时用标准文件工具按需读取。写入后 Claude Code 会检查 200 行/25KB 限制；接近上限时提醒 Claude“一行一条、把细节移到主题文件、合并或删除陈旧条目”；超过上限写入仍成功，但会返回错误要求重写索引，因为下次加载会丢弃超出部分 [S1]。Claude 写入带 YAML frontmatter 的记忆文件时，Claude Code 会记录 `modified` 字段（ISO 8601），让用户和 Claude 都能判断事实的新旧 [S1]。auto memory 文件是普通 Markdown，可用 `/memory` 浏览/编辑/删除，也可在文件系统直接改；用户说“记住……”时 Claude 会写入 auto memory，说“加到 CLAUDE.md”时才写指令文件 [S1]。Claude Code 的 `cleanupPeriodDays` 清理旧 transcript，但 **不会清理 auto memory 文件**；该目录只有在整个保留期内一直为空才会被删除 [S1][S7]。

【事实】子代理可以有自己的 auto memory：frontmatter 的 `memory: user | project | local` 会创建独立目录（`~/.claude/agent-memory/<name>/`、`.claude/agent-memory/<name>/`、`.claude/agent-memory-local/<name>/`），子代理系统提示会包含读写说明和 `MEMORY.md` 前 200 行/25KB，并自动启用 Read/Write/Edit；`project` 是文档推荐的默认 scope。主会话的 auto memory 不会加载进子代理（fork 例外，因为它继承父对话和系统提示）[S1][S3]。

【事实】auto memory 可用 `autoMemoryEnabled`（默认 true）或 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` 关闭；关闭后子代理的 `memory` 字段也不生效 [S1][S3]。Agent SDK 默认把 auto memory 目录位置嵌入系统提示（在 `append` 文本之前），因此不同用户/机器/checkout 的系统提示缓存不共享；`excludeDynamicSections` 可把该 per-user context 移到第一条 user message 以复用缓存，但文档提醒该文本在 user message 中的指令权重略低 [S15]。

#### (b) API memory tool

【事实】memory tool 是 **客户端执行** 的 Anthropic 提供工具：请求里加入 `{"type": "memory_20250818", "name": "memory"}` 即可，不需要自定义 input schema。`/memories` 只是前缀，应用把它映射到自己的存储（每用户目录、数据库 key、云存储等）；模型只发出文件操作请求，应用执行并在 `tool_result` 中返回结果。后续对话只要发送同一个 `tools` entry 且 handler 服务同一个 store，就会接续同一份记忆 [S16]。文档明确说它支持 **just-in-time retrieval**：agent 把学到的东西写入 memory files，需要时再读回，从而不把所有信息塞进活动上下文 [S16]。

【事实】命令语义（参考实现，应用可返回不同文本）：

- `view`：查看目录或文件；目录列出最多 2 层，排除隐藏项与 `node_modules`；文件返回带行号内容；`view_range` 支持 `[start, end]` / `[start, -1]`；超过 16,000 字符的文本视图会被截断；超过 999,999 行返回错误 [S16]。
- `create`：创建文件；参考实现在文件已存在时返回错误；但文档同时指出工具描述写的是“creates or overwrites”，因此覆盖也是合法实现选择 [S16]。
- `str_replace`：替换文本；`new_str` 可省略（等于删除 `old_str`）；`old_str` 必须唯一，否则报多处匹配 [S16]。
- `insert`：在 `insert_line` 之后插入；`0` 表示文件开头 [S16]。
- `delete`：文件或目录；目录递归删除；不能删除 `/memories` 根 [S16]。
- `rename`：移动/重命名；目标已存在时返回错误，不覆盖；不能重命名 `/memories` 根 [S16]。

【事实】SDK 的 memory helper/tool-runner 接口位于 beta namespace（Python/TS/C#/Java 的 helper 等），但 memory tool 本身不需要 beta header [S16]。

【事实】当请求的 `tools` 含 memory tool 时，API 会自动向系统提示加入一段指令，包括 “ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE” 和 “ASSUME INTERRUPTION: Your context window might be reset at any moment…”。工具描述本身还要求保持目录整洁；如果 Claude 仍写得杂乱，可在 prompt 中追加“保持 up-to-date、coherent、organized，重命名/删除不再相关的文件，不要无必要地新建文件” [S16]。文档还给出多会话软件开发的明确模式：**initializer session** 先建 progress log、feature checklist、启动脚本；后续会话先读这些文件恢复状态；会话结束前更新 progress log；一次只做一个 feature，只有端到端验证通过才标记完成 [S16]。

【事实】安全责任在应用侧：Claude 通常会拒绝写敏感信息，但更强保证需要应用在写盘前做脱敏/校验；要跟踪并限制文件大小、可限制 `view` 返回字符数并用 `view_range` 分页；要定期删除长期未访问的记忆；必须校验每个命令的路径，防止 `/memories/../../secrets.env`、`../`、`..\\`、URL 编码的 `%2e%2e%2f` 等目录穿越；应把路径 canonicalize 并确认仍在 memory 目录内（文档举例 Python `pathlib.Path.resolve()` / `relative_to()`）[S16]。

#### (c) Managed Agents memory store / dreaming（范围外但相关）

【事实】这是单独产品，不应与 Claude Code/Agent SDK 合并。其文档说 agent 工作时会写 memory store，多次会话后会产生重复、矛盾和过期条目；**dream** 是一个异步 job，读取已有 memory store 加 1–100 个 past session transcripts，输出一个新的、重组过的 memory store：**合并重复、用最新值替换过期/被矛盾条目、浮现新洞察**。输入 store 不被修改，因此可以先审查输出再决定是否采用 [S23]。该功能是 research preview，需要 `managed-agents-2026-04-01` 与 `dreaming-2026-04-21` 等 beta header；除 self-hosted Managed Agents 外不 eligible for ZDR [S23]。2026-11-06 的 “The components of agent memory” 讨论的 dreaming、wiki、memory hierarchy 正是这一方向的研究与评估，而不是 Claude Code auto memory 的文档化实现 [S27]。

### 2.4 压缩与上下文编辑层

这一层同样有四种不同机制：

| 机制 | 所属 | 做什么 | 当前状态/参数 |
|---|---|---|---|
| **Claude Code 自动压缩 / `/compact`** | Claude Code 产品 | 把会话历史摘要，保留近期交流与关键决策；启动内容中的部分会重新注入 | 产品内自动；`/compact` 可带 focus；`/rewind` 可 Summarize from/up to here；`/autocompact` 可设窗口；idle compaction 默认开启（满足条件时）[S2][S6][S5] |
| **API context editing** | Claude API，服务端 | 按阈值清除旧 tool results（可选连同 tool inputs）或旧 thinking blocks；不生成摘要 | beta；header `context-management-2025-06-27`；策略 `clear_tool_uses_20250919`、`clear_thinking_20251015` [S17] |
| **API server-side compaction** | Claude API，服务端 | 用 Claude 写的摘要替换旧回合，生成 `compaction` block | beta；threshold 用 `compact-2026-01-12` / `compact_20260112`；on-demand/background 用 `compact-2026-09-04` [S18][S19][S20][S21] |
| **SDK client-side compaction** | TypeScript/Ruby SDK `tool_runner` | SDK 监控 token，超过阈值时让 Claude 生成 `<summary>`，替换整个消息历史 | 已弃用；TypeScript/Ruby 仍可用但会警告，Python v1.0 已移除；Anthropic 推荐 server-side compaction [S17] |

#### Claude Code 的压缩行为

【事实】Claude Code 在接近上下文上限时自动压缩；自动压缩与 `/compact` 的机制相同，都是把会话历史摘要到能放进窗口。压缩后仍保留/重新注入的内容包括：系统提示与 output style、项目根 `CLAUDE.md` 与无 `paths:` 的 rules、auto memory、skill 描述（v2.1.304+，从当前 skills 重建）、启动时的 git status 快照（若存在）、plan mode 的 plan、`paths:` rules 与子目录 `CLAUDE.md`（按需重新加载）、最近读过/改过的至多 5 个文件（文件超过 5,000 token 时只留路径引用）、已调用 skill body（每个最多 5,000 token、总计最多 25,000 token，最旧的先丢）、后台命令/子代理（继续运行，并提醒 Claude 不要重复启动）、hooks 之前加入的内容（随会话一起摘要）、匹配 `compact` source 的 SessionStart hooks（重新运行并加入输出）[S2]。

【事实】Claude Code 还提供：`/compact focus on ...` 指定摘要重点；`/rewind` 的 Summarize from here / Summarize up to here；`/autocompact <tokens>` 提前压缩；`/clear` 在切换无关任务时清空；把大读取交给子代理。自动压缩窗口按模型/配置变化：native 1M 窗口的模型默认在约 **967K** token 压缩；Sonnet 4.6 / Opus 4.6 未开 extended context 时在 200K 边界压缩；无法识别的模型 ID 按假定窗口压缩 [S2][S6]。idle compaction 在交互式终端/VS Code/桌面、auto-compaction 开启、使用 1 小时 prompt cache、上下文达到阈值（默认 200,000，可调，最低 100,000）且空闲约 1 小时后触发，默认开启 [S5]。如果单个文件/工具输出大到每次摘要后立刻又填满，Claude Code 会在几次尝试后停止自动压缩并报 thrashing 错误 [S4]。

#### API context editing

【事实】context editing 在服务端、prompt 到达模型之前应用；客户端仍保留完整未修改的对话历史，不需要同步编辑后的版本。`clear_tool_uses_20250919` 在超过阈值后按时间顺序清除最旧的 tool results，替换为占位文本；默认只清结果，`clear_tool_inputs: true` 时连 tool use 参数一起清。配置项：`trigger` 默认 100,000 input tokens；`keep` 默认保留最近 3 个 tool-use/result 对；`clear_at_least` 要求每次至少清够一定 token，否则不应用；`exclude_tools` 排除指定工具；`clear_tool_inputs` 默认 false [S17]。`clear_thinking_20251015` 管理旧 thinking blocks，默认是否保留取决于模型代际，可用 `keep` 覆盖 [S17]。响应中的 `context_management.applied_edits` 会报告清除了多少 turns/tool uses 和多少 input tokens；流式响应在最后一个 `message_delta` 中给出 [S17]。

【事实】context editing 与 prompt caching 有交互：清 tool results 会使被清内容之后的缓存前缀失效，因此应用 `clear_at_least` 让清理量值得破坏缓存；保留 thinking 会保留缓存，清除 thinking 会使缓存失效。文档还提供 token counting 预览编辑后的 token 数 [S17]。

【事实】context editing 与 memory tool 设计为配合使用：当对话接近配置的清除阈值时，Claude 会收到自动警告，提示把重要信息保存到 memory files，然后再清除 tool results/上下文；之后可按需从 memory 读回。文档举的文件编辑场景是：Claude 把已完成修改摘要到 memory，tool results 被清后仍能通过 memory 继续工作 [S17]。当前 context editing 页面开头明确说：**对大多数用例，server-side compaction 才是主要策略**；context editing 适合需要更细粒度控制的场景 [S17]。这与 2025-09-29 发布公告把 context editing 与 memory tool 并列为两大能力时的重心不同，属于版本/指南变化 [S24]。

#### API server-side compaction

【事实】threshold compaction 在普通请求的 `context_management.edits` 中加入 `{"type": "compact_20260112"}`，并带 `compact-2026-01-12` beta header；默认在 **150,000 input tokens** 触发，最低可设 **50,000**。达到阈值后 API 生成摘要、创建 `compaction` block、并继续响应；后续请求把响应 append 回去，API 自动丢弃 compaction block 之前的内容 [S19]。摘要用请求中指定的同一个模型，不能用更便宜的模型；如果请求带 `tools`，模型偶尔会在摘要时调用工具而不是写摘要，导致 `compaction` block 的 `content: null`，文档建议在 `instructions` 中明确“只写摘要、不要调用工具” [S19]。context windows 页面说 server-side compaction 对 Claude 4.6+ 与 Mythos Preview 可用（beta），并以它作为长对话的主要策略 [S22]。

【事实】on-demand compaction 由应用决定何时摘要：发送一个带顶层 `"compaction": {"type": "summarize"}` 的请求，返回一个含摘要文本与签名的 `compaction` block，不返回回复；之后把该 block 放在 `messages` 最前面，替换被摘要的消息。它使用 `compact-2026-09-04` header；文档明确说 **不能在同一请求中把 `compaction` 与 `context_management` 组合** [S20]。background compaction（async）让摘要请求在后台运行、对话继续在完整历史上推进，返回后再把 block 换入；同样使用 `compact-2026-09-04` [S21]。“Compaction that keeps recent turns” 只摘要更旧的回合，最近回合逐字保留 [S18]。

【事实】memory tool 文档建议长任务同时使用 compaction 与 memory：compaction 保持活动上下文小，memory 保留必须跨摘要存活的信息；context editing 清具体 tool results，compaction 摘要整个会话，两者定位不同 [S16][S17]。SDK 的自动压缩在接近上限时摘要旧历史，保持最近交流与关键决策；`CLAUDE.md` 在每个请求都会重新注入（压缩后仍可依赖），因此持久规则应放 `CLAUDE.md` 而不是初始 prompt；可用 `PreCompact` hook 归档、在 `CLAUDE.md` 写 summary instructions，或发送 `/compact` 手动触发 [S10]。

【事实】SDK client-side compaction 的默认摘要提示要求 Task Overview、Current State、Important Discoveries、Next Steps、Context to Preserve 五部分；它用 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens + output_tokens` 估算 token，server-side tools 可能使估算偏高并提前触发；工具调用待定时会先移除 tool use block，恢复后 Claude 若仍需要会重发 [S17]。

### 2.5 子代理层

【事实】Claude Code 子代理在独立上下文窗口中运行；除非是 fork，否则从全新上下文开始，父到子只传 Agent 工具的 prompt 字符串，子的工具调用和结果留在子上下文，父只收到最终报告/摘要。主会话的 auto memory 不会加载进子代理；子代理可通过 `memory` 字段拥有自己的独立记忆目录 [S1][S3]。子代理可配置 `omitClaudeMd: true` 跳过 user/project/local 的 `CLAUDE.md`，但 managed policy 仍加载（managed subagents 例外；主线程 agent 忽略该字段）[S3][S13]。

【事实】Agent SDK 的子代理同样强调 context isolation：非 fork 子代理从全新上下文开始，只有最终消息回到父；父可能再自行摘要。`AgentDefinition` 有 `memory: 'user' | 'project' | 'local'` 字段；启用 memory 时子代理还会获得 Read/Write/Edit 工具 [S14]。文档提醒：子代理的最终报告可能被父再摘要，若要逐字保留，应在主 `query()` 的 prompt 或 `systemPrompt` 中明确要求 [S14]。

【事实】工程博客给出的经验：子代理可能探索数万 token，但只返回约 **1,000–2,000 token** 的压缩摘要；主代理只保留高层计划，详细搜索上下文留在子代理内 [S25]。多代理研究系统的做法是：lead agent 先把计划保存到 Memory，以便上下文被截断后仍能恢复；子代理在各自上下文窗口并行探索；外部 memory/artifact 文件系统用于避免“传话游戏”，子代理把结果写入外部系统后只传轻量引用 [S29]。该文说多代理系统比单代理在内部研究评估上高 90.2%，但 token 消耗约为聊天的 15 倍 [S29]。

【事实】“Effective harnesses for long-running agents”（2025-11-26）把问题定义为：每个新会话没有上一次会话的记忆；仅靠 compaction 不够。它的两段式 harness 是：**initializer agent** 在第一次会话建立 `init.sh`、`claude-progress.txt`、初始 git commit，并把用户 prompt 展开成结构化 feature list（示例 200+ 个功能，初始标记 failing）；**coding agent** 每次会话先 `pwd`、读 progress file / git log / feature list，运行 `init.sh` 做基本端到端验证，然后只做一个 feature，结束后 git commit 并更新 progress file；只有端到端验证通过才标记 passing。文章说用 JSON feature list 是因为模型比 Markdown 更不容易改坏；progress file + git history 是让 fresh context 快速理解状态的关键 [S26]。

【事实】“Harness design for long-running application development”（2026-03-24）进一步比较 **context resets** 与 compaction：有些模型在接近自认为的上下文上限时出现 “context anxiety”，会提前收尾；reset 清空窗口并配合 structured handoff，能给出干净起点，但要求 handoff artifact 足够完整；compaction 保留连续性，但 agent 仍在同一段历史里，焦虑可能持续。该文的 harness 用 planner / generator / evaluator 三个角色，并把主观判断拆成可评分标准；在早期 Sonnet 4.5 测试中 reset 是必要的，而 Opus 4.5 已基本消除该行为，于是该 harness 改为单一连续会话、用 Agent SDK 自动压缩处理上下文增长 [S28]。

【事实】“Effective context engineering for AI agents”（2025-09-29）把长任务记忆实践归为三类：**compaction**（摘要 + 保留架构决策、未解决 bug、实现细节，丢弃冗余 tool 输出；Claude Code 还会保留最近 5 个访问过的文件）、**structured note-taking / agentic memory**（如 NOTES.md 或 to-do，把进度写到上下文外，之后再读回）、**sub-agent architectures**（子代理探索数万 token，只返回约 1–2k token 摘要）；选择取决于任务：compaction 适合长对话，note-taking 适合有明确里程碑的迭代开发，多代理适合可并行探索的研究分析 [S25]。

### 2.6 检索层

【事实】在 Claude Code / Agent SDK / API memory tool 的公开文档中，**没有看到向量数据库、embedding 预检索或服务端语义搜索**作为记忆机制。检索是文件系统式的：

- **Claude Code auto memory**：`MEMORY.md` 索引在会话启动时加载（前 200 行/25KB），主题文件按需用普通 Read/Grep/Glob 等文件工具读取；没有专门的 memory 检索工具，也没有自动 embedding 索引 [S1][S7]。
- **API memory tool**：模型在任务开始时先 `view /memories`，再按需 `view` 具体文件；`/memories` 只是应用存储的映射，Anthropic 不托管检索 [S16]。
- **Agent SDK**：沿用 Claude Code 的文件工具与 auto memory；会话恢复会把 transcript 带回上下文，`SessionStore` 只镜像 transcript，不提供语义检索 [S10][S11][S12]。
- **工程指引**：effective context engineering 文章主张 “just-in-time” 检索——维护文件路径、查询、链接等轻量标识，运行时再用工具加载；Claude Code 是混合策略：`CLAUDE.md` 预先放入上下文，glob/grep 按需导航，从而避开陈旧索引和复杂语法树 [S25]。“The components of agent memory” 进一步用 **wiki** 作为记忆表示：Claude 写并维护带链接的页面，链接本身构成可遍历的记忆地图；评估中 wiki + search 的组合优于单独 search，但 wiki 也可能膨胀到比原始语料还大 [S27]。

### 2.7 已公开的评估与数字

【事实】Anthropic 公开的记忆/上下文评估主要来自两处，且都是 **Anthropic 内部评估**：

1. **2025-09-29 发布公告** [S24]：在一个内部 agentic search 评估集上，memory tool + context editing 比 baseline 提升 **39%**；只用 context editing 提升 **29%**。在一个 100-turn web search 评估中，context editing 让原本会因上下文耗尽失败的工作流完成，并减少 **84%** token 消耗。公告没有给出独立复现或置信区间。
2. **2026-11-06 “The components of agent memory”** [S27]：
   - **CL-Bench 1.0** database 任务：Claude 每个问题从新会话开始，只能从跨会话保留的 memory 目录取文件；不同模型的自建学习循环成熟度不同。Opus 5.5 / Sonnet 5.5 用 memory 后与 Opus 5 大致持平，但它们无 memory 的 baseline 略高。
   - **Pokémon Red**：Sonnet 3.7 写了 **413 个 memory files / 225 个文件夹**，只拿到 1 个 badge；Fable 5 写了 **9 个文件 / 2 个文件夹** + 一个 `global.md`，拿到 4 个 badge。Sonnet 3.7 的记录随游戏状态快速过期，约 step 10,000 时在 17 步内创建 6 个文件、删除 9 个文件、没有在游戏里采取行动。Opus 5.5 用小型 memory 文件夹跟踪当前目标和下一步，最终通关。该比较是每次运行各一次，属于说明性案例，不是统计基准。
   - **Wiki 评估**：内部 350,000 个文件、约 420M token 的语料，25 个问题；dreaming 从 2 个 session 扩到 128 个 session，按评分标准通过率从 **13% 到 48%**。同时给 search 和 wiki 时，随 wiki 增长总分从 **54% 到 61%**，而只有 search 时是 **53%**；只用 wiki 最好 48%；search + wiki 每题约省 **20,000 token**。
   - **Harvey LAB / merger 文档**：24 个问题中，需要跨多文档综合的题目，wiki 得分 **87%**，search 单独 **73%**；对于单文档即可检索的 LAB 任务，wiki 没有明显增益，甚至可能膨胀到比原始文档还大。
   - **写入冲突**：多个 agent 同时写共享 contract 表时，57 个 contract facts 只有 **41 个（72%）** 进入 wiki；改成每个 contract 一个页面、由一个 agent 逐字引用条款后，达到 **57/57（100%）**。
   - **第二次 dreaming pass**：把 9 个指向不存在页面的链接重指到已有页面，并新增 3 个页面（含索引）[S27]。

【事实】同一篇文章还报告了写入策略的观察：给 Claude 说明 memory 的用途、但不规定具体写法，通常比给固定规则更有效；对 Opus 5/Opus 4.7 设 “record only failures” 会显著削弱 memory 带来的提升。对 Sonnet 4.6，提示它先读 memory 并显式测试假设，几乎让基准分数翻倍；Sonnet 5 已自行在 10 次中 9 次先读 memory。错误或漂移的笔记会被后续会话读取并信任；dreaming 可用 transcript 做 ground truth 校正，但需要 compute [S27]。

【事实】Claude Code 产品文档没有公开 auto memory 的 precision/recall、遗忘准确率或跨项目泛化评估；Agent SDK 文档也没有 memory 专项 benchmark。上述数字衡量的是任务表现/token 使用或特定 wiki 构建流程，不等于 auto memory 的产品质量。消费者侧 memory 的评估不在本文范围。

---

## 3. 生命周期（Lifecycle）

| 阶段 | Claude Code auto memory | API memory tool | API context editing / compaction | Agent SDK |
|---|---|---|---|---|
| **写入** | Claude 判断 salience 后写 Markdown；用户说“记住…”可触发；跳过可推导内容和 CLAUDE.md 重复项 | 模型发 `create` / `str_replace` / `insert`；应用执行并返回结果 | context editing 不写记忆；compaction 写摘要 block | 同 Claude Code；auto memory 用 Write/Edit；会话写 transcript |
| **读取** | 启动加载 `MEMORY.md` 前 200 行/25KB；主题文件按需 | 模型先 `view /memories`，再按需读文件 | 编辑在服务端应用；compaction 摘要替换旧回合 | 同 Claude Code；resume 恢复 transcript；`getSessionMessages` 返回压缩后的链 |
| **更新** | 重写/编辑索引与主题文件；`modified` 时间戳；提示合并/删除陈旧条目 | `str_replace` / `insert` / `rename`；应用可覆盖或报错（参考实现） | 清除旧 tool results/thinking；摘要替换 | 同 Claude Code；`PreCompact` hook 可在压缩前归档 |
| **去重** | 索引一行一条；跳过 CLAUDE.md 已有内容；接近上限时提示 merge/drop；无公开算法 | 文档要求保持 organized；可 rename/delete；无自动去重 | 清除最旧内容；`keep` 保留最近 N 个；`exclude_tools` 保护重要工具 | 同 Claude Code；dreaming 是 Managed Agents，不是 SDK |
| **遗忘** | 用户/Claude 可删除文件；`cleanupPeriodDays` 不清理 auto memory；无 TTL | `delete` 文件/目录（根不可删）；文档建议应用定期删除长期未访问文件 | context editing/compaction 只从上下文移除，不等于删除持久记忆 | 同 Claude Code；transcript 可按 `persistSession: false` 或环境变量不落盘 |
| **陈旧** | `modified` 时间戳；`/doctor prompt-audit` 检查指令文件；auto memory 本身无自动校验 | 文档建议应用做 expiration；无内建 TTL | 旧 tool 结果按阈值清除；context rot 使旧内容价值下降 | 同 Claude Code |

### 3.1 写入（Write）

【事实】auto memory 的写入策略是“模型判断 + 用户提示”：文档说 Claude 不是每个会话都写，而是判断未来是否有用；用户说“记住这个”会写入 auto memory，说“加到 CLAUDE.md”才写指令文件 [S1]。API memory tool 的写入完全由模型发起工具调用、应用执行；API 自动注入的 “ASSUME INTERRUPTION” 指令明确要求把进度写入 memory，因为上下文随时可能被重置 [S16]。compaction 的“写入”是模型生成摘要 block，不是持久记忆；context editing 不写入新记忆 [S17][S19]。

### 3.2 读取（Read）

【事实】auto memory 的读取分两级：索引在启动时自动加载，主题文件按需读取；因此检索质量取决于索引是否把“去哪里找”写清楚 [S1][S27]。API memory tool 在启用后，模型会“自动检查 memory 目录再开始任务”，因为系统提示被注入 “ALWAYS VIEW…”；这属于提示层行为，不是服务端强制检索 [S16]。Agent SDK 的 resume 会把之前 turn 的完整上下文恢复（包括读过的文件、分析、动作），但会话持久化的是 **conversation，不是 filesystem**；文件改动需用 file checkpointing 单独恢复 [S11]。

### 3.3 更新、去重与陈旧（Update / dedup / staleness）

【事实】auto memory 的去重是“提示 + 索引约束”，不是确定性算法：`MEMORY.md` 一行一条；接近 200 行/25KB 时 Claude Code 提醒 Claude 把细节移到主题文件、合并或删除陈旧条目；Claude 写入时会跳过能从代码库推导和已在 `CLAUDE.md` 中的内容 [S1]。文档没有公开“什么算重复”“何时覆盖旧事实”的规则，也没有公开冲突解决算法；`modified` 时间戳只是把新旧信息暴露给用户和 Claude [S1]。`/doctor prompt-audit` 能找出过时/矛盾/指向不存在文件的指令，但审计对象是指令文件，不是 auto memory [S1]。

【事实】API memory tool 的文档只给出原则：工具描述要求保持目录 organized；如果 Claude 仍然杂乱，可在 prompt 中要求 up-to-date、coherent、organized，重命名/删除不再相关的文件，不要无必要新建文件；没有自动 dedup 或 TTL，应用可自行实现 expiration [S16]。Managed Agents 的 dreaming 则明确做 dedup/staleness：合并重复、用最新值替换过期/被矛盾条目、从 transcripts 挖掘新洞察；输入 store 不可变，输出是新 store；这是当前 Anthropic 文档里最具体的“后台整合”机制，但不属于 Claude Code/Agent SDK [S23]。

【事实】工程文章给出了陈旧记忆的典型失败：Pokémon 中 Claude 把 PokéCenter 的位置记错，之后依据错误笔记判断“Mt Moon 已完成”，结果反复掉回原路线；dreaming 用 session transcript 作为 ground truth 检查并改写该笔记后，Claude 才重新进入山洞并到达下一个城市 [S27]。文章把“如何保持记忆最新”列为开放问题：记忆可能一开始就错，也可能随环境漂移；可以按访问频率调整 dreaming 节奏，或只对易变信息做 dreaming，但持续全量校验可能不现实 [S27]。

### 3.4 遗忘与保留（Forget / retention）

【事实】Claude Code 的 auto memory 文件没有 TTL，且被排除在 `cleanupPeriodDays` 的 transcript 清理之外；用户可随时编辑/删除，Claude 也可重命名/删除 [S1][S7]。API memory tool 没有内建过期；文档建议应用跟踪文件大小、限制 `view` 返回量、定期删除长期未访问的记忆 [S16]。context editing/compaction 的“遗忘”只发生在上下文层：被清除的 tool results/旧回合不再进入模型，但客户端完整历史或持久 memory 文件未必被删除 [S17][S19]。Claude Code 的 `/clear` 清会话，`/compact` 只替换为摘要；两者都不等于删除 auto memory 或 `CLAUDE.md` [S2]。transcript 本身默认在 `~/.claude/projects/` 保留 30 天（可调 `cleanupPeriodDays`）[S8]。

### 3.5 作用域与隔离（Scoping / isolation）

【事实】

- **CLAUDE.md**：managed / user / project / local 四层；managed 不能被 `claudeMdExcludes` 排除；local 建议 gitignore [S1]。
- **auto memory**：按 git 仓库一个目录，worktree/子目录共享；machine-local，不跨机器/云；可自定义目录，但仓库提供的路径在 `blockReadsOutsideWorkingDirectories` 下不被信任 [S1][S5]。
- **子代理**：主会话 auto memory 不进入子代理（fork 例外）；子代理自己的 memory 有 user/project/local 三种 scope [S1][S3]。
- **API memory tool**：应用负责把 `/memories` 映射到 per-user 目录、数据库 key 等；没有内建多租户隔离；必须做路径校验 [S16]。
- **Agent SDK**：默认读取 user/project/local 设置，`settingSources: []` 可关闭；但 **auto memory 不受 `settingSources` 控制**，仍会从 `~/.claude/projects/<project>/memory/` 加载，并用 Write/Edit 写入。多租户部署必须每个租户独立文件系统，并同时设 `settingSources: []` 与 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`；managed settings 仍会通过组织凭据获取，文件系统隔离不能移除它们 [S13]。
- **会话**：Agent SDK transcript 默认写到 `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`；`SessionStore` 可镜像到外部存储；`SessionStore` 的 key 包含 projectKey、sessionId、可选 subpath（子代理 transcript）[S11][S12]。

### 3.6 可观测与审计（Observability / audit）

【事实】Claude Code 提供 `/context all` 查看 **Memory files** 列表、`/memory` 浏览/编辑 memory 文件、`/status` 的指令文件大小警告；auto memory 写入/读取时界面会出现 “Saved N memories” / “Recalled N memories” [S1][S2]。API context editing 在响应的 `context_management.applied_edits` 中报告清除了多少 turns/tool uses/input tokens；compaction 返回 `compaction` block；Agent SDK 在自动压缩时发出 `system` / `compact_boundary` 消息，并提供 `PreCompact` hook（`trigger: manual | auto`）用于归档完整 transcript [S17][S10]。这些是可观测信号，不是记忆质量的自动评估。

---

## 4. 安全与隐私指引

### 4.1 API memory tool

【事实】文档把安全责任明确放在应用侧：

- **敏感信息**：Claude 通常会拒绝写敏感信息，但更强保证需要应用在写盘前做校验/脱敏 [S16]。
- **存储大小**：跟踪并限制 memory 文件大小；考虑限制 `view` 返回的字符数，让 Claude 用 `view_range` 分页 [S16]。
- **过期**：定期删除长期未访问的 memory 文件 [S16]。
- **目录穿越**：必须验证每个命令的每个路径；推荐校验 `/memories` 前缀、canonicalize、拒绝 `../` / `..\\` / URL 编码穿越，并使用语言内置路径安全工具 [S16]。
- **数据责任**：memory tool 是客户端执行，数据在开发者控制的存储中；文档把 ZDR 标注为 eligible（排除 Covered Models），HIPAA eligible [S16]。

### 4.2 API context editing / compaction

【事实】context editing 与 threshold compaction 都把 ZDR 标为 eligible（排除 Covered Models），但 **HIPAA 标为 not eligible**；context editing 的编辑实时应用，compaction 结果通过 API 响应以 stateless 方式 round-trip [S17][S19]。Managed Agents 的 dreaming 除 self-hosted 外 **not eligible for ZDR**，且 session transcripts 会持久化到删除为止 [S23]。

### 4.3 Claude Code 产品

【事实】文档公开的隐私/安全相关行为包括：

- auto memory 是 **machine-local**，不跨机器或云共享；同一 git 仓库的 worktree 共享一个目录 [S1]。
- 项目级外部 `@` 导入第一次遇到时弹出审批；用户级导入默认受信任，但 Cowork 会跳过外部导入和外部符号链接 [S1]。
- 指向 UNC/网络路径的 `CLAUDE.md` / rules 符号链接不会被跟随 [S1]。
- 仓库提供的 `.claude/settings.json` / `settings.local.json` 若设置 `autoMemoryDirectory`，受 workspace trust 规则约束；在 `permissions.blockReadsOutsideWorkingDirectories` 开启时不会加载或写入该目录 [S1][S5]。
- managed policy 的 `CLAUDE.md` 不能被用户排除，但若整个会话关闭 CLAUDE.md 加载，managed 内容也不加载；因此文档把硬性规则放在 managed settings 的 `permissions.deny` / `sandbox.enabled`，而不是 `CLAUDE.md` [S1]。
- auto memory 文件是普通 Markdown，用户可读/改/删；`cleanupPeriodDays` 不会清理它们 [S1][S7]。
- 本地 session transcript 默认以纯文本 JSONL 存在 `~/.claude/projects/`，默认保留 30 天，可用 `cleanupPeriodDays` 调整；`/feedback` / `/share` 上传 transcript 时只对已知 API key/token 模式做脱敏，源码、文件内容和对话内容按原样上传 [S8]。

【未验证】公开文档没有说明 auto memory 文件的静态加密、文件权限模型、是否进入遥测/反馈上传，也没有说明多用户共享同一 `~/.claude` 时的访问控制。文档只给出位置、plain Markdown、machine-local、清理例外和 workspace trust 规则。

### 4.4 Agent SDK

【事实】SDK 文档给出最明确的多租户隔离警告：**不要依赖默认 `query()` 选项做多租户隔离**。因为 `settingSources` 不控制 auto memory，SDK 进程可能读到宿主级配置和按目录的 memory；多租户应每个租户独立文件系统，设 `settingSources: []`，并在 `env` 中设 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`；managed settings 仍会通过组织凭据获取 [S13]。会话 transcript 可用 `SessionStore` 放进自己的存储，以便合规/审计、保留策略、加密和访问控制；但本地 subprocess 仍先写本地磁盘，store 是镜像而不是替代 [S12]。

### 4.5 工程文章的“记忆正确性”安全

【事实】“The components of agent memory” 把错误记忆视为安全问题/可靠性问题：错误笔记会被后续会话读取并信任；注入到每个会话的顶层记忆消耗 token，且错误会反复出现；因此顶层必须保持小，细节下移并留链接；dreaming 可以用 transcript 校验记忆，但需要 compute，且持续全量校验可能不现实 [S27]。该文没有给出隐私/访问控制指南；它讨论的是 salience、正确性和组织方式。

---

## 5. 产品特定 vs API/SDK 通用

### 5.1 分类表

| 能力 | (a) Claude Code 产品 | (b) Claude API | (c) Claude Agent SDK | (d) 工程博客指引 |
|---|---|---|---|---|
| **CLAUDE.md / AGENTS.md / rules** | 原生；四层作用域、导入、path-scoped rules、`claudeMdExcludes` | 不是 API 功能 | 通过 `settingSources` 继承；默认 user/project/local；`[]` 关闭；无硬优先级 | 作为“预置上下文”的例子；CLAUDE.md 预先放入 + glob/grep just-in-time [S25] |
| **auto memory / MEMORY.md** | 原生；按仓库、machine-local、200 行/25KB 索引 | **不是** memory tool | 继承 Claude Code；不受 `settingSources` 控制；可 disable | 2026-11-06 文章把它作为“注入层保持小”的实例 [S27] |
| **memory tool / `/memories`** | 不是 Claude Code 内建工具 | 原生；客户端执行；stable/all models | 可通过 API tool runner 使用；SDK helper 在 beta namespace | “structured note-taking / agentic memory” 的一种实现 [S25] |
| **context editing** | 不是 Claude Code 的 `/compact` | 原生 beta；服务端清 tool results/thinking | 不直接暴露为 SDK 选项；SDK 文档描述的是自动压缩行为 | 作为 tool result clearing 的产品化 [S25] |
| **compaction** | 产品自动压缩 / `/compact` / `/rewind` / idle compaction | server-side threshold / on-demand / background；beta | SDK 自动压缩 + `compact_boundary` + `PreCompact`；client-side `compaction_control` 已弃用 | compaction 是长任务三件套之一；但“不够”，还需 progress artifacts [S25][S26] |
| **子代理记忆** | 子代理独立上下文；`memory: user/project/local` | 不是 API 功能 | `AgentDefinition.memory`；Read/Write/Edit；context isolation | 子代理返回 1–2k token 摘要；多代理用外部 memory/artifacts [S25][S29] |
| **会话持久化** | 本地 transcript；resume/branch 等产品行为 | 不是“记忆”功能 | JSONL + `SessionStore`；resume/fork；conversation 不是 filesystem | reset + structured handoff 可作为 compaction 的替代 [S28] |
| **dreaming / wiki** | 未见文档化为 Claude Code 功能 | 不是 API memory tool | 未见文档化为 Agent SDK 功能 | 2026-11-06 文章的核心；Managed Agents 有 research preview 实现 [S27][S23] |

### 5.2 矛盾、歧义与版本依赖

【事实】以下差异会影响“记忆架构”的准确表述：

1. **memory tool 的状态**：2025-09-29 公告称其为 **public beta** [S24]；当前 API 文档标为 **stable**、所有模型可用、无需 beta header [S16]。这是版本演进，不是同一时点的矛盾。
2. **context editing 的地位**：2025-09-29 公告把 context editing 与 memory tool 并列为两大能力 [S24]；当前 context editing 页面开头说 **server-side compaction 是大多数用例的主要策略**，context editing 适合需要细粒度控制的场景 [S17]。这是指南重心变化。
3. **client-side SDK compaction**：TypeScript/Ruby 仍支持 `compaction_control` 但已弃用并会警告；Python v1.0 已移除；Anthropic 推荐 server-side compaction [S17]。
4. **CLAUDE.md 层级不是优先级栈**：文档说所有文件拼接、没有覆盖关系；冲突时 Claude 可能任意选择 [S1]。这与“越具体越优先”的直觉不同。
5. **memory tool 的 `create` 语义**：工具描述说 “creates or overwrites”，参考实现却在文件已存在时返回错误；文档明确说覆盖也是合法实现选择 [S16]。
6. **Agent SDK 的 auto memory 绕过 `settingSources`**：默认 `query()` 会读 user/project/local，但 auto memory 无论 `settingSources` 如何都会加载；多租户必须显式 disable [S13]。
7. **auto-compact 阈值随模型/版本变化**：native 1M 模型约 967K；Sonnet 4.6/Opus 4.6 未开 extended context 时 200K；idle compaction 默认开启且可调；文档含大量 v2.1.x 版本门槛 [S2][S5][S6]。
8. **API beta 多头并存**：context editing 用 `context-management-2025-06-27`；threshold compaction 用 `compact-2026-01-12`；on-demand/background 用 `compact-2026-09-04`；on-demand compaction 不能与 `context_management` 同请求组合 [S17][S19][S20]。
9. **dreaming 的归属**：2026-11-06 文章讨论 dreaming，但文档化的 dreams 是 **Managed Agents research preview**，不是 Claude Code/Agent SDK 功能；不能把文章里的机制直接当成 auto memory 的实现 [S23][S27]。

---

## 6. 来源（Sources）

> API 文档页面本身无日期；其正文通过官方 `llms-full.txt` 读取（Last-Modified 2026-11-22）。Claude Code 页面日期取 HTML `dateModified`。所有页面均在 2026-11-22 重新取读。

| ID | 来源 | URL | 日期 | 用途/备注 |
|---|---|---|---|---|
| S1 | How Claude remembers your project（Claude Code Docs） | https://code.claude.com/docs/en/memory | 2026-11-21（dateModified） | CLAUDE.md/AGENTS.md/rules、auto memory、MEMORY.md、导入、限制、安全 |
| S2 | Explore the context window（Claude Code Docs） | https://code.claude.com/docs/en/context-window | 2026-11-17（dateModified） | 压缩后保留什么、`/compact`、`/autocompact`、`/clear`、子代理上下文 |
| S3 | Subagents（Claude Code Docs） | https://code.claude.com/docs/en/sub-agents | 2026-11-21（dateModified） | 子代理上下文隔离、`memory` 字段、持久记忆目录 |
| S4 | How Claude Code works（Claude Code Docs） | https://code.claude.com/docs/en/how-claude-code-works | 2026-11-21（dateModified） | 每会话新上下文、自动压缩、子代理 |
| S5 | Settings reference（Claude Code Docs） | https://code.claude.com/docs/en/settings-reference | 2026-11-21（dateModified） | `autoMemoryDirectory`、`autoMemoryEnabled`、`idleCompaction` |
| S6 | Model configuration（Claude Code Docs） | https://code.claude.com/docs/en/model-config | 2026-11-19（dateModified） | auto-compact 窗口、默认阈值、`/autocompact` |
| S7 | Explore the .claude directory（Claude Code Docs） | https://code.claude.com/docs/en/claude-directory | 2026-11-20（dateModified） | memory 目录、agent-memory、清理规则 |
| S8 | Data usage（Claude Code Docs） | https://code.claude.com/docs/en/data-usage | 2026-11-17（dateModified） | 本地 transcript、30 天保留、反馈上传 |
| S9 | Best practices（Claude Code Docs） | https://code.claude.com/docs/en/best-practices | 2026-11-21（dateModified） | CLAUDE.md 保持短、hooks 强制、上下文成本 |
| S10 | How the agent loop works（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/agent-loop | 2026-11-19（dateModified） | 上下文组成、自动压缩、`compact_boundary`、子代理 |
| S11 | Work with sessions（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/sessions | 2026-11-13（dateModified） | transcript 路径、resume/fork、会话不是文件系统 |
| S12 | Persist sessions to external storage（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/session-storage | 2026-11-12（dateModified） | `SessionStore`、双写、post-compaction 链 |
| S13 | Use Claude Code features in the SDK（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/claude-code-features | 2026-11-19（dateModified） | `settingSources`、CLAUDE.md 加载、auto memory 绕过、多租户隔离 |
| S14 | Subagents in the SDK（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/subagents | 2026-11-19（dateModified） | context isolation、`memory` 字段、Read/Write/Edit |
| S15 | Modifying system prompts（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts | 2026-11-16（dateModified） | CLAUDE.md 注入、auto memory 在系统提示中的位置、`excludeDynamicSections` |
| S16 | Memory tool（Claude API Docs） | https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool | undated（页面无日期） | `/memories`、命令、安全、ZDR/HIPAA、多会话模式 |
| S17 | Context editing（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/context-editing | undated（页面无日期） | tool result/thinking clearing、默认值、memory 集成、SDK compaction |
| S18 | Compaction overview（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction | undated（页面无日期） | 三种 compaction 的取舍、beta header |
| S19 | Compaction at a token threshold（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction-threshold | undated（页面无日期） | `compact_20260112`、默认 150k、限制、数据保留 |
| S20 | Compaction on demand（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction-on-demand | undated（页面无日期） | 顶层 `compaction`、`compact-2026-09-04`、不能与 context_management 组合 |
| S21 | Compaction in the background（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction-background | undated（页面无日期） | 异步 swap、对话继续增长 |
| S22 | Context windows（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/context-windows | undated（页面无日期） | 上下文组成、context rot、context awareness、compaction 定位 |
| S23 | Dreams（Claude Managed Agents Docs） | https://platform.claude.com/docs/en/managed-agents/dreams | undated（页面无日期） | research preview；dedup/staleness；输入不可变；beta |
| S24 | Managing context on the Claude Developer Platform（Anthropic News） | https://www.anthropic.com/news/context-management | 2025-09-29 | context editing + memory tool 发布；39% / 29% / 84% |
| S25 | Effective context engineering for AI agents（Anthropic Engineering） | https://www.anthropic.com/research/effective-context-engineering-for-ai-agents | 2025-09-29 | context rot、compaction、structured note-taking、sub-agents、memory tool beta；原 `/engineering/...` 路径重定向至此 |
| S26 | Effective harnesses for long-running agents（Anthropic Engineering） | https://www.anthropic.com/research/effective-harnesses-for-long-running-agents | 2025-11-26 | initializer agent、progress file、feature list、git、端到端验证；“compaction isn’t sufficient” |
| S27 | The components of agent memory（Anthropic Engineering） | https://www.anthropic.com/research/components-of-agent-memory | 2026-11-06 | agent memory 定义、salience、dreaming、wiki、CL-Bench/Pokémon/Harvey 评估；`/engineering` 列表收录，canonical 为 `/research` |
| S28 | Harness design for long-running application development（Anthropic Engineering） | https://www.anthropic.com/research/harness-design-long-running-apps | 2026-03-24 | context resets + structured handoff 与 compaction 的对比；planner/generator/evaluator |
| S29 | How we built our multi-agent research system（Anthropic Engineering） | https://www.anthropic.com/research/multi-agent-research-system | 2025-06-13 | 子代理上下文隔离、lead plan 存 Memory、外部 memory/artifacts、token 成本 |
| S30 | Engineering hub（Anthropic） | https://www.anthropic.com/engineering | undated（列表页） | 验证 2026-11-06 “The components of agent memory” 与 2025-09-29 等条目 |
| S31 | Anthropic Developer Documentation — Full Content（官方汇总） | https://platform.claude.com/llms-full.txt | Last-Modified 2026-11-22 | 本网络读取 API 文档正文的同源入口；S16–S23 的原文来自此文件 |

---

## 7. 未解问题与未验证项

【未验证】

1. **是否有单一权威“记忆架构”规格？** 没有找到。2026-11-06 的 “The components of agent memory” 是最接近的单篇，但它是工程研究文章，不覆盖 CLAUDE.md 层级、API 命令或 SDK 选项；不要把它当作规范。
2. **auto memory 的写入/更新/去重算法**：文档只说 Claude 判断 salience、跳过可推导内容和 CLAUDE.md 重复项、接近上限时合并/删除；没有公开阈值、冲突解决、事实覆盖或置信度机制 [S1]。
3. **auto memory 的质量评估**：没有公开 precision/recall、遗忘准确率、跨项目泛化或独立 benchmark；现有数字来自 context management 公告和 2026-11-06 文章的特定任务 [S24][S27]。
4. **dreaming 与 auto memory 的关系**：2026-11-06 文章讨论 dreaming，Claude Code 文档只描述 auto memory 的索引维护；Claude Code 是否在后台使用 dreaming 类整合、以及它与 Managed Agents dreams 是否同一实现，均未文档化 [S1][S23][S27]。
5. **Claude Code 自动压缩是否复用 API server-side compaction**：产品文档描述“模型摘要 + 重新注入”，API 文档描述 `compact_20260112` / `compact-2026-09-04`；两者是否同一后端实现未见说明，不能假定相同 [S2][S19][S20]。
6. **auto memory 的静态加密、文件权限、遥测/反馈范围**：文档只说明本地 plain Markdown、machine-local、清理例外和 workspace trust；没有加密/权限/是否上传的明确说明 [S1][S8]。
7. **记忆投毒/提示注入**：API memory tool 文档详细讲路径穿越，但没有专门讨论恶意 memory 内容对后续会话的提示注入；Claude Code 文档也未给出 memory poisoning 的专门防护说明 [S16][S1]。
8. **memory tool 参考实现的安全审计**：文档指向官方 SDK 的 memory helper/示例，但本轮没有审计这些代码；不能据文档断言实现无漏洞 [S16]。
9. **共享/跨机 auto memory 的并发语义**：`autoMemoryDirectory` 可指向自定义目录，但文档没有定义多进程/多用户并发写、锁、冲突合并或权限模型 [S1][S5]。
10. **消费者 claude.ai memory**：属于另一产品面，不在本文范围；不要把它与 Claude Code auto memory 或 API memory tool 混用。
11. **API 文档无日期**：S16–S23 的页面没有 publication/update 日期；本文只能标注 undated，并用官方汇总的 Last-Modified 说明取读时间。功能状态（stable/beta/research preview）可能随版本变化。
