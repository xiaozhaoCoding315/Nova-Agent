# 贡献指南

Nova Agent 采用 [Apache License 2.0](LICENSE)。提交代码即表示你同意以同一许可证发布你的贡献。

## 先读这三件事

1. **论文模式的边界**：我们做的是格式体检、引用核对、AI 使用声明和可复核的报告。不做代写、降重、降低 AIGC 检测率、伪造引用、论文买卖，也不抓取知网/维普/万方的付费全文。
2. **隐私优先**：不要提交真实学生论文、个人信息、导师联系方式或未公开的学校内部文件。样例请脱敏，优先使用 `thesis-samples/` 里的合成文档；任何联网能力都要说明发送了什么、发到哪里。
3. **规则要可解释**：每条格式规则都要说明依据、适用范围和容差；不确定的地方标记「需人工确认」，不要用模型猜测代替确定性检查。

论文模式的上手与模板说明见 [docs/thesis-quickstart.md](docs/thesis-quickstart.md) 与 [docs/thesis-template-guide.md](docs/thesis-template-guide.md)。参与讨论请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)；安全漏洞请走私密渠道 [SECURITY.md](SECURITY.md)。

## 本地开发

```bash
# 后端
cd backend
python -m pip install -r requirements.txt
python -m pytest tests -q

# 前端
cd frontend
npm install
npm run build

# 论文模板校验（改了 thesis-templates 必跑）
cd ../backend
python -m scripts.validate_thesis_templates

# API 契约（改了接口必跑）
python -m scripts.export_openapi
cd ../frontend
npm run contract:generate
```

需要 PostgreSQL / Qdrant 的集成测试会自动跳过；本地完整启动方式见 [README](README.md)。

## 分支与 PR

- 从 `main` 开分支：`feat/...`、`fix/...`、`docs/...`。
- 一个 PR 只做一件事；描述里写清楚验证命令和实际输出。
- 论文模式相关 PR 请勾选 PR 模板里的学术诚信与隐私自查。
- 改 API 时同步更新 `contracts/openapi.json` 和 `frontend/src/lib/api-schema.d.ts`。

## 学校模板

学校模板放在 `thesis-templates/<template-id>/`：

```text
thesis-templates/<template-id>/
├─ template.json   # 规则与页面设置
└─ SOURCE.md       # 来源 URL/文件、日期、适用范围
```

提交时请附：

- 学校、学院、适用学位；
- 公开来源链接或授权说明；
- 规则清单与容差；
- 一份脱敏的合成样例（可选）；
- 运行 `python -m scripts.validate_thesis_templates` 的输出。

字段、规则覆盖与贡献要求见 [docs/thesis-template-guide.md](docs/thesis-template-guide.md)。模板不是「越严越好」：只检查有明确依据的项，避免把正常排版误报成错误。只编码规则，不搬运学校格式文件原文。

## 代码风格

- Python：沿用现有模块结构，类型标注优先，纯函数尽量可单测。
- TypeScript / React：跟随现有 Tailwind token 和组件习惯，不要引入新 UI 框架。
- 用户可见文案用中文，代码标识符用英文。
- 提交信息用 `feat:` / `fix:` / `docs:` / `test:` / `chore:` 前缀。

## 报告问题

使用 [Issue 模板](.github/ISSUE_TEMPLATE/)；安全漏洞请按 [SECURITY.md](SECURITY.md) 私密报告，不要公开贴出利用细节、密钥或真实论文。
