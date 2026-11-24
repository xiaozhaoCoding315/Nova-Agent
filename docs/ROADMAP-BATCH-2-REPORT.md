# M2–M4 批次报告：PR 闭环、远程工作台、证据包与简历

> 日期：2026-11-21  
> 分支：`feat/thesis-mode-m0`  
> 对应路线图：[PRODUCT-UPGRADE-ROADMAP.md](PRODUCT-UPGRADE-ROADMAP.md) §11  
> 性质：批次交付说明。§6 明确列出仍未完成的部分，不表示路线图已全部完成。

---

## 1. 现在可以直接使用的能力

1. **文档格式转换**：在文档工作区里选择源文件与目标格式（DOCX/PDF），按 `report / thesis / resume` 三类 profile 生成，返回保真报告；有损转换默认拒绝，需要用户显式允许。
2. **论文导出前检查**：导出定稿包前读取阶段 readiness；存在未确认或已失效阶段时先列出警告，用户明确确认后才带 `allow_unconfirmed=true` 继续导出。
3. **证据包**：从一次验证结果生成主张级证据包，包含结论、工件 SHA-256、环境、未证明事项；可以重新核对工件是否被篡改，也可以比较两份环境清单（未记录不等于一致）。
4. **远程工作台**：桌面端生成一次性配对链接与二维码，手机打开 `/m` 确认 SAS 后绑定；手机可看脱敏进度、收完成通知、停止任务、审批中低风险操作；高风险操作只能在电脑上确认。
5. **GitHub 交付**：连接 GitHub 账号后查看远端分支与 PR，用户勾选明确授权后创建 **draft PR**，查看 CI、评审与评论；没有 merge 入口。
6. **简历工作台**：维护 Profile 与事实库（数字无依据自动降级为「待确认」，不能进入岗位版本），按学生/技术岗回答 STAR 问题，保存 JD 快照，一岗一版，导出 Markdown/DOCX/PDF。

---

## 2. 各能力的实现与边界

### 2.1 文档转换与论文导出阻断

| 项 | 实现 |
|---|---|
| 转换核心 | `backend/app/core/documents/convert.py`：Pandoc DOCX、LibreOffice PDF，profile 决定排版参数 |
| 转换 API | `POST /documents/workspaces/{id}/convert`：`source_path`、`target_format`、`profile`、`overwrite`、`allow_lossy` |
| 保真报告 | 每次转换写 `.fidelity.json`；不支持的对象列入 `unsupported`，不静默丢弃 |
| 前端 | `frontend/src/documents/DocumentWorkspace.tsx`「格式转换」区；显示状态、保真摘要、未支持项与下载入口 |
| 论文导出检查 | `GET /thesis/projects/{id}/export-readiness`；`POST /thesis/projects/{id}/export?allow_unconfirmed=true` |
| 前端确认 | `frontend/src/stores/thesis.ts` 在导出定稿包前列出前 6 条警告，用户取消则不导出 |

边界：PDF 是终态，不能反向编辑；缺少 Pandoc/LibreOffice 时返回 `unsupported/409`，不会改用远端转换服务。

### 2.2 证据包与环境可比

| 项 | 实现 |
|---|---|
| 生成 | `POST /evidence/repos/{repo_id}/packs`，从验证结果提取主张事实 |
| 读取 | `GET /evidence/packs`、`GET /evidence/packs/{pack_id}` |
| 核对 | `POST /evidence/packs/{pack_id}/verify`：重新计算工件 SHA-256，报告篡改与缺失 |
| 环境比较 | `POST /evidence/compare`：逐项给出 `same / different / unknown`，`unknown` 绝不判为一致 |
| 前端 | `frontend/src/evidence/EvidenceWorkspace.tsx`：主张状态、未证明项、工件哈希、环境对比 |

边界：只陈述可复核的事实；`unproven` 与 `needs_confirmation` 保留，不因为导出或展示而消失。

### 2.3 远程工作台

| 层 | 实现 |
|---|---|
| 配对 | 一次性 token（库中只存 SHA-256）、默认 5 分钟 TTL、短认证串 SAS、单次使用、claim 限流 |
| 设备 | P-256 密钥对；私钥不可导出地存于手机 IndexedDB；`pending / active / revoked` 三态；桌面可撤销 |
| 指令 | `status.get / run.stop / approval.list / approval.decide`；ECDSA 签名 + 规范化 JSON + nonce 防重放 + 45 秒过期 |
| 进度 | 只回传任务状态、阶段、百分比与脱敏摘要；token/tool_output 不原文外发 |
| 停止 | 复用桌面同一条取消路径；重复调用返回 `idempotent=true` |
| 通知 | 任务结束写脱敏通知；同一任务同一状态去重 |
| 审批 | 动作哈希绑定、300 秒过期、仅中低风险可远程；`local_exec / local_write` 等高风险一律要求本机 |
| 审计 | 本地审计含决定与风险级别；中继审计只有路由元数据 |
| 手机端 | `/m` 页面：配对、SAS、进度、审批、通知、停止、本机解除绑定 |
| 桌面端 | `frontend/src/remote/RemotePanel.tsx`：生成二维码/链接、确认 SAS、设备管理、通知与审计 |

**传输边界（必须明确）**：本轮实现的是**同源 HTTPS 直连模式**，不新开公网端口，手机访问桌面所在的同一服务地址。设置项 `remote_relay_url` 已预留，但**出站 WSS 中继连接器尚未实现**；配置该值目前只会把 `/remote/config` 的 `mode` 显示为 `relay`，不会真的建立中继连接。微信/企微适配、系统级推送也未实现，通知靠手机页面轮询。

### 2.4 GitHub draft PR / CI / 评审

| 项 | 实现 |
|---|---|
| 连接 | `POST /github/connect`：校验 token 后加密存储；状态接口从不回传 token |
| 远端 | `GET /github/repos/{id}/remote`：解析 `origin` 与当前分支；只接受 github.com 的 HTTPS/SSH 地址 |
| 创建 PR | `POST /github/repos/{id}/prs`：必须带授权短语 `create-draft-pr`，分支必须已推送，只创建 draft |
| 状态 | `GET /github/repos/{id}/prs/{number}`：check-runs + commit statuses + reviews + review/issue comments |
| 前端 | `frontend/src/github/GitHubPanel.tsx`：连接、授权勾选、PR 列表、CI 徽标、评审意见、复制意见 |

边界：没有 merge、auto-merge、release 或跨仓库写入代码；授权按请求生效，不保存“永久同意”。

### 2.5 简历 MVP

| 项 | 实现 |
|---|---|
| 事实库 | `backend/app/core/resume/models.py`：`self_reported / evidence_linked / needs_confirmation / excluded`；带数字但无依据的事实自动降级为待确认 |
| Profile | 姓名、一句话定位、联系方式；每用户独立 JSON 存储 |
| STAR | 学生版与技术岗版两套问题，`GET /resume/questions` |
| 岗位版本 | JD 原文快照、选定事实、模板（classic/modern/compact）、备注；只允许可纳入的事实 |
| 导出 | Markdown 直出；DOCX/PDF 复用文档转换，缺少工具时返回 409 与诊断 |
| 前端 | `frontend/src/resume/ResumeWorkspace.tsx` |

边界：只重组用户已经陈述的内容，不编造经历、数字或证书；没有「降重」或绕过筛选系统的功能。

---

## 3. 安全与产品红线

- 论文模式仍是「全流程辅助 + 分段草稿 + 作者确认」；没有无人参与的整篇学位论文代写，没有降重、AIGC 规避、伪造引用或数据。
- 普通文档可以整篇起草，但保持「AI 草稿」标识；简历不虚构经历与指标。
- 远程控制不提供第二条执行路径；高风险操作只在电脑确认；不暴露公网端口。
- GitHub 只建 draft PR，必须每次显式授权；没有自动合并或自动发布。
- 所有外部副作用都需要用户明确操作；本轮未提交、未推送、未部署。

---

## 4. 新增接口一览

```text
POST   /api/v1/documents/workspaces/{id}/convert

POST   /api/v1/evidence/repos/{repo_id}/packs
GET    /api/v1/evidence/packs
GET    /api/v1/evidence/packs/{pack_id}
POST   /api/v1/evidence/packs/{pack_id}/verify
POST   /api/v1/evidence/compare

GET    /api/v1/remote/config
POST   /api/v1/remote/pairings
GET    /api/v1/remote/pairings/{pair_id}
POST   /api/v1/remote/pair/claim
POST   /api/v1/remote/pairings/{pair_id}/confirm
POST   /api/v1/remote/pairings/{pair_id}/reject
POST   /api/v1/remote/commands
GET    /api/v1/remote/devices
POST   /api/v1/remote/devices/{device_id}/revoke
GET    /api/v1/remote/notifications
POST   /api/v1/remote/notifications/read
GET    /api/v1/remote/audit

GET    /api/v1/github/status
POST   /api/v1/github/connect
POST   /api/v1/github/disconnect
GET    /api/v1/github/repos/{repo_id}/remote
GET    /api/v1/github/repos/{repo_id}/prs
POST   /api/v1/github/repos/{repo_id}/prs
GET    /api/v1/github/repos/{repo_id}/prs/{number}

GET    /api/v1/resume/questions
POST   /api/v1/resume/profiles
GET    /api/v1/resume/profiles
GET    /api/v1/resume/profiles/{profile_id}
GET    /api/v1/resume/profiles/{profile_id}/facts
POST   /api/v1/resume/profiles/{profile_id}/facts
PATCH  /api/v1/resume/profiles/{profile_id}/facts/{fact_id}
POST   /api/v1/resume/profiles/{profile_id}/versions
GET    /api/v1/resume/profiles/{profile_id}/versions
GET    /api/v1/resume/versions/{version_id}
GET    /api/v1/resume/versions/{version_id}/markdown
POST   /api/v1/resume/versions/{version_id}/export
```

数据库迁移：`backend/app/db/init_db.py` 迁移 26 创建 `user_github_connections` 与 `github_pull_requests`。远程、证据包、简历使用 `settings.user_data_dir` 下的按用户 JSON/JSONL，不依赖数据库迁移。

---

## 5. 验证记录

本轮新增模块聚焦测试（`NOVA_TEST_FAST=1`，8 个文件）：

```text
84 passed in 9.08s
```

覆盖：文档转换与转换 API、证据包生成/核对/环境比较/API、GitHub 授权门与 draft PR、远程配对/签名/重放/撤销/审批/通知、简历事实降级与一岗一版/导出 API。

前端：

```text
npm run build          ✓ built（tsc -b + vite build）
npm run contract:check ✓ contract up to date；contract types up to date
npm run copy:check     ✓ copy check passed
```

OpenAPI 契约已用 `python -m scripts.export_openapi` 重新生成，并同步 `frontend/src/lib/api-schema.d.ts`。

后端全量（`NOVA_TEST_FAST=1 python -m pytest tests -q`）：

```text
1389 passed, 12 skipped, 1 warning in 253.89s (0:04:13)
```

12 项跳过为环境相关用例（缺少外部工具或依赖），无失败。唯一 warning 是测试用 JWT 密钥长度提示，与本次改动无关。Ruff（CI 使用的 0.17.3）对 `app tests scripts evals` 全量检查通过。

---

## 6. 未完成项（必须明确）

| 路线图项 | 状态 | 说明 |
|---|---|---|
| M2 出站 WSS 中继连接器 | 未实现 | 当前只有同源 HTTPS 直连；`remote_relay_url` 只是配置占位 |
| M2 LibreOffice 按需下载与哈希校验 | 未实现 | 只探测本机安装，缺失时显式降级 |
| M4 跨仓库影响 | 未实现 | 现有影响分析只覆盖单仓库依赖图 |
| M4 微信/企微适配 | 未实现 | 不把个人订阅号当控制平面；当前用手机网页工作台 |
| M4 系统推送 / PWA 离线完善 | 未实现 | 手机端靠轮询；无 Service Worker 离线队列 |
| M5 代码→文档断言链 | 未实现 | 证据包已具备工件与主张层，但尚未把代码断言自动写进文档 |
| M5 排版优化/转换 | 未实现 | 本轮只有格式转换与 profile，不等于排版优化 |
| M5 独立移动端评估 | 未实现 | 保留 |

**结论**：M2 的 GitHub 闭环与远程薄片、M3 的证据包/多格式/导出阻断、M4 的简历 MVP 已落地并有测试；中继连接器、跨仓库影响、微信适配、M5 仍未完成。不能把这轮工作称为「路线图全部完成」。

---

## 7. 全量测试补充记录

```text
$ cd backend && NOVA_TEST_FAST=1 python -m pytest tests -q
1389 passed, 12 skipped, 1 warning in 253.89s (0:04:13)
exit code 0
```

本轮没有提交、推送或部署；所有改动仍在 `feat/thesis-mode-m0` 工作区。
