# Nova Agent 论文模式开发计划与路线图

> 日期：2026-11-20  
> 关联文档：[设计文档](THESIS-MODE-DESIGN.md) · [市场调研](research/2026-11-20-thesis-assistant-market.md)  
> 许可证：Apache-2.0  
> 性质：开源项目开发计划；不含付费/商业化排期。  
> 读法：§0 一页纸 → §5 里程碑 → §4 任务分解 → §7 质量门 → §10 风险。

---

## 实施状态（2026-11-20 更新）

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 开源地基 | 已完成 | LICENSE/NOTICE、CONTRIBUTING、CODE_OF_CONDUCT、SECURITY、Issue/PR 模板、模板 schema + validator、合成样例、CI 模板校验 |
| M0 能看见问题 | 已完成 | 模式切换、项目/DOCX 导入、解析与结构树、规则引擎、证据卡、报告 |
| M1 v0.1-alpha 能修好 | 已完成（代码） | 3 个虚构演示模板、页面/边距/标题样式修复与撤销、引用 L1、AI 声明、定稿包 |
| M2 v0.2 能交付 | 代码已完成，社区项待办 | 引用 L2（Crossref DOI，30 天缓存）、引用面板、L3 实验面板、报告/CSV 含 L2/L3、文档与 CI；**10 所真实学校模板与 alpha 用户验证需要社区参与**，仓库内只有虚构演示模板 |
| M3 进阶 | 部分落地 | L3 已实现「用户 PDF + 页码/原文候选 + 人工确认」；LLM 自动判断支持度、毕设复现、Word/WPS 侧边栏、院系版未实施 |

> 说明：L3 当前是确定性定位 + 人工确认，不调用模型；扫描版 PDF 无法提取文字。毕设复现需要环境锁定与沙箱产物收集，按路线图留到后续阶段。

---

## 0. 一页纸

### 0.1 目标

在 Nova Agent 内增加「论文模式」：开源、免费、本地优先、BYOK。用户带着自己的模型，完成定稿前的格式体检、引用核验、AI 使用披露和定稿包导出。

### 0.2 v0.1 必须有什么

| # | 能力 | 验收 |
|---|---|---|
| 1 | 开发/论文模式切换 | 刷新后保持；开发模式无回归 |
| 2 | 论文项目 + docx 导入 | 原文件不被修改；有备份 |
| 3 | 3 所学校模板 + GB/T 核心规则 | 3 个样例跑通 |
| 4 | 格式体检 + 问题列表 + 证据卡 | 每条有规则/位置/当前值/建议值/依据 |
| 5 | 预览/应用/撤销 | 100 次修复不破坏文档 |
| 6 | 引用 L1（对应/重复/缺失/顺序） | 100 条标注 ≥90% 对应正确 |
| 7 | AI 使用声明 | 3 校模板可导出 |
| 8 | 定稿包导出 | 修复 docx + 报告 + 引用清单 + 声明 |
| 9 | 本地模式无需账号；不填 Key 可跑格式/L1 | 断网 + 无 Key 可完成首次体检 |

### 0.3 明确不做（v0.1）

- AI 写作/润色/降重/降 AIGC；
- 查重/AIGC 检测；
- 移动端/小程序/Web 工作台；
- Word/WPS 插件（只做「在 Word 中打开」）；
- 导师/院系协作、B 端多用户；
- 引用 L3 全文核验（v0.2+）；
- 理工毕设复现（v0.3+）；
- 自定义模板编辑器（先用 JSON + 人工维护）。

### 0.4 工作量与日历

假设：

- 1 PD = 约 6 小时有效工作；
- 1 名维护者负责产品/设计/后端/前端/发布；
- 社区贡献模板、文档、测试；
- 不含付费/运营工作。

| 里程碑 | 累计 PD | 全职 5 PD/周 | 兼职 3 PD/周 |
|---|---:|---:|---:|
| M0 能看见问题（demo） | 34–38 | 7–8 周 | 11–13 周 |
| M1 v0.1-alpha（能修好） | 58–64 | 12–13 周 | 19–21 周 |
| M2 v0.2（能交付） | 72–80 | 15–16 周 | 24–27 周 |
| M3 进阶（L3/毕设） | 92–110 | 19–22 周 | 31–37 周 |

> 设计文档里的「90 天」是目标版；上表是按 1 人维护、含测试与发布的现实版。全职 12 周可到 v0.1-alpha，兼职约 20 周。若每周只能投入 1.5 PD，日历约翻倍。

### 0.5 关键路径

```text
E1 模式切换（2–3 天，前置）
        │
E2 项目/文档 → E3 DOCX 解析 → E4 规则引擎 → E5 问题/修复 UI → E8 报告/导出
                                      ↘ E6 引用 L1/L2（可与 E4/E5 并行）
E7 AI 披露（依赖 E8 的报告模板）
```

**最大风险**：DOCX 解析与修复的兼容性。先把 E3 做扎实，再增加规则数量；宁可少 20 条规则，也不要改坏一份论文。

### 0.6 Go/No-go

M1 后：10 名 alpha 完成完整流程，100 次修复/撤销无损坏，引用 L1 ≥90%。

M2 后：30 名 alpha、100 次体检、30 份完整文档、80% 修复成功、90% 检出准确率、5 个外部模板/规则 PR。

达不到就缩窄到「格式检查 + 引用 L1」的最小工具；如果连这个都做不到，暂停论文方向，回到开发者/实验室场景。

---

## 1. 目标、原则与非目标

### 1.1 产品目标

1. 让用户在 **不换编辑器、不上传论文、不买会员** 的前提下，完成定稿前体检。
2. 每个问题都能解释：规则、位置、当前值、建议值、依据、置信度。
3. 每次修复都可预览、可撤销、不破坏原文件。
4. 没有 API Key 也能完成第一次体检；模型只是可选加速器。
5. 学校模板和规则可由社区共建，不靠一个人维护所有学校。

### 1.2 工程原则

| 原则 | 含义 | 反例 |
|---|---|---|
| 本地优先 | 文档解析、规则、修复、报告都在本机 | 先把 docx 上传到服务器再解析 |
| 规则优先 | 确定性检查用规则；LLM 只做模糊判断 | 让 LLM 直接判断页边距 |
| 写时复制 | 原文件不动，修复写新文件，可撤销 | 原地修改用户的 docx |
| 证据先行 | 没有来源/位置就不下结论 | 「疑似有问题」但说不出在哪 |
| 人类确认 | 所有修改逐条确认，不自动改正文 | 一键替换全文 |
| BYOK | 用户自己的 Key/本地模型；无 Key 可跑核心 | 强制绑定某个模型厂商 |
| 小核心 | 核心窄，模板/规则社区化 | 首期支持 100 所学校 |
| 可复现 | 规则、测试、报告都能重跑 | 只靠人工目测 |

### 1.3 非目标

- 不做「更会写论文」的 AI；
- 不做查重/AIGC 检测；
- 不做多端；
- 不做通用文档编辑器；
- 不承诺「包过/包盲审」；
- 不在核心版里加付费墙、强制账号、默认遥测。

---

## 2. 现有基础与差距

| 能力 | 现有位置 | 论文模式怎么用 | 差距/动作 |
|---|---|---|---|
| Windows 桌面端 | `desktop/main.js` | 本地起后端、打开论文项目、调用系统 Word | 增加论文模式入口 |
| 本地运行时 | `backend/app/local/` | 本地 PG、项目目录、无容器隔离 | 复用；增加 thesis 表 |
| FastAPI 路由 | `backend/app/api/v1/router.py` | 新增 `thesis.py` 并注册 | 新增路由 |
| 数据库 | `backend/app/db/init_db.py` | baseline + 增量 migration | 新增 `thesis_*` 表 |
| 工具注册 | `backend/app/core/tools/__init__.py` | 新增 thesis 工具 | 注册 6–7 个工具 |
| 前端壳 | `frontend/src/shell/AppShell.tsx` | 按产品模式渲染论文工作台 | 新增 mode store/view |
| BYOK | `backend/app/core/llm/` | 用户自选模型/Key | 复用；增加「论文任务」预设 |
| PDF 解析 | `pypdf`（`core/indexing/pipeline.py`） | 参考文献 PDF、L3 全文 | 增加 `pdfplumber` 按页/版面 |
| RAG/检索 | `backend/app/core/rag/`、`indexing/` | 在 PDF 中找引文原句 | 增加按页/段落切分 |
| 沙箱 | `backend/app/core/sandbox/` | v0.3 毕设复现 | 增加 artifact 收集 |
| DOCX 解析 | **无** | 核心 | 新增 `python-docx` + `lxml` |
| 规则引擎 | **无** | 核心 | 新增 `core/thesis/rules/` |
| 引用核验 | **无** | 核心 | 新增 `core/thesis/citations/` |
| 模板库 | **无** | 核心 | 新增 `thesis-templates/` |
| 报告模板 | **无** | 核心 | 新增 `core/thesis/report/` |

---

## 3. 总体架构

### 3.1 运行时

```text
桌面本地（主路径）
Electron (desktop/main.js)
  → 本地后端 (backend/app/local/)
  → 内嵌 PostgreSQL
  → 论文项目目录（docx / pdf / versions / exports）
  → 用户配置的模型（OpenAI-compatible / Ollama / vLLM）

自托管（实验室/宿舍）
Docker Compose
  → FastAPI
  → PostgreSQL + Qdrant
  → 浏览器访问同一套前端

模型
- 无 Key：格式检查 + 引用 L1 可用
- 有 Key：引用 L2、L3、声明生成、模糊判断
```

### 3.2 新增模块

```text
backend/app/core/thesis/
├─ models.py
├─ service.py
├─ docx/
│  ├─ parser.py
│  ├─ patcher.py
│  └─ render.py
├─ rules/
│  ├─ engine.py
│  ├─ builtin/
│  └─ templates/
├─ citations/
│  ├─ extract.py
│  ├─ metadata.py
│  ├─ match.py
│  └─ fulltext.py
├─ disclosure/
│  ├─ recorder.py
│  └─ templates.py
└─ report/
   └─ builder.py

backend/app/api/v1/thesis.py
frontend/src/views/ThesisWorkspaceView.tsx
frontend/src/thesis/
frontend/src/stores/thesis.ts
thesis-templates/
thesis-samples/
```

### 3.3 数据流

```text
导入 docx
  → 解析 OOXML
  → DocumentModel（节/段/run/样式/域/题注/脚注）
  → 规则引擎
  → Issue 列表（规则/位置/当前值/建议值/依据/置信度）
  → 预览 → 应用 → 撤销
  → 新 docx + 修改记录

引用
  → 抽取文内引用 + 文末文献
  → 对应/重复/缺失/顺序
  → 元数据核验（Crossref/OpenAlex/用户 PDF）
  → 引用证据

AI 披露
  → 本地事件记录/导入
  → 学校模板
  → 声明/脚注/Q&A

导出
  → 修复 docx + 报告 + 引用清单 + 声明 + 提交说明
```

### 3.4 关键决策

| ID | 决策 | 理由 | 影响 |
|---|---|---|---|
| D1 | 论文模式，不新增端 | 用户不换编辑器；复用桌面/本地/证据 UI | 只加模式与工作台 |
| D2 | DOCX 是唯一事实源 | 学生最终交 docx；不造编辑器 | 不做富文本编辑 |
| D3 | 规则优先，LLM 只做模糊判断 | 可解释、可测试、成本低 | 规则引擎是核心 |
| D4 | 写时复制 + 预览/撤销 | 修复破坏文档是最大信任风险 | patcher 必须保守 |
| D5 | 本地优先 + BYOK | 隐私、2C2G、开源分发 | 服务器只做控制面 |
| D6 | 无 Key 可跑核心 | 开源第一次上手不能卡在模型 | 格式/L1 不依赖 LLM |
| D7 | 模板/规则社区化 | 一个人维护不了所有学校 | 模板 schema + CI |
| D8 | v0.1 不做 L3/毕设 | 先验证「格式+引用」 | 控制范围 |

---

## 4. 工作分解（WBS）

> PD 为估算，含实现 + 自测，不含跨模块联调；实际以里程碑复盘为准。

### E1 产品模式与壳

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E1-1 | `ProductMode` store + localStorage | P1 | 1 | — | 刷新后保持 |
| E1-2 | 顶栏「开发/论文」切换 | P1 | 1 | E1-1 | 切换不丢会话 |
| E1-3 | `ThesisWorkspaceView` 骨架 + 空态 | P1 | 1 | E1-1 | 空态可操作 |
| E1-4 | 开发模式回归 | P1 | 0.5 | E1-2 | 现有测试全绿 |

### E2 论文项目与文档

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E2-1 | `thesis_*` 表 + migration | P1 | 1.5 | — | `init_db` 通过 |
| E2-2 | 项目 CRUD API + OpenAPI | P1 | 1 | E2-1 | `contract:check` 通过 |
| E2-3 | 项目目录 + docx 导入 + hash/备份 | P1 | 1.5 | E2-2 | 原文件 hash 不变 |
| E2-4 | 导入 UI + 模板选择 | P1 | 1 | E2-3 | 3 个样例可导入 |

### E3 DOCX 解析与文档模型

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E3-1 | OOXML 解析 spike（3 个样例） | P1 | 2 | E2-3 | 3 个样例可解析 |
| E3-2 | `DocumentModel` + parser | P1 | 3 | E3-1 | 节/段/样式/编号 |
| E3-3 | 域/书签/题注/脚注/页眉页脚 | P1 | 2 | E3-2 | 目录/图注可定位 |
| E3-4 | parser 单测 + round-trip | P1 | 1.5 | E3-2 | 无内容丢失 |
| E3-5 | LibreOffice 渲染/页码映射（可选） | P2 | 1 | E3-2 | 页码可用 |

### E4 规则引擎与格式规则

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E4-1 | 规则 schema + engine | P1 | 2 | E3-2 | JSON 规则可执行 |
| E4-2 | 页面/分节/页码规则 | P1 | 2 | E4-1 | 样例命中 |
| E4-3 | 标题/目录规则 | P1 | 1.5 | E4-1 | 样例命中 |
| E4-4 | 图表题注/交叉引用 | P2 | 2 | E4-1 | 样例命中 |
| E4-5 | 参考文献 GB/T 格式 | P2 | 2 | E4-1 | 样例命中 |
| E4-6 | 3 所学校模板 + golden | P2 | 2 | E4-2..5 | 3 校跑通 |

### E5 问题/证据/修复工作台

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E5-1 | 问题列表/概览/筛选 | P1 | 2 | E4-1 | 可读、可筛选 |
| E5-2 | 问题详情/证据卡 | P1 | 2 | E5-1 | 规则/位置/前后值 |
| E5-3 | 文档结构树/定位 | P1 | 2 | E3-2 | 点击定位 |
| E5-4 | 预览/应用/撤销 | P2 | 3 | E5-2 | 100 次不坏 |
| E5-5 | 忽略/批量/审计记录 | P2 | 2 | E5-4 | 记录可导出 |
| E5-6 | 导出面板 | P3 | 1 | E5-4 | 可导出 |
| E5-7 | 键盘/可访问性/细节 | P3 | 1 | E5-4 | 基本可用 |

### E6 引用 L1/L2

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E6-1 | 文内引用抽取（数字/作者年/脚注） | P2 | 2.5 | E3-2 | 100 条标注 |
| E6-2 | 参考文献列表解析 | P2 | 1.5 | E6-1 | 条目完整 |
| E6-3 | 对应/重复/缺失/顺序 | P2 | 1.5 | E6-1..2 | 标注通过 |
| E6-4 | Crossref/OpenAlex + 缓存 | P3 | 2 | E6-2 | 95% 元数据 |
| E6-5 | 引用面板/证据 UI | P3 | 1.5 | E6-3 | 可读 |
| E6-6 | 100 条准确率测试集 | P3 | 1 | E6-4 | ≥95% |

### E7 AI 使用披露

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E7-1 | 本地 AI 使用日志 | P2 | 1 | E2-1 | 记录/删除 |
| E7-2 | 导入/粘贴对话 | P2 | 0.5 | E7-1 | 可导入 |
| E7-3 | 3 校声明模板 | P2 | 1 | E7-1 | 模板匹配 |
| E7-4 | 声明 UI + 导出 | P2 | 1 | E7-3 | 可导出 |

### E8 报告与导出

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E8-1 | 报告 builder（docx/html） | P2 | 2 | E5-2 | 报告完整 |
| E8-2 | 定稿包 zip | P2 | 1 | E8-1 | 包可打开 |
| E8-3 | 引用 CSV/审计 JSON | P2 | 1 | E6-3 | 字段完整 |
| E8-4 | 报告测试/局限说明 | P3 | 1.5 | E8-1 | 人工验收 |

### E9 模板与社区

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E9-1 | 模板 schema/validator | P0 | 1.5 | — | CI 通过 |
| E9-2 | 10 所学校模板 | P3 | 2 | E9-1 | 来源可查 |
| E9-3 | CONTRIBUTING/Issue/PR 模板 | P0 | 0.5 | — | 可提 PR |
| E9-4 | 样例回归 CI | P0 | 1 | E9-1 | 每次 PR 跑 |

### E10 测试/质量/CI

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E10-1 | 黄金样例集（3 干净 + 3 问题） | P0 | 2 | — | 脱敏/标注 |
| E10-2 | 单元测试 | P1–P3 | 2 | 各模块 | 核心覆盖 |
| E10-3 | CI lint/test/build/contract | P1 | 1 | — | 全绿 |
| E10-4 | 安全测试（zip/XML/路径） | P2 | 1 | E3-2 | 用例通过 |
| E10-5 | 性能基准（5 万字） | P2 | 1 | E3-2 | <5 min / <1 GB |
| E10-6 | 手工 QA 清单 | P3 | 1 | — | 发布前执行 |

### E11 分发/文档/发布

| ID | 任务 | 阶段 | PD | 依赖 | 验收 |
|---|---|---|---:|---|---|
| E11-1 | README 论文模式/截图 | P3 | 1 | E5-1 | 可读 |
| E11-2 | 5 分钟上手 | P3 | 1 | E11-1 | 新用户可完成 |
| E11-3 | Windows 安装包 | P3 | 1 | E11-1 | 安装即用 |
| E11-4 | Docker 镜像/compose | P3 | 1 | E11-1 | 一键起 |
| E11-5 | Release checklist/checksum | P3 | 1 | E11-3/4 | 发布 |

**合计**：约 78–82 PD（含 v0.1 与 v0.2 核心）；M0 约 34–38 PD，M1 累计约 58–64 PD，M2 累计约 72–80 PD。

---

## 5. 阶段计划与里程碑

### Phase 0 — 开源地基（第 0–1 周，5–6 PD）

**目标**：仓库具备接受外部贡献的最低条件，样例与模板 schema 就位。

任务：

- LICENSE/NOTICE/README 许可证段（已完成）；
- `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、Issue/PR 模板；
- `thesis-templates/schema.json` + validator；
- `thesis-samples/`：3 个脱敏样例（1 干净、1 格式问题、1 引用问题）；
- CI 骨架：lint、单测、前端 build、模板 schema 校验；
- README 增加「论文模式」一段（可以先写目标，不写未实现功能）。

**退出标准**：

- 外部贡献者能按文档跑起本地开发；
- 3 个样例能通过 CI；
- 模板 schema 能拒绝缺 `source` 的模板。

### Phase 1 — M0「能看见问题」（第 2–7 周，30–34 PD）

**目标**：打开一份真实论文，看到可信的问题清单和一份报告；先不做修复。

任务：E1 全部、E2 全部、E3-1..4、E4-1..3（含第 1 所学校模板）、E5-1..3、E8-1、E10-2..3（E9-1/4 与 E10-1 已在 Phase 0 完成）。

**交付物**：

- 可切换的论文模式；
- 论文项目 + docx 导入；
- 1 所学校模板 + GB/T 核心规则；
- 问题列表 + 证据卡 + 文档结构树；
- HTML/docx 报告 v0；
- 3 个样例的 before/after 截图。

**退出标准**：

- 3 个样例解析无内容丢失；
- 干净样例 0 个「阻断」误报；
- 问题样例 ≥90% 预期问题被检出；
- 5 名外部用户能独立完成一次扫描。

### Phase 2 — M1 v0.1-alpha「能修好」（第 8–13 周，24–28 PD）

**目标**：不仅能看见，还能安全地修；交付定稿包。

任务：E3-5（可选）、E4-4..6、E5-4..5、E6-1..3、E7、E8-2/3、E10-4/5。

**交付物**：

- 预览/应用/撤销；
- 3 所学校模板；
- 引用 L1 + 引用面板；
- AI 使用声明；
- 定稿包（修复 docx + 报告 + 引用清单 + 声明）。

**退出标准**：

- 100 次修复/撤销无内容丢失、无 docx 打不开；
- 引用 L1 100 条标注 ≥90% 对应正确；
- 3 校样例全部跑通；
- 10 名 alpha 用户完成完整流程。

### Phase 3 — M2 v0.2「能交付」（第 14–19 周，14–18 PD）

**目标**：把「能用」变成「敢推荐给别人用」。

任务：E5-6/7、E6-4..6、E8-4、E9-2、E11。

**交付物**：

- 引用 L2（Crossref/OpenAlex）；
- 10 所学校模板；
- 社区模板贡献流程 + 样例回归；
- Windows 安装包 + Docker 镜像；
- README/5 分钟上手/FAQ；
- v0.2.0。

> v0.1.0 stable 在 M1 结束后即可打 tag；本阶段把 L2、10 所学校模板和安装包并入 v0.2.0。

**退出标准**：

- 30 名 alpha、100 次体检、30 份完整文档；
- 80% 修复成功、90% 检出准确率；
- 5 个外部模板/规则 PR；
- 安装到首次体检 <10 分钟（无 Key）。

### Phase 4 — M3 进阶（第 20 周以后，20–30 PD）

**目标**：验证 L3 全文核验与理工毕设复现，不默认全做。

任务：

- L3：用户 PDF + 页码/原文定位 + 支持度判断；
- 毕设：环境锁定、沙箱复现、图表/表格 → 代码/数据证据附录；
- Word/WPS 侧边栏 spike（只在用户明确要求时做）；
- 院系版/多用户（可选，另立计划）。

**退出标准**：

- L3 人工抽检精确率 ≥90%，否则降级为「需人工确认」；
- 毕设 5 个项目复现成功 ≥3 个；
- 侧边栏不破坏「一个产品」的边界。

---

## 6. 技术实施细节

### 6.1 产品模式

- 新增 `ProductMode = 'dev' | 'thesis'`，存 `localStorage`（键名 `nova.productMode`）。
- `AppShell` 读取模式：`dev` 渲染现有 `Workbench`，`thesis` 渲染 `ThesisWorkspaceView`。
- 顶栏加一个两段式切换；不改变现有 `useMode`（server/local）语义。
- 论文模式复用：对话、输入框、模型选择、设置、权限、轨迹。
- 验收：切换后刷新仍保持；开发模式现有测试全绿。

### 6.2 论文项目与文档

项目目录：

```text
data/users/<user_id>/thesis/<project_id>/
├─ original.docx
├─ working.docx
├─ versions/
├─ references/
├─ exports/
└─ project.json
```

- 导入时计算 SHA256；原文件只读；每次修复写新版本。
- 项目元数据进 `thesis_projects`；文档版本进 `thesis_documents`。
- 本地模式与服务器模式共用同一套目录结构（路径根不同）。
- 验收：导入 5 万字 docx <5 秒；原文件 hash 不变。

### 6.3 DOCX 解析

- `python-docx` 处理 sections/paragraphs/runs/styles/headers/footers。
- `lxml` 直接处理 OOXML：`w:fldSimple`、`w:instrText`、书签、题注、交叉引用、脚注、OMML。
- 输出统一 `DocumentModel`，不要让规则直接操作 XML。
- 页面级检查可选：检测到 LibreOffice 时 headless 转 PDF，建立页码映射；否则报告标注「未做页面级校验」。
- 解析失败要给出可读错误（哪个文件、哪一节、什么元素），不能只抛异常。
- 验收：3 个样例 round-trip 无内容丢失；单测覆盖节/页眉/题注/脚注。

### 6.4 规则引擎

规则 JSON 草案：

```json
{
  "id": "page.margin.left",
  "category": "page",
  "severity": "blocker",
  "scope": "section",
  "check": "margin_left == 3.0cm",
  "fix": "set_margin_left(3.0cm)",
  "evidence": "XX大学 2026 届模板 §4.2；GB/T 7713.1—2025 §6.3",
  "source": "template:xx-2026",
  "version": "2026.1",
  "confidence": "high"
}
```

- 规则分 `blocker / warning / info`；只有确定性规则能给 `blocker`。
- 每条规则必须有 `source` 和 `version`；没有来源的规则不进默认模板。
- LLM 只用于「这句话引用是否充分」这类模糊判断，输出 `confidence`，不直接改文档。
- 规则测试：`rules/tests/<rule_id>.json`，给输入片段和期望结果；CI 跑。
- 验收：干净样例 0 个阻断误报；问题样例 ≥90% 检出。

### 6.5 修复

- 只改目标属性：段落格式、样式、页眉页脚、题注文字、参考文献条目；不改正文内容。
- 修改前备份；修改后生成新 `working.docx`；保留 diff。
- 预览：before/after 文本片段 + 受影响段落列表；可选生成对比 docx。
- 撤销：按 `thesis_fixes` 回滚；支持单条/全部。
- 复杂域（目录、交叉引用、题注编号）提示「在 Word 中按 F9 更新」，不假装已更新。
- 破坏性检查：修复后重新解析，段落数/字数/图片数不应异常减少；异常则拒绝应用。
- 验收：100 次修复/撤销无内容丢失、无打不开。

### 6.6 引用

- L1：正则 + 规则抽取 `[1]`、`（张三，2020）`、`(Smith, 2020)`、脚注；文末参考文献按编号/作者年解析。
- L2：DOI → Crossref；标题/作者 → OpenAlex/Crossref；中文文献优先用户 PDF/人工确认。
- 状态：`已核实 / 部分匹配 / 信息不符 / 未找到 / 需人工确认 / 疑似撤稿`。
- 没有来源证据不标「已核实」；`未找到` 不等于伪造。
- L3：`pdfplumber` 按页抽取；混合检索定位候选段落；LLM 判断支持度；显示页码 + 原文 + 置信度；用户确认。
- 缓存：Crossref/OpenAlex 结果缓存 30 天；失败降级为「需人工确认」。
- 验收：100 条标注 ≥95% 元数据准确；L3 人工抽检 ≥90%。

### 6.7 AI 使用披露

- 本地表 `thesis_disclosures`：工具、版本、用途、环节、提示词、生成内容、用户修改、时间。
- Nova 自己的对话可自动记录；其他工具粘贴/导入。
- 学校模板：`disclosure.templates` 按学校配置字段和格式。
- 生成声明/脚注/答辩 Q&A；用户必须确认后才能导出。
- 不做 AIGC 检测、不帮用户掩盖 AI 使用。

### 6.8 报告与导出

定稿包：

```text
<论文名>_定稿包/
├─ <论文名>_修复版.docx
├─ 论文体检报告.docx / .html
├─ 引用核验清单.csv
├─ AI使用声明.docx
├─ 修改记录.json
└─ 提交说明.md
```

- 报告必须包含：模板版本、扫描时间、工具版本、问题清单、证据、修复状态、引用状态、局限、人工确认项。
- PDF：优先 docx/html；检测到 LibreOffice 时转 PDF；否则让用户打印。
- 验收：包能打开；报告字段完整；不包含未授权文件。

### 6.9 Agent 工具

新增工具（注册到 `backend/app/core/tools/__init__.py`）：

| 工具 | 作用 | 审批 |
|---|---|---|
| `thesis_scan` | 触发体检 | 只读 |
| `thesis_issue` | 解释某条问题 | 只读 |
| `thesis_preview_fix` | 预览修复 | 只读 |
| `thesis_apply_fix` | 应用修复 | 需确认 |
| `thesis_audit_citations` | 引用 L1/L2/L3 | 只读（L3 消耗 token） |
| `thesis_disclosure` | 生成声明 | 需确认导出 |
| `thesis_export` | 导出定稿包 | 需确认 |

- 工具结果走 SSE，前端工具卡展示进度/耗时/结果。
- 写操作必须走现有审批/快照机制；不能绕过。

### 6.10 前端

```text
frontend/src/views/ThesisWorkspaceView.tsx
frontend/src/thesis/
├─ ThesisWorkbench.tsx
├─ IssueList.tsx
├─ IssueDetail.tsx
├─ DocumentOutline.tsx
├─ CitationPanel.tsx
├─ DisclosurePanel.tsx
├─ ExportPanel.tsx
└─ TemplatePicker.tsx
frontend/src/stores/thesis.ts
```

- 不做富文本编辑器；不做 PDF 查看器。
- 问题详情显示段落文本 + 位置；「在 Word 中打开」调用系统默认程序。
- 引用证据显示页码 + 原文片段 + 来源链接。
- 复用现有 `SignalGutter`/证据视觉语言，但不要为了复用而扭曲信息结构。
- 验收：1280px 宽下三栏可用；键盘可达；空态/加载/错误齐全。

### 6.11 数据模型

```text
thesis_projects(id, user_id, title, school, college, degree, major, template_id, created_at)
thesis_documents(id, project_id, version, filename, sha256, page_count, word_count, path)
thesis_issues(id, project_id, document_id, rule_id, category, severity, location_json,
              current, expected, evidence, fix_type, confidence, status)
thesis_fixes(id, issue_id, before_json, after_json, applied_at, undone_at)
thesis_citations(id, project_id, document_id, raw, normalized_json, kind, status, confidence)
thesis_citation_evidence(id, citation_id, source, url, page, quote, support, confidence)
thesis_disclosures(id, project_id, tool, version, purpose, stage, prompt, output, modified, created_at)
thesis_templates(id, school, college, degree, year, rules_json, source, version)
thesis_reports(id, project_id, document_id, kind, path, created_at)
```

- 迁移加到 `backend/app/db/init_db.py` 的增量 migration；不要改 baseline 历史。
- 所有表带 `user_id` 或通过 `project_id` 做 owner 校验（复用现有隔离方式）。

### 6.12 API

```text
POST   /api/v1/thesis/projects
GET    /api/v1/thesis/projects
POST   /api/v1/thesis/projects/{id}/documents
POST   /api/v1/thesis/projects/{id}/scan
GET    /api/v1/thesis/projects/{id}/issues
GET    /api/v1/thesis/issues/{id}
POST   /api/v1/thesis/issues/{id}/preview
POST   /api/v1/thesis/issues/{id}/apply
POST   /api/v1/thesis/issues/{id}/undo
POST   /api/v1/thesis/projects/{id}/citations/audit
POST   /api/v1/thesis/projects/{id}/disclosure
POST   /api/v1/thesis/projects/{id}/export
GET    /api/v1/thesis/projects/{id}/versions
```

- 更新 `contracts/openapi.json` 与 `frontend/src/lib/api-schema.d.ts`；`npm run contract:check` 必须通过。
- 长任务走现有 Job/SSE 机制，不要新造轮子。

### 6.13 性能与安全

| 项 | 目标 |
|---|---|
| 5 万字 docx 扫描 | <5 分钟 |
| 内存峰值 | <1 GB |
| 导入 | <5 秒 |
| 修复 100 条 | <2 分钟 |
| 崩溃/内容丢失 | 0 |
| docx 解压后大小 | 限制（防 zip bomb） |
| XML | 禁用外部实体 |
| 路径 | 限定项目目录 |
| 宏 | 不执行 |

---

## 7. 测试与质量门

### 7.1 质量门

| Gate | 时间 | 标准 |
|---|---|---|
| G0 解析 | M0 前 | 3 个样例 round-trip 无内容丢失；页眉/题注/脚注可定位 |
| G1 M0 | 第 7 周 | 干净样例 0 阻断误报；问题样例 ≥90% 检出；5 名用户独立完成 |
| G2 M1 | 第 13 周 | 100 次修复/撤销无损坏；引用 L1 ≥90%；10 名 alpha 完成全流程 |
| G3 M2 | 第 19 周 | 30 alpha、100 体检、30 完整文档、80% 修复成功、5 个外部 PR |
| G4 发布 | 发布前 | 无 P0 bug；安装到首次体检 <10 分钟（无 Key）；checksum/changelog 齐全 |

### 7.2 测试类型

- **单元测试**：parser、rules、citation extraction、report builder。
- **黄金样例**：3 干净 + 3 问题；每个规则至少 1 个正例/负例。
- **回归**：Word/WPS/LibreOffice 打开的 docx；修复后重新解析。
- **安全**：zip bomb、XML 外部实体、路径穿越、超大文件、宏。
- **性能**：5 万字论文、1000 条引用、100 个问题。
- **手工 QA**：安装、导入、扫描、修复、撤销、导出、无 Key、断网。
- **用户测试**：30 名 alpha；记录完成率、卡点、耗时、NPS（自愿）。

---

## 8. CI/CD 与发布

### 8.1 CI（GitHub Actions）

| Job | 内容 | 触发 |
|---|---|---|
| backend | `pytest`、lint | PR |
| frontend | `tsc -b`、`vite build`、`contract:check` | PR |
| templates | schema 校验 + 样例回归 | PR（模板改动） |
| security | 依赖扫描/基础 SAST | PR/每周 |
| desktop | Windows 安装包构建（可手动） | tag/手动 |
| docker | 镜像构建 | tag/手动 |

### 8.2 发布

- 版本：SemVer；`v0.1.0-alpha.1` → `v0.1.0` → `v0.2.0`。
- 产物：Windows 安装包、Docker 镜像、源码 zip、SHA256。
- Release notes：新增/修复/已知问题/模板变更/迁移说明。
- 发布节奏：alpha 每 2 周；stable 每月或不定期。

### 8.3 支持矩阵

| 项 | 支持 |
|---|---|
| Windows | 10/11 x64（主路径） |
| macOS/Linux | Docker/源码（v0.1 不作为桌面安装包） |
| Word | 2016+（docx） |
| WPS | 最新版（兼容测试） |
| LibreOffice | 可选，用于页面级校验 |
| Python | 3.12 |
| Node | 20+ |
| PostgreSQL | 16 |

### 8.4 发布清单

- [ ] 版本号/CHANGELOG
- [ ] 后端测试/前端构建/contract check
- [ ] 3 个样例回归
- [ ] 安装包在干净 Windows 上安装/卸载
- [ ] Docker compose 冷启动
- [ ] 无 Key 首次体检
- [ ] 断网首次体检（格式/L1）
- [ ] 导出包可打开
- [ ] SHA256/Release notes
- [ ] 已知问题/局限

---

## 9. 社区与开源运营

### 9.1 贡献类型

- 学校模板（最高价值）；
- 规则/测试样例；
- 引用适配器（公开 API）；
- 文档/翻译/上手视频；
- Bug 报告/复现样例；
- UI/可访问性改进。

### 9.2 模板贡献流程

```text
thesis-templates/<school-slug>/<degree>/<year>/
├─ template.json      # 规则与页面设置
├─ SOURCE.md          # 来源 URL/文件/日期/适用范围
├─ sample.docx        # 脱敏样例（可选但推荐）
└─ expected.json      # 期望问题（用于回归）
```

- PR 必须通过 schema 校验和样例回归。
- 只编码规则，不搬运学校模板原文；`SOURCE.md` 记录来源。
- 维护者审核来源、版权、误报；不合规的模板不合并。

### 9.3 Issue/PR 模板

- Bug：版本/系统/Word 版本/复现步骤/脱敏片段/期望行为。
- 模板请求：学校/学院/学位/年份/来源/规则清单。
- 规则误报：规则 ID/位置/当前值/为什么是误报/脱敏片段。
- PR：目的/改动/测试/截图/是否影响模板。

### 9.4 治理

- `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`；
- `good first issue` 标签；
- DCO sign-off（Apache-2.0 不强制 CLA）；
- 维护者保留合并/发布权；
- 安全漏洞走私密报告（`SECURITY.md`）。

### 9.5 文档

- README：论文模式、5 分钟上手、截图/GIF；
- `docs/THESIS-MODE-DESIGN.md`：设计；
- `docs/THESIS-MODE-ROADMAP.md`：本计划；
- `docs/thesis-template-guide.md`：模板作者指南；
- FAQ：无 Key、断网、Word/WPS 兼容、误报、隐私。

### 9.6 隐私

- 默认无遥测；不收集论文内容/路径/行为；
- 崩溃报告 opt-in，不含文档内容；
- 设置页列出所有外联端点；
- 「仅本地」模式：禁用 Crossref/OpenAlex 与模型调用。

---

## 10. 风险登记册

| 风险 | 概率 | 影响 | 缓解 | 触发/停止条件 |
|---|---|---|---|---|
| DOCX 修复破坏文档 | 高 | 高 | 写时复制、预览/撤销、修复后重解析、黄金样例 | 任何内容丢失 → 停止发布，先修 parser |
| parser 覆盖不足 | 高 | 高 | 先 3 个样例；失败给可读错误；不支持的文档明确提示 | 样例解析成功率 <80% → 缩窄支持范围 |
| 页面级检查不准 | 中 | 高 | LibreOffice 可选；报告标注局限；不承诺打印一致 | 页码误报 >10% → 只做结构级 |
| 引用元数据不准 | 中 | 高 | 来源证据/置信度/人工确认；中文优先用户 PDF | 元数据准确率 <90% → 降级为「需人工确认」 |
| 中文库访问受限 | 高 | 高 | 公开 API/用户 PDF/人工；不爬知网 | 无法获得来源 → 不做 L2 中文自动核验 |
| Word/WPS 兼容 | 中 | 高 | 先 Word；WPS 测试；LibreOffice 校验 | 任何打不开 → 阻塞发布 |
| 模板维护成本 | 高 | 中 | 首批 10–20 所；社区 PR；schema/CI | 模板月维护 >2 PD → 缩窄学校数 |
| 模板版权 | 中 | 高 | 只编码规则；SOURCE.md；不搬运原文 | 收到侵权投诉 → 下架模板 |
| 范围蔓延 | 高 | 高 | 非目标清单；阶段门；L3/毕设后置 | 新需求不进 v0.1 |
| 社区冷启动 | 高 | 中 | 样例/演示/2–3 个学校试点；good first issue | 3 个月无外部 PR → 简化贡献流程 |
| 模型差异 | 中 | 中 | 规则优先；置信度；用户可换模型复跑 | 同一问题模型结论冲突 → 只显示「需人工确认」 |
| 性能不达标 | 中 | 中 | 5 万字基准；分页/流式；本地执行 | 扫描 >10 分钟 → 优化或缩窄 |
| 安全漏洞 | 中 | 高 | zip/XML/路径限制；依赖扫描；SECURITY.md | 高危漏洞 → 立即修复/发版 |
| 学术诚信争议 | 中 | 高 | 明确辅助定位；禁止代写/降重；AI 披露 | 被误解为代写 → 调整文案/功能 |
| 维护者倦怠 | 高 | 高 | 窄 MVP；社区；不承诺日期；阶段复盘 | 连续 2 周无进展 → 缩窄范围 |

---

## 11. 指标与决策点

### 11.1 指标

**产品**

- 首次体检完成率；
- 完整文档上传数；
- 问题检出准确率（人工标注）；
- 修复成功率；
- 复检率；
- 导出定稿包数；
- 无 Key 首次体检占比。

**质量**

- docx 损坏率（目标 0）；
- 崩溃率；
- 5 万字扫描耗时/内存；
- 引用元数据准确率；
- 误报率（用户标记「忽略」的比例）。

**社区**

- GitHub stars/forks；
- Release 下载量；
- Issue 首次响应时间；
- PR 合并率；
- 外部模板数/规则 PR 数；
- 贡献者数。

> 默认无遥测；上述使用指标通过可选匿名统计、GitHub 数据、用户访谈/自报获得。

### 11.2 决策点

| 决策点 | 时间 | 看什么 | 决定 |
|---|---|---|---|
| Gate 0 | Phase 0 结束 | 样例/CI/schema | 继续或补地基 |
| Gate 1 | M0 结束 | 解析/误报/5 名用户 | 继续修，或缩窄规则 |
| Gate 2 | M1 结束 | 10 alpha/完整流程/修复无损坏 | 继续 v0.2，或缩窄到只读 |
| Gate 3 | M2 结束 | 30 alpha/100 体检/5 外部 PR | 做 L3/毕设，或维持 |
| Gate 4 | M3 结束 | L3 精确率/毕设复现率 | 合并/实验性/停止 |

### 11.3 停止/转向条件

- 任何内容丢失或 docx 打不开：停止发布，先修 parser；
- 修复成功率 <50%：缩窄为「只读体检 + 报告」；
- 首次体检完成率 <30%：先修上手流程，不加功能；
- 3 个月无外部模板/规则 PR：简化模板模型，或只维护 3 所学校；
- 维护者连续 2 周无法投入：缩窄范围，发「维护模式」说明。

---

## 12. 近 10 个工作日

> 目标：跑通「模式切换 → 导入 docx → 解析 → 2 条规则 → 问题列表」的最小闭环，不做修复。

| 天 | 任务 | 产出 |
|---|---|---|
| D1 | 建分支、Issue/PR 模板、样例目录、roadmap 链接 | 仓库骨架 |
| D2 | `ProductMode` store + 顶栏切换 | 开发/论文可切 |
| D3 | `ThesisWorkspaceView` 骨架 + 空态 | 论文模式可见 |
| D4 | `thesis_projects`/`thesis_documents` 表 + migration | 本地库可建项目 |
| D5 | 项目 CRUD + docx 导入 API | 可导入样例 |
| D6 | DOCX 解析 spike（3 个样例） | 解析报告 |
| D7 | `DocumentModel` + 文档结构树 | 章节可显示 |
| D8 | 规则引擎骨架 + 2 条规则（页边距/标题） | 可产出 Issue |
| D9 | 问题列表 + 证据卡（真实数据） | 最小工作台 |
| D10 | 演示 + 复盘 + 调整估算 | demo/风险清单 |

**D10 验收**：打开样例论文，看到章节树和至少 2 类问题；刷新后项目还在；原文件 hash 不变。

---

## 13. 假设与待确认

1. **首批 3 所学校**：建议 1 所普通本科人文社科、1 所师范/综合类硕士、1 所理工本科；需要拿到 2026 模板/学院通知。
2. **时间投入**：上表按全职 5 PD/周或兼职 3 PD/周；如果实际更低，日历顺延。
3. **Windows 优先**：v0.1 只做 Windows 安装包；macOS/Linux 走 Docker/源码。
4. **LibreOffice 可选**：不打包进安装包；检测到就用，检测不到就标注「未做页面级校验」。
5. **L3 时间**：默认 v0.2/v0.3；如果 alpha 用户强烈要求，可提前，但不要挤占 M1。
6. **NOTICE 版权主体**：当前为 `The Nova Agent Authors`；如要改成个人/组织，发布前改。
7. **模板来源**：只编码规则，不搬运学校模板原文；需要逐校确认来源与版权。

---

## 14. Definition of Done

### 功能

- 验收标准全部满足；
- 单测/样例回归通过；
- 文档更新（README/设计/模板指南）；
- 不影响开发模式；
- 无 P0/P1 bug。

### PR

- 说明目的/改动/测试；
- 截图/GIF（UI 改动）；
- 模板改动附 `SOURCE.md` 和 `expected.json`；
- DCO sign-off；
- CI 全绿。

### 模板

- `template.json` 通过 schema；
- `SOURCE.md` 有来源/日期/适用范围；
- 样例回归通过；
- 误报有记录/解释。

### 发布

- 版本号/CHANGELOG；
- Windows/Docker 产物；
- SHA256；
- 安装→首次体检→导出 全流程手工验证；
- 已知问题/局限写进 Release notes。

### 安全

- 无新增高危依赖；
- zip/XML/路径限制有测试；
- 安全漏洞有私密报告渠道。

---

## 15. 一句话

**先用 3 个样例把「能看见问题」做出来，再用 3 所学校把「能修好」做扎实，最后才谈社区、L3 和毕设；每一步都有可验证的退出标准，不靠感觉推进。**
