# Nova Agent 上线推进路线图

> 目标：补齐简历亮点对应功能，实现 Docker 一键部署，让项目从"本机 demo"变成"可演示、可追问、可复现"的完整产品。
> 决策已确认：先 Skill 后部署；部署目标为本机 Docker 一键启动 + 虚拟机常驻双轨；Function-Calling 主力模型 DeepSeek。

## 完成状态（2026-08-20 更新）

- **Phase 1 全部完成**：tools 模块（calculator/db_query/doc_parser）、LLM astream_with_tools、chat 4 轮 Agent 循环、SSE tool_call/tool_result 事件、前端工具卡片。208 单测全过；本机真实 LLM 端到端验证通过（LLM 自主调用 calculator + db_query 查询知识库统计）。
- **Phase 2.1 完成**：docker-compose.yml 全家桶、多阶段 Dockerfile（pip 走清华镜像）、.env.docker.example、AUTO_INIT_DB 幂等初始化。
- **Phase 2.2 完成**：虚拟机 192.168.150.128 常驻部署（docker-compose.vm.yml，backend 容器经 host.docker.internal 连宿主机原生数据库，保留既有 174 文档数据），局域网可访问 http://192.168.150.128:8000（health OK、前端页面挂载、容器 healthy）。
- **Phase 3 部分完成**：README 已重写部署章节并补「Agent Skill 工具集」亮点。

## 待办（阻塞项）

1. **LLM Key 额度耗尽**：唯一配置的 LongCat 返回 402（Token 额度不足），DeepSeek/DashScope key 为空 → 当前 chat 不可用。建议配置 DASHSCOPE_API_KEY（阿里云百炼：LLM 用 qwen 系列 + embedding 用 text-embedding-v3，一个 key 全解决）或 DEEPSEEK_API_KEY。配好后：更新 VM 上 /opt/nova-agent/.env → `docker compose -f docker-compose.vm.yml up -d` 重建容器。
2. **Embedding 依赖 DASHSCOPE_API_KEY**：key 为空期间 dense 向量检索一直降级（BM25+graph 两路可用）、知识库上传不可用。配 key 后恢复三路召回。
3. 次要：token 统计仍是 chunk 计数；git 提交与 GitHub 推送待用户确认。

---

## 现状结论（2026-08-19 全量扫描）

已真实实现且质量过关：三路混合 RAG（dense/BM25/graph + RRF）、四层记忆（session/facts+TTL衰减去重/graph/DAG运行时）、自研 DAG 引擎、harness 分级容错、Docker 沙箱、RAGAS 评测、多厂商 LLM 降级、前端六面板全对接、30+ 测试文件。

两大缺口：

1. **Agent Skill 工具集 + Function-Calling 完全缺失** —— 简历四大亮点中唯一没有代码实现的。chat 链路是纯 RAG 问答，harness 预留了 tool_timeout=30s 但工具系统不存在。
2. **容器化部署停留在 README** —— 无 docker-compose.yml；.env 数据库指向局域网 VM(192.168.150.128)；Dockerfile 极简；无线上可访问形态。

次要问题：token 统计是 chunk 计数；README 引用的 docs/ 设计文档不存在。

---

## Phase 1：Agent Skill 工具系统（补简历最大缺口）

### 1.1 后端 tools 模块（新建 `backend/app/core/tools/`）

- `base.py`：`ToolDefinition`（name/description/parameters JSON Schema/execute）、`ToolRegistry`（注册、按名查找、导出 OpenAI tools 格式）、统一入参校验（Pydantic）、统一异常捕获、harness 包装执行（复用 tool_timeout）
- `calculator.py`：计算器——安全 AST 求值，禁 eval，白名单运算符
- `db_query.py`：数据库查询——只读 SELECT、表白名单、LIMIT 强制、超时控制
- `doc_parser.py`：文档解析——复用 knowledge/pipeline 的解析能力，按文件名/ID 取知识库文档并返回分块摘要
- `__init__.py`：默认注册三个工具，导出 registry

### 1.2 LLM 接口扩展

- `LLMProvider.astream` 支持 tools 参数与 tool_calls delta 解析（新增 `astream_with_tools`）
- FallbackLLM：tool_calls 请求失败时降级为无工具纯文本回答
- factory：DeepSeek 为主力（原生 Function-Calling），配置透传

### 1.3 chat 链路接入 Agent 循环（`api/v1/chat.py`）

- SSE 新增事件：`tool_call`（工具名+参数）、`tool_result`（结果+耗时）
- 循环：LLM 决策 → harness 保护执行工具 → 结果回填 messages → 继续生成（上限 4 轮）
- 工具调用写入会话记忆与审计日志

### 1.4 前端展示

- MessageBubble 新增工具调用卡片（工具名/参数/结果/耗时，可折叠）
- useSSE/ChatWindow 处理新事件类型

### 1.5 测试

- 单测：registry 注册查找、三工具各自行为、参数校验失败路径、chat 工具循环（mock LLM 返回 tool_calls）
- 更新 test_chat_api

## Phase 2：双轨部署（compose 一键复现 + 虚拟机常驻演示）

> 已确认：数据库服务（PG/Qdrant/Neo4j）已常驻部署于 192.168.150.128 虚拟机，开发测试直连即可。

### 2.1 docker-compose 一键复现（根目录 docker-compose.yml）

- 服务：pgvector/postgres + qdrant + neo4j + backend（FastAPI 托管前端 dist）
- 健康检查、depends_on condition、数据卷持久化
- backend/Dockerfile 改进：多阶段（node 构建前端 → python 运行时）、非 root、HEALTHCHECK
- `.env.docker` 模板：数据库主机指向 compose 服务名（与 .env 的虚拟机地址解耦，两套配置并存）

### 2.2 虚拟机常驻部署

- backend + 前端产物部署到 192.168.150.128，局域网可访问演示地址
- 用 .env 直连同机数据库（localhost），supervisor/systemd 或 docker 常驻
- 初始化自动化：启动时 init_db 幂等建表、Qdrant collection、Neo4j 约束

### 2.3 README 重写部署章节

- `git clone → docker compose up -d → localhost:8000` 一条链路
- 架构图与功能截图、功能演示 GIF

## Phase 3：收尾验证

- 全量 pytest 通过；端到端手测（上传→RAG问答→工具调用→DAG→评测）
- token 统计修正（tiktoken 或字符估算）
- docs/ 补设计文档或删除 README 引用
- GitHub push，简历链接可访问性验证

---

## 风险与注意

- 沙箱功能依赖 Docker-in-Docker，compose 部署下标记为可选（本机跑 Docker Desktop 时 sandbox 状态接口如实返回降级）
- Neo4j 内存占用较高，compose 中限制堆内存
- DeepSeek tool_calls 格式遵循 OpenAI 规范，FallbackLLM 需保证非 DeepSeek 备选不支持工具时优雅降级
