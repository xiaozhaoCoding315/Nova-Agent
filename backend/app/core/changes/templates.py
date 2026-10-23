"""Task templates for the change workflow.

A template is a prompt hint plus the policy the server enforces.  Templates
keep the planner and executor aligned without hard-coding one workflow.
"""

TEMPLATES: dict[str, dict] = {
    "feature": {
        "label": "功能",
        "requires_tests": True,
        "planner_hint": "新增或扩展用户可见能力；必须包含测试任务或带测试的实现任务。",
        "executor_hint": "实现功能，保持既有风格；新增行为要有对应测试；不要顺手重构无关代码。",
    },
    "bugfix": {
        "label": "修复",
        "requires_tests": True,
        "planner_hint": "先复现、再修复；验收必须包含能稳定复现/验证的命令。",
        "executor_hint": "最小修复；先补一个修复前会失败的测试；不要删除或跳过已有测试。",
    },
    "refactor": {
        "label": "重构",
        "requires_tests": True,
        "planner_hint": "行为不变，以现有测试为安全网；验收必须是全量测试通过。",
        "executor_hint": "保持外部行为不变；优先小步改动；不要改变公共接口语义。",
    },
    "test": {
        "label": "测试",
        "requires_tests": True,
        "planner_hint": "只补测试与测试基础设施，不改变生产行为。",
        "executor_hint": "新增或加强测试；不得删除/跳过已有测试；不要修改生产逻辑。",
    },
    "docs": {
        "label": "文档",
        "requires_tests": False,
        "planner_hint": "只改文档与注释；验收可以是文档存在性或链接检查。",
        "executor_hint": "只改 README / docs / docstring；不要改业务逻辑。",
    },
    "contract": {
        "label": "契约",
        "requires_tests": True,
        "planner_hint": "修改接口契约时必须同步前端类型、后端校验与测试。",
        "executor_hint": "保持契约与实现一致；同时更新调用方与测试。",
    },
}


def template_for(kind: str) -> dict:
    return TEMPLATES.get(kind, TEMPLATES["feature"])


def kind_labels() -> dict[str, str]:
    return {kind: meta["label"] for kind, meta in TEMPLATES.items()}
