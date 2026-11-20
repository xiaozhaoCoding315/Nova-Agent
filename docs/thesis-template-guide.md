# 论文模板作者指南

模板把一所学校/学院的**可执行格式要求**编码成 JSON，供 Nova 的确定性规则引擎使用。模板只描述规则，不搬运学校格式文件原文，也不承诺覆盖学校全部要求。

## 目录结构

```text
thesis-templates/
└─ <template-id>/
   ├─ template.json   # 必需
   └─ SOURCE.md       # 必需：来源、日期、适用范围、版权说明
```

- `<template-id>` 必须匹配 `^[a-z0-9][a-z0-9-]{2,79}$`，例如 `demo-university-2026`；
- 三个内置模板以 `nova-demo-` 开头，`is_sample: true`，是虚构演示校，不对应任何真实学校；
- 运行时也可以通过 `NOVA_THESIS_TEMPLATES` 指向外部模板目录。

## 最小示例

```json
{
  "id": "example-university-2026",
  "name": "示例大学 2026 届本科论文",
  "description": "仅用于演示：A4，上下 2.5cm，左 3cm，右 2.5cm。",
  "source": "示例大学教务处《本科毕业论文格式要求（2026）》",
  "source_url": "https://example.edu.cn/notice/2026-thesis-format",
  "version": "2026.1",
  "degree": "undergraduate",
  "is_sample": false,
  "page": {
    "size": "A4",
    "width_cm": 21.0,
    "height_cm": 29.7,
    "tolerance_cm": 0.15
  },
  "margins": {
    "top_cm": 2.5,
    "bottom_cm": 2.5,
    "left_cm": 3.0,
    "right_cm": 2.5,
    "tolerance_cm": 0.2
  },
  "headings": {
    "max_level": 3,
    "allow_skip": false
  },
  "page_number": {
    "required": true,
    "position": "footer"
  },
  "required_sections": [
    { "key": "abstract", "label": "中文摘要", "patterns": ["摘要"] },
    { "key": "references", "label": "参考文献", "patterns": ["参考文献", "References"] },
    { "key": "acknowledgements", "label": "致谢", "patterns": ["致谢"] }
  ],
  "references": {
    "enabled": true,
    "style": "GB/T 7714-2015",
    "min_entries": 5,
    "numbering_required": true,
    "section_patterns": ["参考文献", "References"]
  },
  "disclosure": {
    "title": "AI 工具使用声明",
    "intro": "本人在本论文完成过程中使用 AI 工具的情况如下。",
    "fields": ["工具名称与版本", "使用环节", "用途说明", "生成内容与修改情况"]
  }
}
```

完整字段约束见 [`thesis-templates/schema.json`](../thesis-templates/schema.json)。

## 字段说明

| 字段 | 必需 | 作用 |
|---|---|---|
| `id` | 是 | 模板唯一标识；改名会影响已有项目的模板关联 |
| `name` / `description` | 是 | 选择器与报告中显示 |
| `source` | 是 | 规则依据（文件名称/通知/标准）；没有来源的模板不合并 |
| `source_url` | 否 | 公开链接；不要放需要登录才能访问的内部地址 |
| `version` | 是 | `YYYY.N`，规则变化时递增 |
| `degree` | 是 | `undergraduate` / `master` / `doctor` |
| `is_sample` | 否 | 虚构演示模板必须为 `true` |
| `page` | 是 | 页面大小与宽高（cm）、容差 |
| `margins` | 是 | 上/下/左/右页边距（cm）、容差 |
| `headings.max_level` | 是 | 允许的最深标题级别；超出记警告 |
| `headings.allow_skip` | 是 | 是否允许跳级（如一级直接到三级） |
| `page_number.required` | 否 | 是否要求页码；需要页眉/页脚中存在 PAGE 域 |
| `page_number.position` | 否 | `header` / `footer` / `any` |
| `required_sections` | 否 | 必需章节；`patterns` 与标题文本匹配（不区分大小写） |
| `references.enabled` | 否 | 是否启用引用核对；默认 `true`，设为 `false` 可关闭 |
| `references.style` | 否 | 引用体例说明（当前用于展示，不做格式解析） |
| `references.min_entries` | 否 | 参考文献最少条数 |
| `references.numbering_required` | 否 | 是否要求条目带 `[n]` 编号 |
| `references.section_patterns` | 否 | 参考文献标题的匹配文本 |
| `disclosure` | 否 | 声明标题、说明与字段；缺省使用内置文案 |

## 当前规则覆盖

| 规则 ID | 检查内容 | 自动修复 |
|---|---|---|
| `format.page_size` | 页面宽高是否在容差内 | 是（`set_page_size`） |
| `format.margins` | 四个页边距是否在容差内 | 是（`set_margins`） |
| `format.page_number` | 页眉/页脚是否存在 PAGE 域 | 否，需人工处理 |
| `structure.heading_hierarchy` | 首个标题级别、跳级、超过 `max_level` | 否 |
| `structure.heading_style` | 形如「1.2 标题」却按正文排版的段落 | 是（`set_heading_style`） |
| `structure.required_sections` | 必需章节是否缺失 | 否 |
| `citation.*` / `references.*` | 引用对应、缺条目、重复、编号、顺序、条数 | 否 |

**不检查**：字体、字号、行距、段前段后、图表题注、页眉文字、目录页码、打印分页。这些需要页面渲染级校验或更多结构证据，当前版本会明确标注「需人工确认」。

## 校验与测试

在仓库根目录运行：

```bash
cd backend
python -m scripts.validate_thesis_templates
```

校验内容包括：JSON Schema、模板 ID 唯一、`SOURCE.md` 存在。CI 会在每个 PR 运行同一命令。

如果你提供脱敏合成样例，可同时提交：

```text
thesis-templates/<template-id>/
├─ sample.docx       # 合成文本，不含真实学生论文或个人信息
└─ expected.json     # 期望命中的规则与数量（可选）
```

## 贡献要求

1. **来源可查**：`SOURCE.md` 写明学校/学院、文件名称、发布日期、适用范围、获取方式；
2. **只编码规则**：不要复制学校格式文件原文、校徽、模板文件；只写数值与规则；
3. **保守容差**：默认容差 0.15–0.2cm；过严会产生大量误报；
4. **不做推断**：学校没写的要求不要加；不确定的项标记为提示或留给人工；
5. **合成样例**：如附样例，必须完全合成、脱敏；
6. **通过 CI**：模板校验 + 后端测试 + 前端构建；
7. **许可**：贡献以 Apache-2.0 发布；收到版权投诉会先下架模板。

## 常见问题

**一个学院一个模板，还是学校一个模板？**
按实际差异建。差异只在个别章节时，优先在模板里用 `required_sections` 表达，不要复制整份模板。

**页码位置怎么判断？**
当前只检查页眉/页脚中是否存在 PAGE 域，并区分 header/footer；不判断页码格式（罗马数字、起始页）。

**能否用模板检查字体？**
当前不能。字体/字号需要 run 级样式与页面渲染结合，容易误报；后续版本评估。

**模板会随学校通知更新吗？**
维护者会按来源更新并递增 `version`；旧项目仍保留原模板版本，重跑检查不会悄悄换规则。
