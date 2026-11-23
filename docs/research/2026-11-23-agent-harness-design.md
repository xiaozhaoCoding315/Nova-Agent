# Agent Harness 设计：一手资料梳理

**日期**：2026-11-23  
**研究问题**：一个成熟、可上生产的 agent harness（“agent = model + harness” 里的 harness）应该怎么设计？围绕六个维度：①循环（turn 结构、工具调用轮次、停止条件、续跑/压缩）；②工具设计（schema 校验、工具结果体积上限、并行执行、幂等、权限门控/审批、非幂等工具）；③可靠性（可重试错误、退避/抖动、Retry-After、熔断、按 provider 与全局健康、分层超时、provider fallback 链）；④上下文管理（token 计量、压缩、结构化笔记/进度文件/todo、子代理上下文隔离、摘要细节丢失）；⑤可观测与评估（tracing、该记什么、离线 eval harness、回归基线、如何度量 agent 质量）；⑥安全（权限模式、沙箱、密钥脱敏、工具输出与网页内容的提示注入处理）。  
**方法**：只使用一手来源——Anthropic 工程博客与 Claude Code / Claude Agent SDK / Claude API 官方文档，OpenAI “A practical guide to building agents” PDF 与 OpenAI Agents SDK 文档，Google ADK 文档，Vercel AI SDK 文档，LangChain / LangSmith / LangGraph 文档，以及 Cognition 的工程文章。先读原文再归纳；每条【事实】后标注来源编号，编号对应第 8 节 URL 表。不引用二手解读，不评价任何具体产品，也不讨论本项目代码。  
**取证说明**：`platform.claude.com` 的 API 文档页面在本网络会被地区重定向，正文统一从同源官方汇总 `https://platform.claude.com/llms-full.txt` 读取（[S62]，本轮 `Last-Modified: 2026-11-23T01:18:34Z`），因此这些页面的“日期”只能标 undated，并按汇总文件的 Last-Modified 说明取读时间。Claude Code / Agent SDK 页面日期取 HTML 内的 `dateModified`；Anthropic 工程文章日期取 HTML 的 `datePublished`。`platform.openai.com` 文档返回 403，OpenAI 侧改用官方 PDF 与 `openai.github.io/openai-agents-python` 一手文档。Google 侧只有 `adk.dev` 可达，未取得 Google 白皮书原文。  
**阅读提示**：【事实】= 来源直接陈述；【未验证】= 本轮一手资料未给出足够细节，不等于不存在；【张力】= 两个一手来源对同一问题给出不同取向，本文并列呈现，不替任何一方裁决。

---

## 1. 摘要（Summary）

【事实】“harness” 这个词在官方文档里有直接定义。Claude Code 文档说：agentic loop 由 model 和 tools 两个组件驱动，而 “Claude Code is the layer around the model that provides the tools and manages the context the model sees. This surrounding layer is what the term **agentic harness** refers to” [S2]。LangChain 文档的定义更窄一点：“An agent is a model calling tools in a loop until a given task is complete. A **harness** is everything around that loop: the prompt, the tools, and any middleware that shapes the model’s behavior” [S59]。两处合起来，harness 至少包含：循环控制、工具、上下文管理、权限与沙箱、可观测与评估。

【事实】不存在任何一家厂商发布的、覆盖上述六维度的单一“harness 规范”。实际知识分散在四类材料：**(a) 产品文档**（Claude Code 的循环、权限模式、沙箱、错误与重试、上下文窗口；OpenAI Agents SDK 的 runner、HITL、tracing、guardrails）；**(b) API 文档**（stop_reason、tool_result 契约、strict tool use、compaction、context editing、task budgets）；**(c) SDK 文档**（Agent SDK 的 max_turns / max_budget、subagents、OTel、permissions）；**(d) 工程博客**（context engineering、long-running harnesses、evals、tool writing、multi-agent research）[S1][S19][S22][S30][S37][S39][S40][S44][S46][S47]。

【事实】跨来源看，六维度里最一致的三条是：**循环以“模型不再发起工具调用”为正常终止条件，并且必须叠加硬上限**；**只读操作可并行、有副作用的操作必须串行或显式串行化**；**权限与沙箱必须由 harness 确定性执行，不能依赖模型自觉** [S1][S4][S5][S24][S26][S46][S52][S56]。分歧最大的是 **子代理该不该共享上下文**（Anthropic 用上下文隔离换压缩率，Cognition 主张必须共享完整 trace）[S39][S42][S55]。

---

## 2. 循环（The loop）

### 2.1 turn 的定义与正常终止

【事实】Claude Agent SDK 把 turn 定义得很精确：“A turn is one pass through the loop: Claude produces output, and if it includes tool calls, the SDK executes them and the results feed back to Claude automatically. Turns continue until Claude produces output with no tool calls, at which point the loop ends” [S1]。一次 turn 内 SDK 不把控制权交还给调用方；只有最终的无工具调用响应才会产出 `ResultMessage` [S1]。

【事实】Anthropic API 的“规范形状”是一个以 `stop_reason` 为键的 `while` 循环：请求带 `tools`；模型回 `stop_reason: "tool_use"` 和一个或多个 `tool_use` block；应用执行工具、把结果格式化成 `tool_result`；带着原消息、assistant 响应和 user 消息（内含 `tool_result`）再发一次；只要 `stop_reason == "tool_use"` 就继续。**任何其他 stop reason 都结束循环**——`end_turn`、`max_tokens`、`stop_sequence`、`refusal`，以及服务端工具循环触顶时的 `pause_turn`、输出撑满窗口时的 `model_context_window_exceeded` [S22][S24]。

【事实】OpenAI Agents SDK 的 runner 语义一致但判定条件不同：循环里若模型产出被判定为 final output 就结束——SDK 文档的定义是 “it produces text output with the desired type, and there are no tool calls”，指南另提到 final-output tool 被调用时也算结束；若请求 handoff 则切换 agent 后重跑；若有工具调用则执行、追加结果后重跑；超过 `max_turns` 抛 `MaxTurnsExceeded`，传 `None` 可关闭上限 [S47][S46]。OpenAI 的指南把这一点写成通用原则：“every orchestration approach needs the concept of a `run`, typically implemented as a loop that lets the agent call tools until an exit condition is reached” [S46]。

【事实】Vercel AI SDK 的 `ToolLoopAgent` 默认在 **20 步**后停止（`stopWhen: isStepCount(20)`），文档称这是 “a safety measure to prevent runaway loops that could result in excessive API calls and costs”；若默认上限打断了本可继续的循环，SDK 会打印警告并提示显式配置 `stopWhen` [S53]。相比之下 `generateText` / `streamText` 默认只跑一步，必须显式设置 `stopWhen` [S53]。

### 2.2 停止条件必须显式且可度量

【事实】Claude Code 团队的 “loop engineering” 文章把循环按“触发方式 / 停止方式 / 所用原语”分为四类：**turn-based**（用户每次 prompt 触发，模型自行判断完成）、**goal-based**（`/goal`，由 evaluator model 检查成功条件，未达成则送回重做，直到达成或触达 turn 上限）、**time-based**（`/loop`、`/schedule` 按间隔触发）、**proactive**（事件或计划触发、无人在场）[S45]。文章强调 “deterministic criteria, such as number of tests passed or clearing a certain score threshold, are so effective”，并建议用明确的 turn cap（例如 “stop after 5 tries”）控制成本 [S45]。

【事实】Anthropic 的 “Building effective agents” 也说，agent 的任务通常在完成时终止，但 “it’s also common to include stopping conditions (such as a maximum number of iterations) to maintain control” [S43]。

### 2.3 上限与预算：两个独立旋钮

【事实】Claude Agent SDK 提供两类上限：`max_turns` / `maxTurns`（默认无上限）和 `max_budget_usd` / `maxBudgetUsd`。计数规则很关键：**带工具调用的每个 turn 计一次，最终的无工具文本响应再计一次**；不给最后那一 turn 留额度，run 会以 `error_max_turns` 结束且没有最终答复 [S1]。触顶时 `ResultMessage.subtype` 为 `error_max_turns` 或 `error_max_budget_usd`；`result` 字段只在 `success` 变体上存在，所以必须先查 subtype 再读结果 [S1]。

【事实】预算上限是“事后比较”：Claude Code 在模型响应到达后才把花费与 `max_budget_usd` 比较，因此 “Spend can therefore pass the cap by up to the cost of that one response, plus anything that subagents still running at that moment spend before they stop”，设上限时要留余量 [S1]。`total_cost_usd` 是客户端按内置价目表估算的值，不是权威账单，不能用来对最终用户计费 [S13]。

【事实】Anthropic API 侧另有一个面向模型的**建议性**预算：`output_config.task_budget`（beta header `task-budgets-2026-03-13`），告诉 Claude 整个 agentic loop（含 thinking、工具调用、工具结果、输出）可用的 token 总数，模型拿到的是 “running countdown”，用于自我调节并 “finish gracefully (summarize findings, report progress) as it approaches the budget rather than cutting off mid-action” [S33]。文档明确 task budget 与 effort 是两个维度：effort 管每一步推理多深，task budget 管整条 loop 的工作总量 [S33]。

### 2.4 续跑与截断

【事实】服务端工具（web search、web fetch、code execution、tool search）在 Anthropic 基础设施内跑自己的循环，有迭代上限；触顶时返回 `pause_turn`，应用应把该响应原样带回继续，而不是当成完成 [S24][S22]。若 `max_tokens` 把响应截断且截断处是**不完整的 `tool_use`**，需要提高 `max_tokens` 重试该请求；若截断响应里没有 `tool_use`，可以保留它并用新的 user 消息续写 [S22]。注意把被截断的 assistant turn 作为最后一条消息重发属于 prefill，Claude 4.6 及以后会返回 400 `invalid_request_error` 拒绝 [S19]。

【事实】Claude Code 遇到 “输入 + `max_tokens` 超过上下文上限” 的拒绝时，不会原样重发（必然再失败），而是**降低 `max_tokens` 重试**；若怎么降都放不下、或已无法再降，则停止重试改为压缩 [S14]。

【事实】OpenAI 侧把“暂停—恢复”做成了持久化状态：`RunState` 可 `to_json()` / `to_string()` 落库，之后 `from_json()` 恢复；文档同时警告该快照**不做认证**，只能来自可信存储，或由应用完整校验完整性与归属 [S49]。LangGraph 侧对应的抽象是 checkpointer（线程级短期状态，用于对话连续性、human-in-the-loop、time travel 与容错）与 store（跨线程长期记忆）两套机制，并提示长对话中 checkpoint 会无限累积、推高延迟与存储成本 [S61]。

### 2.5 小结表

| 维度 | Anthropic / Claude Code | OpenAI Agents SDK | Vercel AI SDK | Google ADK |
|---|---|---|---|---|
| 正常终止 | 响应无工具调用 [S1]；API 侧 `stop_reason != tool_use` [S24] | 无工具调用的 final output [S47] | `stopWhen` 条件满足 [S53] | agent 输出 final response [S57] |
| 默认步数上限 | SDK 无上限，需自行设置 [S1] | `max_turns`（默认值未在文档中给出）[S47] | 20（`isStepCount(20)`）[S53] | 未在已读页面说明【未验证】 |
| 预算上限 | `max_budget_usd`，事后比较 [S1][S13] | 未在已读页面说明【未验证】 | 无内建预算，靠 `stopWhen` [S53] | 未在已读页面说明【未验证】 |
| 续跑 | `pause_turn` 原样带回 [S22][S24] | `RunState` 序列化 [S49] | `prepareStep` 改 messages/模型 [S53] | 未在已读页面说明【未验证】 |

---

## 3. 工具设计（Tool design）

### 3.1 schema 校验：把类型错误挡在模型采样层

【事实】Anthropic API 的 `strict: true` 通过**语法约束采样**（grammar-constrained sampling）保证工具输入严格符合 JSON Schema。文档给的理由很具体：不开 strict 时，Claude 可能返回 `passengers: "2"` 或 `"two"` 而不是 `2`，或漏掉必填字段，导致函数运行时报错；“Strict tool use guarantees type-safe parameters: Correctly typed function arguments every time; No need to validate and retry tool calls” [S27]。支持的模型与平台以文档 `featureMetadata` 为准 [S27]。

【事实】Vercel AI SDK 的 `strict` 是**逐工具、默认关闭**的：“By default, strict mode is disabled. You can enable it per-tool by setting `strict: true`”；开启后 “language model providers that support strict tool calling will only generate tool calls that are valid according to your defined `inputSchema`” [S52]。

【事实】即便如此，harness 仍需处理非法调用。Vercel 文档列出四类错误：`NoSuchToolError`（调用了未定义工具）、`InvalidToolInputError`（输入不匹配 schema）、`ToolCallRepairError`、`ToolChoiceViolationError` [S52]。OpenAI Agents SDK 对“模型调了不存在的工具”默认抛 `ModelBehaviorError`；可设 `tool_not_found_behavior="return_error_to_model"`，把错误作为 `function_call_output` 回灌给模型，让它改选工具或直接作答，使 run 可恢复 [S48]。

### 3.2 工具结果：体积上限与“给模型看什么”

【事实】Claude Code 的做法是**在 harness 侧硬截断**：“For Claude Code, we restrict tool responses to 25,000 tokens by default”，并建议对可能吃上下文的工具实现分页、范围选择、过滤和/或截断，给出合理默认值 [S37]。同一篇还强调返回“高信号”信息：优先 `name`、`image_url`、`file_type` 这类能直接影响下游动作的字段，避免 `uuid`、`mime_type` 等低层标识；把 UUID 解析成语义化名称能显著降低检索任务的幻觉 [S37]。工具可暴露 `response_format` 枚举（`concise` / `detailed`），让模型自己选择详略——示例中 concise 响应只用约 1/3 的 token [S37]。

【事实】API 本身**不截断**工具结果：“The API doesn’t truncate tool results (an oversized request is rejected). Truncate large outputs in your application before returning them to Claude” [S28]。也就是说体积控制是 harness 的责任，不是 API 的兜底。

【事实】工具失败时应回 `is_error: true` 的 `tool_result`，并且错误文本要“有指导性”：“Instead of generic errors such as `"failed"`, include what went wrong and what Claude should try next (for example, `"Rate limit exceeded. Retry after 60 seconds."`)”；文档同时提醒模型可能据此再次调用工具，所以 “limit how many retries your loop allows” [S25]。

【事实】另一条控制上下文体积的路径是**延迟加载工具定义**：Claude Code 默认把 MCP 工具 schema 延后到按需加载（tool search），在此之前只有工具名和 server 说明占上下文 [S2][S1]。Anthropic 的 “Code execution with MCP” 进一步指出，把 MCP server 当代码 API 暴露，可以让 agent 只加载需要的工具，并在执行环境里处理中间结果，避免把大文档在两次工具调用之间完整穿过上下文（示例中两小时会议转录会额外消耗约 50,000 token）[S38]。

### 3.3 并行执行：只读可并发，有副作用要串行

【事实】Anthropic API 明确把执行策略交给应用：“The API doesn’t prescribe an execution order”；“Independent, read-only operations are usually safe to run in parallel for lower latency. Tools with side effects, shared state, or ordering requirements might be better run sequentially” [S26]。协议层面的硬性要求是：**每个 `tool_use` 都要有一个 `tool_result`，全部放在下一条 user 消息里**，用 `tool_use_id` 对应；若某个调用没执行（例如串行批次中前一个失败），也要返回 `is_error: true` 的结果并说明原因 [S26]。computer use / browser use 的批量动作更严：必须按出现顺序串行，遇首个失败即停 [S26]。

【事实】Claude Agent SDK 把这条规则产品化：同一 turn 内 “Read-only tools (like `Read`, `Glob`, `Grep`, and MCP tools marked as read-only) can run concurrently. Tools that modify state (like `Edit`, `Write`, and `Bash`) run sequentially to avoid conflicts” [S1]。

【事实】Vercel AI SDK 默认并发执行同一 step 内的多个工具调用，用 `toolCallConcurrency` 限制并发度；“Use `toolCallConcurrency: 1` when later calls need to observe side effects from earlier calls” [S52]。OpenAI Agents SDK 区分两个概念：provider 侧的 `ModelSettings.parallel_tool_calls` 决定模型**是否允许**一次发出多个调用；`tool_execution.max_function_tool_concurrency` 决定 SDK **如何执行**本地函数工具调用 [S48]。

### 3.4 权限门控与审批

【事实】OpenAI Agents SDK 用 `needs_approval` 标记需要审批的工具，审批请求以 `RunResult.interruptions`（`ToolApprovalItem`）暴露；审批是 **run 级**的，handoff 之后或嵌套 `Agent.as_tool()` 里的工具审批也会浮到外层 run [S49]。可调用式审批规则**失败即关闭**（fail closed）：参数缺失、为空、只有空白、JSON 畸形、是合法 JSON 但不是对象、或含 `NaN` / `Infinity` 时，规则不被调用，直接要求人工审批 [S49]。

【事实】Claude Agent SDK 允许自定义工具设 `permission_policy: always_ask`，任何 allow 规则都不能批准它（包括 `allowedTools` 条目）；在 `dontAsk` 模式下这类调用被拒绝 [S4]。MCP 工具可通过 `_meta["anthropic/requiresUserInteraction"]` 声明需要用户交互，即使命中 allow 规则也会走到回调 [S4]。Vercel 文档给了一条很实用的模型侧配合指令：工具执行被拒绝时，在系统提示里加 “When a tool execution is not approved, do not retry it”，防止模型反复尝试同一个调用 [S52]。

【事实】Claude Code 的规则优先级里有一条安全关键事实：**deny 规则在 `bypassPermissions` 模式下仍然生效**，即使 hook 返回 `allow` 也不能批准被 deny 命中的调用 [S4]。另外，`allowed_tools` 并不约束 `bypassPermissions`——“If you set `allowed_tools=["Read"]` with `permission_mode="bypassPermissions"`, Claude Code still approves calls to tools such as `Bash`, `Write`, and `Edit`”；要挡住具体工具必须用 `disallowed_tools` [S4]。

### 3.5 幂等与非幂等工具

【事实】OpenAI 的 HITL 文档把“审批”与“恰好执行一次”明确切开：“Approval permits a tool call to execute; it does not guarantee exactly-once execution.” 若工具做了外部动作、进程在保存 run state 之前退出，从旧的已批准快照恢复会**再执行一次**（例如付款已经完成，但快照里没有付款结果）。对策是：对有后果的工具，为每个逻辑动作分配**稳定的 idempotency key**，传给一个能原子去重的目标系统，并在重试时复用同一 key 与参数；仅靠审批决定或本地完成标记无法让外部动作与本地状态成为原子操作 [S49]。

【事实】当目标系统不支持幂等、或 key 已过期时，必须先**向目标系统权威核对**再决定是否重试。文档特别指出：“A missing result in an ordinary lookup is not proof that retrying is safe: reads can lag, and an earlier request can still complete.” 若结果仍不确定，应记为 unknown 并**避免自动重放** [S49]。

【事实】Vercel 从另一个角度给出同一条边界：流式重试会丢弃失败尝试的工具输入、工具调用、审批请求与客户端工具执行，“but it cannot undo work already performed by provider-executed tools. Retrying a step after provider-side work may repeat that work or its cost. Use idempotency controls for provider-executed side effects” [S54]。

【事实】Anthropic 文档里没有找到 MCP 工具注解（`readOnlyHint` / `idempotentHint`）的对应说明；Claude Code 侧的只读判定是内建命令清单加命令分析，不是注解驱动 [S5]。一个可复用的幂等模式出现在 Anthropic 的 orchestration 示例里：为子代理分发建**内容寻址日志**——分发前用 prompt 的 SHA-256 查本地 JSON，命中就复用记录结果；中断重跑时只重算未完成的子任务 [S35]。

---

## 4. 可靠性（Reliability）

### 4.1 哪些错误可重试

【事实】Anthropic 官方 SDK 默认对**瞬时失败**自动重试**两次**（可用 `max_retries` 配置或关闭）：文档的描述是 “connection errors, rate limits, and 5xx server errors”，指数退避，并在有 `retry-after` 头时遵守它 [S19]。Claude Code 作为产品把预算调大：**默认最多重试 10 次**（`CLAUDE_CODE_MAX_RETRIES`，v2.1.186 起上限 15）；`CLAUDE_CODE_RETRY_WATCHDOG=1` 用于无人值守场景，对 `429` / `529` 容量错误无限重试，并把其它瞬时错误的默认重试次数提到 300（约三小时退避）[S14]。

【事实】Claude Code 文档列出了**不该重试**的情形，理由都是重放安全性：TLS 证书校验失败（重试无意义，应立即暴露以便修复）；**响应中途**到达的服务器错误 / 断连 / 流停滞——因为重跑请求 “could execute the same tool calls twice”，所以保留已完成内容、执行已完成的工具调用、从结果继续，而不是重发 [S14]；组织策略检查拒绝的请求（denial 针对内容而非模型，换 fallback model 也没用）[S14]。

【事实】OpenAI Agents SDK 的 runner-managed retry 是**运行时可选、默认不重试**的：“The SDK does not retry general model requests unless you set `ModelSettings(retry=...)` and your retry policy chooses to retry” [S48]。重试策略由谓词组合：`provider_suggested()`、`retry_after()`、`network_error()`、`http_status([408, 409, 429, 500, 502, 503, 504])`、`any(...)`、`all(...)`；退避参数是 `initial_delay`、`max_delay`、`multiplier`、`jitter` [S48]。安全边界写得很清楚：abort 永不重试；已经开始输出的流式 run 若重放不安全则不重试；带本地副作用否决的请求（如 Programmatic Tool Calling）不重试；provider 标记为 unsafe 的失败默认阻断，只有应用显式 `approve_unsafe_replay=True` 才放行，且该开关**不能**授权流式重试或本地副作用 [S48]。使用 `previous_response_id` / `conversation_id` 的有状态后续请求在 replay safety 未知时 **fail closed** [S48]。

【事实】Vercel AI SDK 把重试拆成两个参数：`maxRetries` 只重试“模型调用启动阶段”的失败；`streamRetries` 重试“流已经开始后收到的格式良好的 provider error event”。流式重试只重跑失败的那个 step，已完成的 step 及其工具调用/结果不重放；失败尝试的文本、推理、文件等输出不能撤回，可能在消费端出现重复或分叉；`onError` 可动态请求重试，每个逻辑 step 上限是 `streamRetries + 1` [S54]。

### 4.2 退避、Retry-After 与“不可重试的 429”

【事实】`retry-after` 必须优先于本地退避：OpenAI 的 `retry_policies.retry_after()` 只在有该提示时重试，并把该值当作**显式策略延迟**——`backoff.max_delay` 不会截断它 [S48]。Anthropic 的合规 API 文档给了缺头时的兜底：“fall back to exponential backoff (start at 1 second, double up to 60 seconds)” [S64]。

【事实】不是所有 `429` 都该退避。Anthropic API 文档区分：tier spend cap 触顶的 `429` **没有 `retry-after`**，会一直失败到下月 1 日 00:00 UTC 或升级 tier；用量陡增触发的 ramp limit 也可能在额度内返回 `429` [S19][S20]。Claude Code 因此明确 “Temporary 429 throttles, but not a gateway's spend-limit 429, which isn't a throttle”，并且即使开了 watchdog，标准速度请求遇到报告 spend limit / 用量耗尽的 `429` 也**立刻失败** [S14]。fast mode 的 `429` 则带 `retry-after`，可等容量，也可捕获后退回标准速度（代价是 prompt cache miss）[S21]。

### 4.3 熔断与上游健康

【事实】Anthropic 的 Claude apps gateway 支持多上游 failover，规则是“按顺序尝试”：`5xx`、`429`、`401`、`403`、`404`、超时和 `501` 会切到下一个上游，其它 `4xx` 不会；若上游设了 `forward_user_identity: true`，带开发者 email 的请求遇到 `429` 视为**按用户限额**，不 failover [S16]。关键限制是：“The gateway keeps no record of failed upstreams, so while an upstream is down, every request that reaches it still tries it and waits for it to fail before moving on” [S16]。也就是说，这个 gateway **没有跨请求的 provider 健康记忆**；文档未描述基于失败率的熔断或半开恢复，每个请求都要重新“试错”一遍。

【事实】Anthropic 文档里确实有熔断器语义，但作用域是 Inference hooks 的安全服务器：持续 webhook 失败会触发熔断，停止向该服务器发请求并按“Failure handling”处理所有请求；触发 3 分钟后开始探测恢复，最多约每分钟一次合成测试请求，得到有效裁决即复位 [S36]。这是“按依赖健康 + 半开探测 + 自动复位”的完整一手描述，但它不是模型 provider 的熔断。

【未验证】没有找到任何一手文档描述“按 provider 维度统计失败率并全局熔断、再按 provider 分别降级”的通用 harness 机制。Vercel / OpenAI / Google 的已读页面也没有给出 provider 健康注册表的规范。因此“per-provider vs global health”这一问题在本轮资料中只能确认到“上游逐个 failover、不记失败”和“依赖级熔断器”两个端点，中间的通用设计未文档化。

### 4.4 分层超时

【事实】Claude Code 用多个看门狗分层控制等待，且每个只负责一个阶段 [S15]：

| 看门狗 | 触发条件 | 默认值 |
|---|---|---|
| first-byte deadline | 发出请求后没有响应头 | 直连 Anthropic API 180 秒；Claude Platform on AWS / Bedrock 300 秒；另加请求体每 32KB 一秒 |
| event-level watchdog | 没有可解析的响应事件 | 300 秒 |
| body idle timeout | 完全没有字节到达（含等响应头） | 5 分钟 |

【事实】`API_TIMEOUT_MS` 只管“等响应头”，不管响应开始后流多久；在 first-byte deadline 不运行的连接上，把它设成小于 300000 的正数可以更早重试未应答的请求 [S15]。OpenAI 的 `ModelSettings.timeout` 是**每次尝试**的上限，覆盖流式与非流式、包含传输等待，但 “does not limit the full agent run, function-tool execution, or retry backoff”，且每次获准的重试都会拿到新的 per-attempt 超时 [S48]。

### 4.5 provider fallback 链

【事实】Anthropic API 提供服务端 fallback（beta `server-side-fallback-2026-07-01`）：请求里设 `fallbacks: "default"`，遇到 `stop_reason: "refusal"` 时由 API 在推荐 fallback 模型上重试；没有推荐 fallback 的 refusal 类别则保持拒绝；Claude Haiku 5.5 **没有**服务端 fallback，必须用 SDK middleware 或手写重试 [S23]。另有 fallback credit 机制，避免自己实现 fallback 时重复支付 prompt cache 成本 [S23]。

【事实】Claude Code 的产品化 fallback 链规则是：`fallbackModel` 可配多个备份模型，“Claude Code keeps at most three distinct allowed models from the list and ignores the rest”；该键**不跨设置文件合并**，最高优先级文件给出的整条链生效；切到 fallback 意味着 “one turn with a cold prompt cache”，下一条消息仍先试主模型 [S17]。组织策略拒绝的请求不会发往 fallback model [S14]。

【事实】OpenAI 侧的多模型能力主要通过 handoff 与 provider 配置实现，而非“同一请求自动换模型重试”；Vercel 则允许在 `prepareStep` 里按 step 动态换模型，这是“运行中改道”而非“失败后 fallback” [S53]。

---

## 5. 上下文管理（Context management）

### 5.1 上下文是有限资源

【事实】Anthropic 的立场是明确的：“context rot: as the number of tokens in the context window increases, the model’s ability to accurately recall information from that context decreases”；模型有一个 “attention budget”，每引入一个新 token 都在消耗它 [S39]。API 文档同样写 “As token count grows, accuracy and recall degrade… This makes curating what’s in context just as important as how much space is available” [S29]。工程结论是 “find the smallest possible set of high-signal tokens that maximize the likelihood of some desired outcome” [S39]。

【事实】上下文里到底有什么：系统提示、`messages` 中每条消息（含 tool results、图片、文档）、工具定义，以及本轮输出（含 thinking）；prompt caching 的 `cache_read_input_tokens` 与 `cache_creation_input_tokens` 也计入窗口 [S29]。Claude Code 的会话还额外加载 CLAUDE.md、auto memory、MCP 工具名、skill 描述等 [S3]。

### 5.2 计量

【事实】Anthropic 每个响应在 `usage` 里报告消耗，另有 token counting API 可在发送前估算 [S29]。Claude Code 提供 `/context` 查看按类别分解的占用，`/usage` 按 skill、subagent、MCP 分解近期用量，`/goal` 无参时显示已用 turn 数与 token [S3][S45]。Agent SDK 的 `total_cost_usd` 是本地估算，且会把 subagent 的请求计入 [S13]。

### 5.3 压缩：三种粒度

【事实】Anthropic API 的服务端压缩（compaction）把较早的 turn 替换成服务端生成的摘要，应用无需自己写摘要代码 [S30]。文档区分三种做法 [S30]：

| 做法 | 谁决定何时 | 代码量 | 近期 turn 是否逐字保留 |
|---|---|---|---|
| Compaction on demand（`compact-2026-09-04` + 顶层 `compaction`） | 应用发请求决定 | 需写一个压缩循环 | 可以，配合 keep-recent-turns |
| Compaction at a token threshold | API 在输入 token 达到阈值时 | 普通请求加一个参数 | 通过“压缩后暂停再插回”实现 |
| 自写 summarizer | 应用 | 摘要调用 + prompt + 历史重写 | 可以 |

【事实】keep-tail 压缩要求切点处不能有未闭合的工具调用：“Put the cut where no tool call is left open, with each tool call and its result on the same side”；保留的 turn 按原样（含 thinking block）发回，保留越多释放空间越少 [S31]。压缩期间若出现 `529 overloaded_error` 且 `error.details.error_code` 为 `compaction_unavailable`，属于瞬时问题，文档建议重试 [S63]。context editing 是另一条路：按规则清除旧 tool result（`clear_tool_uses_20250919`）或旧 thinking block（`clear_thinking_20251015`），beta header `context-management-2025-06-27`，服务端在 prompt 到达模型前应用，客户端仍保留完整历史 [S32]。

【事实】Claude Code 的自动压缩在接近上限时触发，并在流里发 `compact_boundary` 事件 [S1]。压缩后**不会全部丢失**：系统提示、项目根 CLAUDE.md、无 `paths:` 的规则、auto memory、skill 描述、plan mode 的 plan、git status 快照会从磁盘重新注入；Claude 读/改过的文件会按最近修改顺序**重读最多五个**，超过 5,000 token 的文件只回路径引用；已调用 skill 的正文按每 skill 5,000 token、总计 25,000 token 的上限重注入，超出时先丢最旧的 [S3]。带 `paths:` 的规则和子目录 CLAUDE.md 会被摘要掉，除非去掉 `paths:` 或移到根 CLAUDE.md [S3]。若单个文件或工具输出大到“每次摘要后立刻又填满”，Claude Code 会在几次尝试后停止自动压缩并报 thrashing 错误，而不是无限循环 [S2]。

### 5.4 压缩不够：结构化笔记与上下文重置

【事实】Anthropic 明确写过 “compaction isn’t sufficient”：即使前沿编码模型在 Agent SDK 里跨多个上下文窗口循环，仅给高层 prompt 也做不出生产级应用 [S40]。原因有两个失败模式：长任务中模型随上下文填满而失去连贯性；以及 “context anxiety”——模型接近它以为的上限时提前收尾 [S41]。

【事实】对策一：**结构化笔记**。agent 把进度写到上下文之外的持久文件，之后再读回来——例如 Claude Code 的 to-do list，或自定义 agent 维护的 `NOTES.md`，用来跨几十次工具调用保留关键上下文与依赖 [S39]。在 Agent SDK 里，这套 todo 是显式的结构化工具调用（`TaskCreate` / `TaskUpdate`，或设 `CLAUDE_CODE_ENABLE_TASKS=0` 时的 `TodoWrite`），状态机是 pending → in_progress → completed，另有 `deleted` 表示移除；它同时是给用户看的进度界面与给模型看的持久清单 [S12]。对策二：**上下文重置 + 结构化交接**。清空上下文、启动新 agent，用交接产物携带状态与下一步；它和压缩的区别是 “A reset provides a clean slate, at the cost of the handoff artifact having enough state for the next agent to pick up the work cleanly” [S41]。

【事实】Anthropic 的长任务 harness 实验给出了具体产物 [S40]：

- **initializer agent**：第一次会话建立环境——`init.sh`（能起开发服务器并跑一遍端到端测试）、`claude-progress.txt`（进度日志）、初始 git commit；并把用户一句话 prompt 扩展成一份完整功能清单（claude.ai 克隆示例里有 200+ 条），全部先标为 “failing”，让后续 agent 知道“完整功能长什么样”。
- **coding agent**：每个后续会话读进度文件与 git log、先跑基本测试、按功能逐个实现、结束时写 git commit 与进度更新，保证环境处于可合并的“干净状态”。
- 文章的核心洞察是 “finding a way for agents to quickly understand the state of work when starting with a fresh context window”，灵感来自人类工程师的日常做法。

【事实】后续的 harness 设计文章把结构升级为 planner / generator / evaluator 三角色：planner 把 1–4 句 prompt 扩成产品 spec（刻意不写太细的技术实现，避免错误级联）；generator 实现；evaluator 用 Playwright MCP 真的去点应用，按硬阈值打分；每个 sprint 前 generator 与 evaluator 先“谈判”出一份 sprint contract，定义“done” [S41]。文章也记录了一个负面结论：开箱的 Claude 是糟糕的 QA agent，会识别出问题又说服自己放过，需要多轮调 prompt 才可用 [S41]。

【事实】OpenAI 指南给出的判断顺序是：先最大化单 agent 能力，确有需要再拆多 agent；触发拆分的是复杂逻辑（prompt 里大量 if-then-else）与 **tool overload**（工具相似/重叠，而非单纯数量），并指出 “Some implementations successfully manage more than 15 well-defined, distinct tools while others struggle with fewer than 10 overlapping tools” [S46]。

### 5.5 子代理上下文隔离与摘要细节丢失

【事实】Claude Agent SDK 的子代理默认**全新上下文**：父代理只通过 Agent tool 的 prompt 字符串传信息，子代理拿不到父对话历史、工具结果、父系统提示；中间工具调用与结果留在子代理里，**只有最终消息回到父代理** [S11]。上下文工程文章给的量级是：子代理可能消耗数万 token 探索，但只返回 “a condensed, distilled summary of its work (often 1,000-2,000 tokens)” [S39]。Anthropic 的多代理研究系统把这一点作为核心收益：子代理并行、各自独立上下文，主代理只做综合；该系统在内部研究 eval 上比单 agent 高 90.2%，但代价是 token 消耗约为聊天的 15 倍，且 “token usage by itself explains 80% of the variance” [S42]。

【事实】摘要会丢细节，这一点被多份文档承认：压缩 “can result in the loss of subtle but critical context whose importance only becomes apparent later”，建议先在复杂 trace 上最大化 recall、再迭代提升 precision [S39]；Claude Code 说压缩后 “detailed instructions from early in the conversation may be lost”，持久规则应放 CLAUDE.md 而不是依赖对话历史 [S2]。

【事实】把子代理输出回灌父上下文本身是注入面：Claude Code v2.1.210+ 会扫描子代理最终消息里的“指令形状”模式——模仿 `<system-reminder>` 这类只有 harness 会发的控制标签会被就地中和（在开尖括号后插反斜杠），以 `Human:` / `Assistant:` 开头的行会被加反斜杠以防伪造 turn 边界；匹配控制标签或权限配置时会加一行 `[harness: ...]` 标记，但**从不删除或改写**子代理文本 [S11][S18]。

【张力】Cognition 明确反对“子代理并行做决策”的架构：两条原则是 “Share context, and share full agent traces, not just individual messages” 与 “Actions carry implicit decisions, and conflicting decisions carry bad results”；文中举例两个子代理各自按不同假设做出风格冲突的产物，最后合成失败 [S55]。它也指出 Claude Code 的子代理之所以可行，是因为“不与子代理并行做同一件事，且子代理通常只负责回答一个定义清楚的问题” [S55]。这与 Anthropic “隔离上下文换压缩率”的取向并不矛盾到无法共存，但两者的默认架构选择相反：一个默认隔离、一个默认共享完整 trace。

---

## 6. 可观测性与评估（Observability / eval）

### 6.1 tracing：span 结构与内容门控

【事实】Claude Agent SDK 通过 Claude Code CLI 内置的 OpenTelemetry 埋点导出三类信号，各自独立开关：metrics（token/成本计数）、log events（prompt、API 请求、API 错误、tool result）、traces（每次 interaction、模型请求、工具调用、hook 的 span）[S10]。span 层级是 `claude_code.interaction` → `claude_code.llm_request` / `claude_code.tool` / `claude_code.hook`；`claude_code.tool` 下还有等权限的 `claude_code.tool.blocked_on_user` 和执行本身的 `claude_code.tool.execution`；子代理的 span 嵌在父代理的 `claude_code.tool` 下，整条委派链出现在同一个 trace 里 [S10]。span 默认带 `session.id`，同一 session 的多次 `query()` 可按它串成时间线 [S10]。

【事实】跨系统关联靠 W3C trace context：SDK 自动把 `TRACEPARENT` / `TRACESTATE` 注入 CLI 子进程，`claude_code.interaction` 成为应用 span 的子节点；Bash 工具跑的命令也会收到 `TRACEPARENT`，其自带的 OTel span 会挂在 `claude_code.tool.execution` 下 [S10]。

【事实】一个容易踩的坑：“The CLI fails silently on export errors by default: if the endpoint is unreachable or rejects the data, the agent still runs normally and the CLI drops the telemetry without surfacing an error”；要暴露导出错误需设 `CLAUDE_CODE_OTEL_DIAG_STDERR=1` [S10]。另一个是进程被杀时批量缓冲会丢，干净退出也只做有时限的 flush [S10]。

【事实】内容默认不记录：“Telemetry is structural by default. Durations, model names, and tool names are recorded on every span… The content your agent reads and writes is not recorded by default.” 内容需逐项 opt-in：`OTEL_LOG_USER_PROMPTS`、`OTEL_LOG_TOOL_DETAILS`、`OTEL_LOG_TOOL_CONTENT`（默认截断 60 KB）、`OTEL_LOG_RAW_API_BODIES`（含完整对话历史，thinking 内容会被脱敏，开启它等于同意前三项会暴露的一切）[S10]。文档要求这些变量 “Leave these unset unless your observability pipeline is approved to store the data your agent handles” [S10]。

【事实】OpenAI Agents SDK 的默认值相反：tracing **默认开启**，且 `trace_include_sensitive_data` **默认为 True**，generation span 存 LLM 输入/输出、function span 存函数输入/输出 [S50]。要脱敏可设 `trace_include_sensitive_data=False` 或环境变量；文档还给出“在同一个应用自有 exporter 里复制、脱敏、再发送，任何一步失败就丢弃整批”的做法，并要求失败日志不含 payload [S50]。这是两家在默认隐私姿态上的实质差异，接哪家 SDK 就要按哪家的默认值做数据合规评估。

【事实】OpenAI 的 trace 结构是 trace + span：`workflow_name`、`trace_id`、`group_id`（可用来把同一会话的多次 run 串起来）、`metadata`；span 有 `trace_id`、`parent_id`、`span_data`，覆盖 agent、generation、function、guardrail、handoff、transcription、speech 等类型 [S50]。默认 `BatchTraceProcessor` 后台批量导出，进程退出时做最终 flush；长驻 worker 里可调 `flush_traces()` 保证立即送达 [S50]。

### 6.2 该记什么

【事实】Anthropic 的多代理研究文章给出的原则是：生产 tracing 要能回答“为什么失败”，同时 “we monitor agent decision patterns and interaction structures—all without monitoring the contents of individual conversations, to maintain user privacy” [S42]。Claude Code 另有一组安全审计事件，例如 `claude_code.tool_decision` 记录工具决策，便于事后审计权限判断 [S10]。文章还提到用 “rainbow deployments” 逐步切流，避免部署打断正在运行的 agent [S42]。

### 6.3 离线 eval harness

【事实】Anthropic 的 “Demystifying evals” 给出了一套可直接照抄的词汇 [S44]：

- **task**（a.k.a. problem / test case）：带明确输入与成功标准的单个测试；
- **trial**：对同一 task 的一次尝试，因输出有随机性需多次；
- **grader**：给 agent 表现打分的逻辑，一个 task 可有多个 grader，每个 grader 含多个 assertion；
- **transcript**（trace / trajectory）：一次 trial 的完整记录，含输出、工具调用、推理、中间结果；
- **outcome**：trial 结束时环境的最终状态——“A flight-booking agent might say ‘Your flight has been booked’ at the end of the transcript, but the outcome is whether a reservation exists in the environment’s SQL database”。

【事实】grader 分三类：code-based、model-based、human；code-based 适合结果可判定的场景，model-based 需要与人类评分校准，human 用于校准 [S44]。评分方式可以是加权（总分过阈值）、二值（所有 grader 必须过）或混合 [S44]。

【事实】**capability vs regression** 是两条不同的 suite：capability（quality）eval 问“这个 agent 能做好什么”，应从低通过率开始，瞄准它目前做不好的任务；regression eval 问“它是否还能处理以前能处理的全部任务”，应接近 100% 通过，下降即说明坏了。高通过率的 capability eval 可以“毕业”成持续运行的 regression suite [S44]。

【事实】**pass@k vs pass^k**：pass@k 是 k 次尝试里至少成功一次的概率，k 增大而升高；pass^k 是 k 次全部成功的概率，k 增大而下降。若单次成功率 75%，跑 3 次全过的概率是 0.75³ ≈ 42%。“Use pass@k for tools where one success matters, pass^k for agents where consistency is essential” [S44]。

【事实】起步规模不必大：“20-50 simple tasks drawn from real failures is a great start”；早期改动效果大，小样本足以看出差异；越晚建 eval 越难，因为要从线上系统反推成功标准 [S44]。好 task 的判据是 “two domain experts would independently reach the same pass/fail verdict”；每个 task 最好附一份 reference solution，证明可解且 grader 配置正确；0% pass@100 更可能是 task 坏了而不是 agent 不行 [S44]。

【事实】环境隔离会影响结论：每次 trial 应从干净环境开始，残留文件、缓存、资源耗尽会造成相关性失败；文章举了内部 eval 里 Claude 通过查看上一轮 trial 的 git 历史获得不公平优势的例子 [S44]。

【事实】必须读 transcript：“You won’t know if your graders are working well unless you read the transcripts and grades from many trials”；失败应当是“公平的”，能清楚看出 agent 哪里错了、为什么 [S44]。文章给了 CORE-Bench 的例子：Opus 4.5 起初只有 42%，排查发现是 grader 过于死板（期望 `96.124991…` 却拒绝 `96.12`）、task 描述歧义、任务本身随机不可复现，修好 grader 与放宽 scaffold 后升到 95% [S44]。

【事实】LLM-as-judge 要校准：与人类专家对齐；给模型“不知道”的出口；按维度拆成独立 judge 而不是一个 judge 打所有维度；robust 之后只需偶尔人工复核 [S44]。多代理研究文章补充：他们试过“每个组件一个 judge”，最后发现 “a single LLM call with a single prompt outputting scores from 0.0-1.0 and a pass-fail grade was the most consistent and aligned with human judgements” [S42]。两家的一手经验在“多 judge 还是单 judge”上并不一致，属于【张力】，按自己的 eval 实测选。

【事实】eval 会饱和：100% 通过的 eval 只能防回归、不再提供改进信号；SWE-Bench Verified 从 30% 起步、前沿模型已接近 >80% 饱和，越接近饱和，同样的能力提升在分数上越不明显 [S44]。文章建议 “eval-driven development”：先为计划中的能力写 eval，再迭代实现 [S44]。

【事实】其他一手来源的补充：Google ADK 把 agent eval 拆成 “Evaluate Trajectory and Tool Use”（实际轨迹 vs 期望轨迹）与 “Evaluate the Final Response”，并指出由于模型有随机性，deterministic pass/fail 常常不适用 [S57]。LangSmith 把 eval 分成 offline（在带 reference outputs 的 dataset 上）与 online（在线上 run/thread 上，无 reference outputs，只能靠启发式、安全检查与 reference-free 方法），一次“experiment”是某版本应用在一个 dataset 上的结果集，可并排比较 [S60]。OpenAI 的指南把 guardrail 与 eval 分开讲，强调 guardrail 是分层防御，并建议 “Assess the risk of each tool… low, medium, or high—based on factors like read-only vs. write access, reversibility, required account permissions, and financial impact”，高风险动作前暂停检查或升级给人 [S46]。

【事实】Anthropic 在多代理系统上给了一条 eval 边界：对会修改持久状态的 agent，“focus on end-state evaluation rather than turn-by-turn analysis”，判断最终状态是否正确，而不是判断它是否走了预设路径；复杂工作流可拆成若干 checkpoint，检查关键状态变化是否发生 [S42]。

---

## 7. 安全（Safety）

### 7.1 权限模式与确定性判定顺序

【事实】Claude Code 有六种权限模式：`default`（Manual）、`acceptEdits`、`plan`、`auto`、`dontAsk`、`bypassPermissions` [S5]。`dontAsk` 把“本该询问”的调用直接拒绝；`plan` 只允许读与只读 shell；`auto` 由一个后台 classifier 在动作执行前审查 shell 命令与网络请求；`bypassPermissions` 跳过提示，但只应在容器/VM 等隔离环境使用 [S5][S6]。

【事实】Claude Agent SDK 的判定是**固定六步，先命中先赢**：①hooks（hook 可 deny 或放行，但返回 `allow` 不会跳过后面的 deny/ask 步骤）→ ②deny 规则（命中即拒绝，**`canUseTool` 不被调用，`bypassPermissions` 下也拒绝**）→ ③ask 规则（命中则走回调，`bypassPermissions` 下也一样）→ ④权限模式 → ⑤allow 规则 → ⑥`canUseTool` 回调（`dontAsk` 下跳过并拒绝）[S4]。文档配了流程图说明这六步的走向 [S4]。

【事实】“Actions no mode auto-approves” 是硬底线，`bypassPermissions` 也不自动批准：显式 ask 规则命中的工具、组织设为 `ask` 的 connector 工具、需要用户交互的工具（`AskUserQuestion`、带 `requiresUserInteraction` 的 MCP 工具）、被识别为关键路径删除的 `rm` / `rmdir`（如 `rm -rf ~`）、跨会话消息保护、开启 `blockReadsOutsideWorkingDirectories` 后的工作目录外读取等 [S6]。`auto` 模式的 classifier 若**没有给出裁决**，Claude Code 选择拒绝而不是未审查就执行 [S6]。

【事实】权限规则由 harness 执行而非模型：“Permission rules are enforced by Claude Code, not by the model. Instructions in your prompt or `CLAUDE.md` shape what Claude tries to do, but they don’t change these rules” [S5]。子代理的权限继承也有明确规则：主会话在 `plan` 模式时，即使子代理定义写 `acceptEdits` 也仍在 `plan` 模式；`bypassPermissions` 值**从不**被继承，`auto` 只在可用时继承 [S4]。

【事实】OpenAI 的对应能力是 guardrails 与 HITL：guardrail 可以并行执行（默认，延迟低，但可能已经花掉 token、执行了工具）或阻塞执行（`run_in_parallel=False`，先检查再启动，适合成本与副作用敏感场景）；tripwire 触发即抛异常终止 [S51]。输出 guardrail 只在 agent 完成后运行 [S51]。人工介入的两个触发条件是“超过失败阈值”与“高风险动作”（敏感、不可逆、高代价），后者 “should trigger human oversight until confidence in the agent's reliability grows” [S46]。

### 7.2 沙箱：OS 级、只管 shell、网络默认空名单

【事实】Claude Code 的 Bash sandbox 是 **操作系统强制**的边界：macOS 用 Seatbelt，Linux/WSL2 用 `bubblewrap` + `socat`；默认关闭，开启后 shell 命令及其子进程都在边界内 [S7]。写入默认只允许工作目录、每用户临时目录和显式添加的目录，受保护路径保持禁写；读取默认覆盖机器大部分位置——**包括 `~/.ssh`、`~/.aws/credentials` 这类凭据文件**，要挡需配 `filesystem.denyRead` 或 `credentials` [S7]。网络没有直接出口，全部经本机代理按域名白名单检查，而**白名单初始为空** [S7]。

【事实】边界有明确局限：“The sandbox covers shell commands only. Claude’s file tools, MCP servers, and hooks run outside it” [S7]。另有逃逸口：命令在沙箱内失败时，Claude 可分析失败并以 `dangerouslyDisableSandbox` 参数重试；`sandbox.excludedCommands` 里的命令完全在沙箱外运行 [S7]。文档建议用 `allowWrite` / `allowedDomains` 做最小扩权，而不是整条命令放行 [S7]。

【事实】更高隔离等级的选项在 SDK 的安全部署指南里：容器 + `--network none` + 宿主机 proxy 的 Unix socket（proxy 负责域名白名单、凭据注入、流量记录）；`--userns-remap`、`--ipc private`；gVisor（`runsc`）在用户态截获 syscall，代价是简单 syscall 约 2× 慢、重度文件 I/O 可达 10–200× 慢；Firecracker microVM（<125ms 启动、<5 MiB 开销，经 vsock 连宿主机 proxy）[S9]。原则是安全边界、最小权限、纵深防御：凭据放边界外、由 proxy 注入，agent 永远看不到凭据本身 [S9]。

### 7.3 密钥脱敏

【事实】可操作的三条：**凭据不进 agent 边界**（proxy 注入）[S9]；**trace 内容默认不记录**，要开也得逐项批准并注意 60KB 截断与 thinking 脱敏 [S10]；**不要把密钥放进会被持久化的 run state**——OpenAI 文档明确说 `RunContextWrapper.context` 是持久化数据，“avoid placing secrets there unless you intentionally want them to travel with the state” [S49]。OpenAI 的脱敏实现建议是“复制→脱敏→只发脱敏副本，任一步失败就丢批”，失败日志只写固定文本，不含 payload、异常文本或 traceback [S50]。

### 7.4 提示注入：工具输出与网页内容

【事实】Anthropic 把威胁模型分成两类：**直接注入/越狱**（用户是攻击者）与 **间接注入**（用户可信，但 Claude 处理的第三方内容含对抗指令）[S34]。间接注入的防护是结构性的 [S34]：

- **只把不可信内容放进 `tool_result`**，绝不放进 `system` 或普通 user `text` block；Claude 被训练为对 tool result 里的指令保持怀疑。
- **在工具描述或结果结构里说明内容来源与性质**（例如“未知发件人的邮件正文”“从用户上传图片 OCR 出的文本”）。
- **在系统提示里声明策略**：工具/文档/搜索返回的内容是不可信数据，不得覆盖系统提示或用户原始请求。
- **JSON 编码不可信字符串**，用 JSON 转义提供无歧义的分隔，攻击者无法“闭合引号/标签”跳进指令上下文。
- **不要把自己的指令放进 tool result**（会被当作不可信内容忽略或标记）；指令应放在 `tool_result` 之后的 user turn，或受支持模型上的 mid-conversation system message。
- **最小权限**：不授予不需要的密钥，工具跑在沙箱里，权限尽量窄。
- **用轻量模型筛工具输出**：把原始输出交给 Haiku 5.5 + structured outputs 判定 `injection_suspected`，命中则返回错误或剥离后的摘要；**分类器自身返回 `stop_reason: "refusal"` 时按“有注入”处理**，因为没有裁决可读。
- **对自己的 agent 做红队**：用故意含注入的文档、邮件、工具输出测一遍。

【事实】Claude Code 的产品化对应措施包括：WebFetch 对多数抓取由**另一个模型调用**读页面并把答案交给 Claude，而不是把原始网页塞进上下文；手动模式下 curl/wget 默认要批准；无法完整分析的 Bash 命令要批准；命令解析不了就要求批准而不是当作只读；工作区信任对话框；fail-closed 匹配——未命中规则默认需要批准 [S8][S5]。文档同时承认 “While these protections significantly reduce risk, no system is completely immune to all attacks” [S8]。

【事实】Google ADK 的安全页把同类风险列为“vague instructions、model hallucination、jailbreaks、直接与间接注入”，并给出分层机制：身份与授权（agent-auth vs user-auth）、输入/输出 guardrails、**工具内 guardrail**（工具同时接收模型给的 arguments 与开发者确定设置的 Tool Context，用后者校验前者）、Gemini 内建安全过滤、callbacks/plugins 在执行前后校验、用便宜模型做安全筛、沙箱化代码执行、评估与 tracing、网络控制与 VPC-SC [S56]。ADK 的 callbacks 机制提供了落点：`before_model_callback` 返回 `LlmResponse` 可跳过真实模型调用；`before_tool_callback` 返回 dict 可跳过工具执行并把它当作结果；`after_tool_callback` 可替换工具结果 [S58]。

【事实】审批界面本身也是攻击面。OpenAI 的 HITL 文档要求：审批状态留在服务端；对审阅者做认证（不能从请求体取身份）；校验其有权处理该 run 与所选调用（持有 run ID 不是授权）；用服务端保存的 `get_interruptions()` 校验提交的决策，不接受客户端传来的替换工具调用或参数；用存储层做**原子、带 owner 校验的状态转换**，防止并发或重放提交把同一快照恢复两次；工具名与参数按不可信展示内容转义后再渲染 [S49]。

---

## 8. 来源（Sources）

> API 文档页面本身无日期，正文通过官方 `llms-full.txt` 读取（Last-Modified 2026-11-23T01:18:34Z）。Claude Code / Agent SDK 页面日期取 HTML `dateModified`；Anthropic 工程文章日期取 `datePublished`。所有 URL 均在 2026-11-23 用 HTTP 200 复核可达。

| ID | 来源 | URL | 日期 | 用途/备注 |
|---|---|---|---|---|
| S1 | How the agent loop works（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/agent-loop | 2026-11-19 | turn 定义、max_turns、预算、ResultMessage subtype、并行执行、自动压缩 |
| S2 | How Claude Code works（Claude Code Docs） | https://code.claude.com/docs/en/how-claude-code-works | 2026-11-21 | agentic harness 定义、上下文、压缩后丢失、thrashing、tool search |
| S3 | Explore the context window（Claude Code Docs） | https://code.claude.com/docs/en/context-window | 2026-11-17 | 上下文构成、压缩后保留什么、5 文件重读、skill 重注入上限 |
| S4 | Control execution with permissions（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/permissions | 2026-11-19 | 六步判定顺序、deny 优先于 bypass、always_ask、子代理继承 |
| S5 | Configure permissions（Claude Code Docs） | https://code.claude.com/docs/en/permissions | 2026-11-20 | 模式表、规则由 harness 执行、只读命令集、fail-closed |
| S6 | Permission modes（Claude Code Docs） | https://code.claude.com/docs/en/permission-modes | 2026-11-22 | 任何模式都不自动批准的动作、classifier 无裁决即拒绝 |
| S7 | Configure the sandboxed Bash tool（Claude Code Docs） | https://code.claude.com/docs/en/sandboxing | 2026-11-20 | OS 级沙箱、网络空白名单、凭据可读、边界局限 |
| S8 | Security（Claude Code Docs） | https://code.claude.com/docs/en/security | 2026-11-19 | 注入防护、WebFetch 摘要、信任对话框 |
| S9 | Securely deploying AI agents（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/secure-deployment | 2026-11-16 | 容器、gVisor、Firecracker、proxy 注入凭据、最小权限 |
| S10 | Observability with OpenTelemetry（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/observability | 2026-11-12 | OTel 信号、span 层级、TRACEPARENT、静默失败、内容 opt-in |
| S11 | Subagents in the SDK（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/subagents | 2026-11-19 | 上下文隔离、只回最终消息、输出扫描 |
| S12 | Todo tracking（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/todo-tracking | 2026-11-16 | TaskCreate/TaskUpdate、todo 生命周期 |
| S13 | Track cost and usage（Agent SDK Docs） | https://code.claude.com/docs/en/agent-sdk/cost-tracking | 2026-11-16 | total_cost_usd 为估算、step/session 作用域 |
| S14 | Errors（Claude Code Docs） | https://code.claude.com/docs/en/errors | 2026-11-22 | 自动重试 10 次、哪些不重试、spend-limit 429、降 max_tokens |
| S15 | Network configuration（Claude Code Docs） | https://code.claude.com/docs/en/network-config | 2026-11-22 | first-byte deadline、event-level watchdog、body idle timeout |
| S16 | Claude apps gateway configuration（Claude Code Docs） | https://code.claude.com/docs/en/claude-apps-gateway-config | 2026-11-17 | 多上游 failover 规则、不记录失败上游 |
| S17 | Settings reference（Claude Code Docs） | https://code.claude.com/docs/en/settings-reference | 2026-11-21 | fallbackModel 链、最多三个模型、不跨文件合并 |
| S18 | Subagents（Claude Code Docs） | https://code.claude.com/docs/en/sub-agents | 2026-11-21 | 子代理输出扫描、fork 语义 |
| S19 | Claude API errors（Claude API Docs） | https://platform.claude.com/docs/en/api/errors | undated | 错误码、SDK 默认重试两次、spend cap 无 retry-after |
| S20 | Rate limits（Claude API Docs） | https://platform.claude.com/docs/en/api/rate-limits | undated | spend cap、ramp limits |
| S21 | Fast mode（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/fast-mode | undated | fast 429 带 retry-after、退回标准速度、cache miss |
| S22 | Stop reasons and fallback（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons | undated | stop_reason 全表、pause_turn、截断处理、prefill 限制 |
| S23 | Refusals and fallback（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback | undated | 服务端 fallbacks: default、Haiku 5.5 无服务端 fallback、fallback credit |
| S24 | How tool use works（Claude API Docs） | https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works | undated | tool-use 契约、规范 while 循环、服务端循环 |
| S25 | Handle tool calls（Claude API Docs） | https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls | undated | is_error、指令性错误消息、限制重试次数 |
| S26 | Parallel tool use（Claude API Docs） | https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use | undated | 不规定顺序、只读并行、每个 tool_use 都要结果 |
| S27 | Strict tool use（Claude API Docs） | https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use | undated | 语法约束采样、类型保证 |
| S28 | Bash tool（Claude API Docs） | https://platform.claude.com/docs/en/agents-and-tools/tool-use/bash-tool | undated | API 不截断工具结果、超限请求被拒 |
| S29 | Context windows（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/context-windows | undated | 上下文构成、context rot、usage、token counting |
| S30 | Compaction overview（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction | undated | 三种压缩取舍、compaction_unavailable 重试 |
| S31 | Compaction that keeps recent turns（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction-keep-recent-turns | undated | 切点不能留未闭合工具调用、保留 turn 原样发回 |
| S32 | Context editing（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/context-editing | undated | tool result / thinking 清理、beta header、服务端应用 |
| S33 | Task budgets（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/task-budgets | undated | 建议性总预算、倒计时、与 effort 的区别 |
| S34 | Mitigate jailbreaks and prompt injections（Claude API Docs） | https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks | undated | 两类威胁模型、tool_result 隔离、JSON 编码、Haiku 筛输出 |
| S35 | Build an orchestration mode（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/mid-conversation-effort-example | undated | 子代理内容寻址日志、幂等 fan-out |
| S36 | Inference hooks endpoint（Claude API Docs） | https://platform.claude.com/docs/en/manage-claude/inference-hooks-endpoint | undated | 熔断器、半开探测、自动复位 |
| S37 | Writing effective tools for agents（Anthropic Engineering） | https://www.anthropic.com/research/writing-tools-for-agents | 2025-09-11（改 2026-10-13） | 25,000 token 上限、namespacing、concise/detailed、错误消息 |
| S38 | Code execution with MCP（Anthropic Engineering） | https://www.anthropic.com/research/code-execution-with-mcp | 2025-11-04 | 工具定义膨胀、中间结果重复穿过上下文 |
| S39 | Effective context engineering for AI agents（Anthropic Engineering） | https://www.anthropic.com/research/effective-context-engineering-for-ai-agents | 2025-09-29 | context rot、attention budget、compaction、note-taking、子代理 1–2k 摘要 |
| S40 | Effective harnesses for long-running agents（Anthropic Engineering） | https://www.anthropic.com/research/effective-harnesses-for-long-running-agents | 2025-11-26 | initializer agent、progress file、feature list、git、“compaction isn’t sufficient” |
| S41 | Harness design for long-running application development（Anthropic Engineering） | https://www.anthropic.com/research/harness-design-long-running-apps | 2026-03-24 | context reset vs compaction、context anxiety、planner/generator/evaluator、sprint contract |
| S42 | How we built our multi-agent research system（Anthropic Engineering） | https://www.anthropic.com/research/multi-agent-research-system | 2025-06-13 | 子代理隔离、token 方差、15× token、单 judge、rainbow deployment |
| S43 | Building effective agents（Anthropic Engineering） | https://www.anthropic.com/research/building-effective-agents | 2024-12-19 | 三原则、停止条件、ACI、poka-yoke |
| S44 | Demystifying evals for AI agents（Anthropic Engineering） | https://www.anthropic.com/research/demystifying-evals-for-ai-agents | 2026-01-09 | task/trial/grader/transcript/outcome、capability vs regression、pass@k/pass^k、20–50 task、CORE-Bench |
| S45 | Loop engineering: Getting started with loops（Claude Code team） | https://claude.com/resources/articles/getting-started-with-loops | 2026-06-30 | 四类循环、evaluator model、turn cap、token 管理 |
| S46 | A practical guide to building agents（OpenAI） | https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf | 未标（PDF） | run 循环、单/多 agent、tool overload、guardrail 分层、人工介入触发条件 |
| S47 | Running agents（OpenAI Agents SDK） | https://openai.github.io/openai-agents-python/running_agents/ | undated | runner 循环、MaxTurnsExceeded、handoff |
| S48 | Models（OpenAI Agents SDK） | https://openai.github.io/openai-agents-python/models/ | undated | 逐次超时、可选重试、重试谓词、replay safety、fail closed |
| S49 | Human-in-the-loop（OpenAI Agents SDK） | https://openai.github.io/openai-agents-python/human_in_the_loop/ | undated | needs_approval、RunState、审批≠恰好一次、idempotency key、核对 |
| S50 | Tracing（OpenAI Agents SDK） | https://openai.github.io/openai-agents-python/tracing/ | undated | trace/span 结构、敏感数据默认开启、脱敏 exporter、flush |
| S51 | Guardrails（OpenAI Agents SDK） | https://openai.github.io/openai-agents-python/guardrails/ | undated | 并行/阻塞执行、tripwire、输入/输出/tool guardrail |
| S52 | Tool Calling（Vercel AI SDK） | https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling | undated | strict 默认关、toolCallConcurrency、工具错误类型、审批后不重试 |
| S53 | Loop Control（Vercel AI SDK） | https://ai-sdk.dev/docs/agents/loop-control | undated | stopWhen、默认 20 步、prepareStep 动态改模型/压缩 |
| S54 | Error Handling（Vercel AI SDK） | https://ai-sdk.dev/docs/ai-sdk-core/error-handling | undated | maxRetries vs streamRetries、失败尝试隔离、provider 副作用不可撤 |
| S55 | Don’t Build Multi-Agents（Cognition） | https://www.cognition.ai/blog/dont-build-multi-agents | 未标 | 共享完整 trace、动作隐含决策、并行子代理冲突 |
| S56 | Safety and Security for AI Agents（Google ADK） | https://adk.dev/safety/ | undated | 风险分类、分层防护、agent-auth vs user-auth、工具内 guardrail |
| S57 | Why evaluate agents（Google ADK） | https://adk.dev/evaluate/ | undated | 轨迹评估 + 最终响应评估、test file 结构 |
| S58 | Callbacks（Google ADK） | https://adk.dev/callbacks/ | undated | before/after model/tool 的拦截与替换语义 |
| S59 | Agents（LangChain Docs） | https://docs.langchain.com/oss/python/langchain/agents | undated | agent 与 harness 的定义 |
| S60 | Evaluation concepts（LangSmith Docs） | https://docs.langchain.com/langsmith/evaluation-concepts | undated | dataset/example/experiment、offline vs online、reference-free |
| S61 | Persistence（LangGraph Docs） | https://docs.langchain.com/oss/python/langgraph/persistence | undated | checkpointer vs store、thread 级短期记忆、HITL 与容错 |
| S62 | Anthropic Developer Documentation — Full Content（官方汇总） | https://platform.claude.com/llms-full.txt | Last-Modified 2026-11-23 | 本网络读取 S19–S36、S63、S64 正文的同源入口 |
| S63 | Compaction on demand（Claude API Docs） | https://platform.claude.com/docs/en/build-with-claude/compaction-on-demand | undated | `compaction_unavailable` 529 属瞬时错误、建议重试 |
| S64 | Handle Compliance API errors（Claude API Docs） | https://platform.claude.com/docs/en/manage-claude/compliance-errors | undated | 缺 `retry-after` 时的退避兜底：1 秒起、翻倍至 60 秒 |

---

## 9. 未解问题与未验证项

【未验证】

1. **是否存在统一的 harness 规范？** 没有找到。六维度由产品文档、API 文档、SDK 文档与工程博客分别覆盖；任何“官方 harness 架构图”式的说法都缺乏一手依据。
2. **OpenAI `max_turns` 的默认值**：文档只说超过传入值抛 `MaxTurnsExceeded`、传 `None` 关闭，未在已读页面给出默认数值。
3. **Vercel `maxRetries` 的默认值**：错误处理页描述语义但未写明默认次数；`ToolLoopAgent` 的 20 步上限则明确 [S53][S54]。
4. **按 provider 的失败率统计与全局熔断**：没有任何一手文档描述通用实现。可确认的只有“gateway 逐个上游 failover 且不记录失败”与“Inference hooks 的依赖级熔断器”两端 [S16][S36]。
5. **Anthropic 工具注解（readOnlyHint / idempotentHint）**：未在已读 API 文档中找到对应机制；Claude Code 的只读判定是内建命令清单加命令分析，不是注解 [S5]。
6. **压缩的摘要质量指标**：Anthropic 建议“先最大化 recall 再提升 precision”，但没有公开阈值、评测集或可复现的对比数据 [S39]。
7. **子代理摘要的保真度**：1,000–2,000 token 是量级描述，没有给出丢失率或与全量 trace 的任务成功率对比；Cognition 的反向主张同样没有公开量化数据 [S39][S55]。
8. **LLM-as-judge 的单 judge vs 多 judge**：Anthropic 的 evals 文章建议按维度拆成独立 judge [S44]，多代理研究文章的经验是单次调用单 prompt 最一致 [S42]；两者场景不同，不能直接互相否定，需自行实测。
9. **沙箱与权限的跨平台等价性**：Claude Code 的 sandbox 在 macOS/Linux/WSL2 依赖不同内核机制，Windows 原生行为未在已读页面说明 [S7]。
10. **Google 侧的循环与可靠性细节**：本轮只取得 ADK 的 safety / evaluate / callbacks / sessions 页面，未取得 Google 白皮书或 Cloud 文档原文；ADK 的默认步数上限、重试语义与 provider 健康策略均未验证 [S56][S57][S58]。
11. **OpenAI Responses API 的限流与重试文档**：`platform.openai.com` 返回 403，本轮 OpenAI 可靠性事实来自 Agents SDK 文档与指南 PDF；Responses API 本身的 `Retry-After` 与并发限制未直接核对。
12. **API 文档无日期**：S19–S36 只能标 undated；功能状态（stable / beta / research preview）随版本变化，引用具体 beta header 时应以当日页面为准。
