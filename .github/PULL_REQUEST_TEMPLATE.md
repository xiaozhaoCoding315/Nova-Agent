## 变更内容

<!-- 一句话说明这次改了什么，以及为什么改。 -->

## 关联 Issue

<!-- 例如：Closes #123 -->

## 验证

- [ ] 后端：`cd backend && python -m pytest tests -q`
- [ ] 前端：`cd frontend && npm run build`
- [ ] 如涉及 API：已运行 `cd backend && python -m scripts.export_openapi`，并更新 `contracts/openapi.json`
- [ ] 如涉及论文解析/规则：用 `thesis-samples/` 的样例验证过，且原文件 hash 不变
- [ ] 如涉及模板：已运行 `cd backend && python -m scripts.validate_thesis_templates`

## 学术诚信自查（论文模式相关改动必填）

- [ ] 不包含代写、降重、降低 AIGC 检测率、伪造引用、论文买卖或绕过学校审查的功能
- [ ] 不包含真实学生论文、个人信息或未公开的学校内部文件
- [ ] 规则模板标注来源与适用范围；不确定的规则给出「需人工确认」而不是假装确定

## 备注

<!-- 截图、风险点、未覆盖的测试等。 -->
