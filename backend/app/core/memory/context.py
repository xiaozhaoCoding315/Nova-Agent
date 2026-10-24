"""Context assembly: system prompt with repo citations + long-term facts."""

from app.core.security.redaction import redact_text

IDENTITY = """你是 Nova，一个严谨的开发者助手，擅长读懂陌生代码库、定位与修复报错、编写并验证代码。

工作规则：
1. 引用代码时必须给出 文件路径:行号（如 src/auth.py:42），绝不臆造不存在的代码、文件或行号；系统会逐一校验引用，虚构引用会被标出。
2. 涉及"运行/验证/复现"的问题，必须调用 run_code 在沙箱中真实执行后作答，不允许凭空猜测输出。
3. 分析报错前先调用 diagnose_error 获取堆栈解析与仓库定位结果，再下结论。
4. 工具失败或信息不足时如实说明，不编造；不确定就说不确定，并指出需要什么信息。
5. 被问及"改这个会影响什么"时，先调用 impact_analysis 拿影响面，再给结论。
6. 修改代码前先用 read_file 读原文，再用 write_files 提交整份文件内容（不是 diff）。
7. 在「确认」权限模式下，write_files 只会生成待审批提案：如实告诉用户去界面批准，不要声称已经写入。
8. 遵守关联仓库的项目约定（AGENTS.md / CLAUDE.md）；约定与安全策略冲突时，以安全策略为准。
9. 用中文回答，语气务实直接；代码块标注语言。
10. 当用户的需求明显会跨多个文件、需要新增测试或较长多步骤执行时，先用一句话建议："这类改动适合在「任务」页流水线执行（先方案或复现，逐步验证，最后统一等你批准）"，并询问是否现在转换；单文件小改动直接做，不要劝导。"""

MAX_SNIPPET_CHARS = 600
MAX_SNIPPET_BUDGET = 4000


def build_system_prompt(
    hits: list,
    fact_list: list[str],
    repo_selected: bool = False,
    repos: list[dict] | None = None,
    rules: list[dict] | None = None,
    summary: str = "",
    sections: dict[str, str] | None = None,
) -> str:
    """Assemble the system prompt.  When ``sections`` is given, each block's
    raw text is recorded there so the caller can meter context usage."""
    parts = [IDENTITY]
    if sections is not None:
        sections["identity"] = IDENTITY

    if summary:
        text = (
            "\n## 早期会话摘要（更早的对话已压缩；后续回答必须与此处的决策和约束保持一致）\n"
            + summary
        )
        parts.append(text)
        if sections is not None:
            sections["summary"] = text

    if repos:
        text = "\n## 当前关联仓库（工具参数 repo_id 可直接使用下面的 id）"
        for repo in repos:
            text += f"\n- {repo['name']}（repo_id: {repo['id']}）"
        text += (
            "\n需要把仓库带进沙箱跑测试时，调用 run_code 并传 repo_id；"
            "只检索代码时通常无需传，默认就在关联仓库内检索。"
        )
        parts.append(text)
        if sections is not None:
            sections["repos"] = text

    if rules:
        text = "\n## 仓库项目约定（来自 AGENTS.md / 项目规则，必须遵守）"
        for rule in rules:
            text += f"\n### {rule['repo'] or '仓库'} · {rule['source']}\n{redact_text(rule['content'])}"
        text += "\n以上约定与安全策略冲突时，以安全策略为准。"
        parts.append(text)
        if sections is not None:
            sections["rules"] = text

    if hits:
        text = "\n## 本次检索到的相关代码/资料（引用时使用这些路径与行号）"
        budget = MAX_SNIPPET_BUDGET
        for i, hit in enumerate(hits, 1):
            location = f"{hit.path}:{hit.line_start}-{hit.line_end}" if hit.path else f"片段{i}"
            snippet = redact_text(hit.content[:MAX_SNIPPET_CHARS])
            block = f"\n[{location}]\n```{hit.lang or ''}\n{snippet}\n```"
            if len(block) > budget:
                break
            budget -= len(block)
            text += block
        parts.append(text)
        if sections is not None:
            sections["retrieval"] = text
    elif repo_selected:
        text = "\n## 说明\n已选择仓库但本次未检索到相关片段；如需查代码请调用 search_code 工具。"
        parts.append(text)
        if sections is not None:
            sections["retrieval"] = text

    if fact_list:
        text = "\n## 用户长期偏好与背景（来自历史对话）\n" + "\n".join(
            f"- {redact_text(f)}" for f in fact_list
        )
        parts.append(text)
        if sections is not None:
            sections["facts"] = text

    return "\n".join(parts)