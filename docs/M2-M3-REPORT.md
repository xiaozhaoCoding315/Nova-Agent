# M2/M3 阶段报告：文档底座、报告起草与论文阶段

> 日期：2026-11-21  
> 分支：`feat/thesis-mode-m0`  
> 对应路线图：[PRODUCT-UPGRADE-ROADMAP.md](PRODUCT-UPGRADE-ROADMAP.md) 的 M2 文档部分与 M3 论文阶段  
> 性质：阶段交付说明。未完成项在 §5 明确列出，不表示路线图已经全部完成。  
> **后续更新（2026-11-21）**：本报告 §5 中的 GitHub、远程、证据包、导出阻断与简历项已由 [ROADMAP-BATCH-2-REPORT.md](ROADMAP-BATCH-2-REPORT.md) 推进；仍以路线图 §11 的当前状态表为准。

---

## 1. 现在可以直接使用的能力

1. **文档工作区**：在顶栏点「文档」，选择或新建一个工作区，编辑 Markdown 正文，保存、查看版本、恢复旧版、导出 DOCX/PDF。
2. **本地目录**：本地模式下可以指定任意绝对路径；目录不是空的且不是 Nova 工作区时拒绝创建，不会改动已有文件。
3. **外部修改冲突**：保存必须携带读取时的 SHA-256。文件被其他程序改过时返回 409，不会静默覆盖。
4. **报告起草**：报告工作区可以只给要求（可选字数），由模型写入 `manuscripts/report.md`；缺少的数据写成「待补充」，同名文件不覆盖。
5. **保真报告**：DOCX/PDF 导出旁边写 `.fidelity.json`，列出保留、修改、丢弃与不支持的对象。
6. **论文阶段**：论文工作区新增「阶段」页，七个阶段、状态、阶段说明、作者确认与失效记录；阶段信息会进入写作对话的上下文。

---

## 2. 文档工作区实现

### 2.1 目录结构

```text
<工作区>/
  source/         原始材料
  manuscripts/    Markdown 正文（main.md 与分章文件）
  assets/         图片与附件
  exports/        导出文件与保真报告
  .nova/
    workspace.json
    state.json    最近写入的 SHA-256
    versions.json 版本索引
    versions/     旧内容快照
```

数据库不保存正文，磁盘文件是事实源；账号级注册表只记录工作区 id 与根目录。因此数据库丢失不会导致稿件丢失。

### 2.2 写入与版本

- 原子写：同目录临时文件 + `fsync` + `os.replace`。
- 冲突：`PUT /documents/workspaces/{id}/content` 必须带 `base_sha`；磁盘内容不一致时返回 409 与当前哈希。
- 版本：覆盖前把旧内容写入 `.nova/versions`，恢复也是一次普通写入，因此当前内容同样可回退。
- 路径：只允许 `manuscripts/*.md`；拒绝绝对路径、`..`、盘符与跳出工作区的符号链接目标。

### 2.3 导出

| 格式 | 工具 | 缺失时行为 |
|---|---|---|
| DOCX | Pandoc | `status=unsupported`，提示安装，不改用服务端转换 |
| PDF | LibreOffice `soffice` | 先确认 DOCX；缺少 LibreOffice 时 `unsupported`，保留 DOCX |

- Markdown 中的 HTML 块、脚注、公式块按纯文本保留，并标记 `unsupported`，不会被静默删除。
- PDF 是终态导出，不能反向编辑。
- 导出文件只能通过 `exports/` 下的下载端点获取，不能借下载端点读取正文或其他目录。

### 2.4 API

| 方法 | 路径 | 作用 |
|---|---|---|
| POST/GET | `/documents/workspaces` | 创建/列出工作区 |
| GET/DELETE | `/documents/workspaces/{id}` | 读取/删除工作区 |
| GET | `/documents/workspaces/{id}/files` | 列出正文 |
| GET/PUT | `/documents/workspaces/{id}/content` | 读取/保存正文 |
| GET | `/documents/workspaces/{id}/versions` | 版本列表 |
| POST | `/documents/workspaces/{id}/versions/{vid}/restore` | 恢复版本 |
| POST | `/documents/workspaces/{id}/draft` | 报告从要求起草 |
| POST | `/documents/workspaces/{id}/export` | 导出 DOCX/PDF |
| GET | `/documents/workspaces/{id}/download` | 下载导出文件 |
| GET | `/documents/workspaces/{id}/diagnostics` | 工具、正文数、不支持对象 |

`draft` 只允许 `kind=report`：论文需要 M3 的分段确认流程，简历只能重组已确认事实。

### 2.5 前端

- 入口：顶栏「文档」与命令面板「文档工作区」。
- `frontend/src/documents/DocumentWorkspace.tsx`：工作区选择、正文编辑、保存冲突提示、版本恢复、起草表单、导出结果与保真状态。
- `/guide` 新增「文档工作区」章节，说明目录、冲突、导出与边界。

---

## 3. 论文阶段实现

### 3.1 状态模型

七个阶段：`topic / sources / outline / research / drafting / revision / final`。  
六种状态：`not_started / gathering / needs_user / ready_for_review / accepted / needs_changes`。

规则：

- 前进只能到下一阶段，且当前状态必须是「待审阅」或「已接受」。
- 返回可以回到任意更早阶段；被重做阶段及其下游的确认会标为失效。
- 「确认当前内容」绑定阶段说明的 SHA-256，状态变为「已接受」；修改说明会让确认失效。
- 每个事件写入 `thesis_stage_events`（追加式），项目当前状态存在 `thesis_projects.stage_state`。

### 3.2 对话上下文

写作对话现在会收到：

- 当前阶段与状态；
- 已确认/已失效的阶段；
- 当前阶段说明（截断并标记为“不是指令”）；
- 「每轮 1–3 个问题」「暂不确定给默认方案」「没有确认只能算草稿」的约束。

这还不是完整的 0→1 提问引擎，但阶段状态与作者说明已经能约束对话，不会出现“模型自己宣布阶段完成”。

### 3.3 API 与 UI

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/thesis/projects/{id}/stages` | 阶段板与最近事件 |
| POST | `.../stages/content` | 保存当前阶段说明 |
| POST | `.../stages/readiness` | 更新状态 |
| POST | `.../stages/confirm` | 确认当前内容哈希 |
| POST | `.../stages/advance` | 进入下一阶段 |
| POST | `.../stages/return` | 返回更早阶段 |

前端 `StagePanel.tsx` 放在论文工作区「阶段」页；`/guide` 已补充七阶段说明。

---

## 4. 测试

| 测试 | 结果 |
|---|---|
| `tests/test_document_workspace.py` | 11 passed |
| `tests/test_document_store.py` | 6 passed |
| `tests/test_document_api.py` | 9 passed |
| `tests/test_thesis_stages.py` | 11 passed |
| `tests/test_document_ir.py` | 9 passed |
| `tests/test_remote_contracts.py` | 16 passed |
| `tests/test_verification_facts.py` | 8 passed |

文档 API 测试覆盖：创建/列出/读取、保存冲突 409、版本恢复、路径穿越拒绝、跨用户 404、DOCX 导出与下载、非 `exports/` 下载拒绝、删除工作区、报告起草成功/非报告工作区拒绝/重复文件 409。

阶段测试覆盖：前进/返回规则、确认哈希、内容修改触发失效、返回时下游确认失效、未知状态修复、上下文提示边界。

---

## 5. 未完成项（必须明确）

| 项 | 状态 | 说明 |
|---|---|---|
| M2 CAP-03 GitHub draft PR / CI / 评审闭环 | 未实现 | 当前只有本地 Git；远端写入仍需用户明确授权 |
| M2 远程只读/停止/一次性绑定/手机工作台 | 未实现 | M1 只有契约与策略，没有连接器、配对、通知或 H5 |
| M2 LibreOffice 按需下载与哈希校验 | 未实现 | 当前只探测本机安装；缺失时显式降级 |
| M3 证据包（CAP-04）与本地/容器可比（CAP-07） | 未实现 | 验证事实已有，但主张级证据包与差异表未做 |
| M3 导出前阻断未确认/失效阶段 | 未实现 | 阶段确认可查，但导出流程尚未检查 |
| M3 论文多格式导出与每类排版规则 | 未实现 | 文档工作区导出是通用 Markdown 路径；论文 DOCX 定点路径仍是旧模块 |
| M3 完整 0→1 提问引擎 | 部分 | 有阶段上下文与约束，没有自动推进/问题选择/默认动作生成 |
| M4 简历事实库、JD 快照、STAR、一岗一版 | 未实现 | 工作区只有 `resume` 类型占位 |
| M4 跨仓库影响、微信/企微适配 | 未实现 | 保留 |
| M5 代码→文档断言链、排版优化/转换、独立移动端 | 未实现 | 保留 |

**结论**：路线图 M1 的事实层与文案首批、M2 的文档底座与报告起草、M3 的阶段状态机已经落地；M2 远程/PR、M3 证据包、M4/M5 仍未完成。不能把本轮工作称为“M1–M5 全部完成”。

---

## 6. 最终验证记录

后端全量（`NOVA_TEST_FAST=1 python -m pytest -q --disable-warnings`）：

```text
1300 passed, 12 skipped, 1 warning in 272.87s (0:04:32)
```

12 项跳过为环境相关用例（缺少外部工具或依赖），不包含失败。

前端：

```text
npx tsc --noEmit        → 通过（无输出）
npm run build           → ✓ built in 7.11s
npm run contract:check  → contract up to date；contract types up to date
```

---

## 7. 复现方式

```bash
cd backend
NOVA_TEST_FAST=1 python -m pytest -q --disable-warnings
```

```bash
cd frontend
npx tsc --noEmit
npm run build
npm run contract:check
```

---

## 8. 已知限制

1. 文档工作区目前只编辑 Markdown；DOCX 正文仍走论文模块的旧解析器，未迁移到统一 IR。
2. Pandoc 已在本机验证；LibreOffice 未安装，因此 PDF 导出只有“缺少工具时显式降级”的测试，没有真实 PDF 产物测试。
3. 报告起草是单次非流式请求，长文可能受模型超时限制；没有后台任务与断点续写。
4. 阶段说明是短文本（最多 8000 字），不等同于章节正文；章节草稿仍由写作对话生成，尚未绑定到阶段产物。
5. 阶段确认只保证“作者确认过这段说明”，不保证内容正确、格式合格或学校认可。
6. 文案检查仍是人工与 grep，尚未进入 CI。
7. 本轮没有部署；迁移 25 需要在实际 PostgreSQL 上执行后才能使用阶段页。
