# M1 阶段报告：契约与事实层

> 日期：2026-11-21  
> 分支：`feat/thesis-mode-m0`  
> 对应路线图：[PRODUCT-UPGRADE-ROADMAP.md](PRODUCT-UPGRADE-ROADMAP.md) 的 M1  
> 性质：阶段交付说明，不是发布公告。未完成项在 §5 明确列出。

---

## 1. 本阶段做了什么

M1 只做事实语言，不铺新界面：

1. **CAP-01 统一验证结果**：验证结果不再只有 `passed / failed`。新增 `not_run / skipped / unsupported`，并记录命令、退出码、超时、耗时、原因、步骤集合。
2. **CAP-02 隔离事实披露**：每次验证结果携带执行模式（容器/本机）、隔离等级、网络策略、工作目录范围、敏感环境剥离情况、镜像信息。
3. **工作区绑定**：验证结果记录 HEAD commit、分支、是否有未提交改动、工作区摘要与 diff 摘要；仓库不是 Git 仓库时来源字段明确写 `not_git`。
4. **文档 IR/变更/版本契约**：定义块级/行内文档模型、来源定位、变更集、版本引用、保真报告、能力清单；提供 Markdown 解析与 JSON 序列化。
5. **远程事件/意图契约**：定义进度事件、审批请求、设备、命令信封、风险映射、审计字段、重放防护与命令校验策略。**本阶段没有实现任何网络监听或连接器。**
6. **文案基线**：新增 [COPY-GUIDELINES.md](COPY-GUIDELINES.md)，清理首批 AI 口吻文案。

---

## 2. 交付物与代码位置

| 交付 | 位置 |
|---|---|
| 验证事实模型 | `backend/app/core/verify/results.py` |
| 验证服务接入 | `backend/app/core/verify/service.py` |
| API 响应字段 | `backend/app/models/schemas.py`（`VerifyResultOut.report`） |
| 前端验证展示 | `frontend/src/views/WorkspaceView.tsx`、`frontend/src/lib/types.ts` |
| 文档 IR | `backend/app/core/documents/ir.py` |
| Markdown 解析 | `backend/app/core/documents/markdown.py` |
| IR 序列化/校验 | `backend/app/core/documents/serialize.py` |
| 远程契约 | `backend/app/core/remote/contracts.py` |
| 远程命令策略 | `backend/app/core/remote/policy.py` |
| 契约测试用 HMAC | `backend/app/core/remote/crypto.py` |
| 文案规范 | `docs/COPY-GUIDELINES.md` |
| 契约导出 | `contracts/openapi.json`、`frontend/src/lib/api-schema.d.ts` |

兼容性：验证结果的旧字段（`status / steps / image / exit_code / stdout / stderr / command / at / elapsed_ms`）保留，新字段放在 `report` 中。旧前端不读 `report` 也不会坏；新前端优先读 `report`，缺失时退回旧字段。

---

## 3. 测试与检查

| 检查 | 结果 |
|---|---|
| `backend/tests/test_document_ir.py` | 9 passed |
| `backend/tests/test_remote_contracts.py` | 16 passed |
| `backend/tests/test_verification_facts.py` | 8 passed |
| 全量后端测试 | 见 §6 的最终记录 |
| `npm run build` | 通过 |
| `npm run contract:check` | 通过 |
| OpenAPI 重新生成 | 通过 |

测试覆盖的关键行为：

- 验证状态聚合：必需步骤失败会压过后面的跳过；可选步骤失败不把整体判成失败，但会保留可见。
- 未运行/不支持不会被折叠成 `failed`；本机执行明确写 `isolation: none`。
- 文件摘要对路径与内容稳定；同一内容不同顺序得到同一摘要。
- Markdown 中的 HTML 块、脚注、公式块不会被静默丢弃，而是保留原文并产生 `unsupported` 诊断。
- 文档 IR 的 JSON 往返与内容哈希稳定；未知 schema 版本被拒绝。
- 变更集基线哈希不匹配时拒绝应用。
- 保真报告只有 `exact` 才允许当作无损导出。
- 远程命令：过期、超时、时钟偏移、设备撤销、权限不足、签名缺失/错误、重放、动作哈希不匹配、高风险远程审批、审批过期、未开启 resume 都会被拒绝。

---

## 4. 文案清理

规范见 [COPY-GUIDELINES.md](COPY-GUIDELINES.md)。本阶段完成的首批修改：

- Agent 身份提示：去掉“擅长…”的自我描述，改为“结论要能回到代码、命令或用户提供的材料”。
- Builder 设计对话：去掉“轻松的多轮对话”“耐心的技术朋友”，改为直接、具体的行为描述。
- 论文写作约定：改为“负责论文写作与工程理解的辅助工作”，保留“不是代写工具”的边界。
- 前端：`AI 写作助手` → `写作对话`；`一键把这一轮…` → `把这一轮…`；`一键启动` → `启动命令`；`让 AI 理解项目…` → `读项目、搭提纲、写章节草稿…`；`可一键复制引用` → `可直接复制引用`。

保留项：`AI 草稿 · 需本人核对`、`AI 使用声明`、`无容器隔离`。这些是事实披露，不是 AI 口吻。

---

## 5. 验收对照（诚实状态）

路线图 M1 的五条验收：

| 验收项 | 状态 | 说明 |
|---|---|---|
| 失败/跳过/未运行/工具缺失四类样例与命令结果一致；同一 commit 可对比 | 部分完成 | 状态模型、原因字段、聚合规则与单元测试已完成；Docker 真实任务的四类端到端样例尚未跑。 |
| 同一任务在 Docker 与本机运行，结果页显示不同环境与安全边界 | 部分完成 | 环境事实与 UI 展示已完成；同一任务的 Docker/本机并排实跑未执行。 |
| 三份样例（新建 MD、已有 DOCX、PDF 导出）有不支持清单 | 部分完成 | Markdown 样例与不支持清单已完成并有测试；DOCX/PDF 样例属于 M2 文档底座，尚未开始。 |
| 远程事件/意图 schema 有文档与风险映射；无新增网络监听 | 完成 | 契约、策略、测试齐全；仓库没有新增监听端口。 |
| 文案词表落地；宣传页/guide/提示词首批清理 | 部分完成 | 词表与首批提示词/前端清理已完成；宣传页与 `/guide` 复核、CI 检查在后续阶段。 |

---

## 6. 最终测试记录

以本报告提交前的最后一次全量运行为准（命令：`NOVA_TEST_FAST=1 python -m pytest -q --disable-warnings`）：

```text
1300 passed, 12 skipped, 1 warning in 272.87s (0:04:32)
```

12 项跳过为环境相关用例（缺少外部工具或依赖）。前端同轮验证：`npx tsc --noEmit` 通过，`npm run build` 成功，`npm run contract:check` 显示契约与类型均为最新。

---

## 7. 已知限制

1. `report` 里的测试计数目前来自步骤输出解析，尚不是统一测试协议；不同栈的统计口径会不同，M3 证据包再固化。
2. 工作区摘要基于文件集合，不包含 Git 未跟踪文件的完整 diff；`dirty` 只表示有未提交改动。
3. 文档 IR 目前只有 Markdown 适配器；DOCX 定点修改仍走论文模块的旧解析器，尚未迁移到 IR。
4. 远程契约的签名测试用 HMAC 代替设备私钥；生产设备密钥（P-256/Ed25519）与中继在 M2/M3 实现。
5. 文案检查目前靠人工与 grep，尚未进入 CI。

---

## 8. 下一步（M2）

1. 文档底座：本地目录、Markdown 主控源、原子写、哈希冲突检测、版本回退、Pandoc/LibreOffice 导出与保真报告。
2. 开发闭环：GitHub draft PR、CI 状态、评审意见与按评论修订。
3. 远程只读薄片：出站连接、一次性绑定、脱敏进度、完成通知、幂等停止、设备撤销。
4. 文案：宣传页与 `/guide` 复核，错误/空状态清理。
