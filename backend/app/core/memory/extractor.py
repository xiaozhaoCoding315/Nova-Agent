"""Extract technical facts from conversation using LLM."""
from app.core.llm.factory import get_llm

EXTRACT_PROMPT = """分析以下对话,提取用户的技术偏好、学习记录、代码习惯等关键事实。
每行输出一条事实,格式为: [类别] 事实内容
类别可选: preference(偏好), learning(学习记录), style(代码风格), domain(擅长领域)
如果没有有价值的信息,输出为空。

对话:
{dialog}
"""


async def extract_facts(messages: list[dict]) -> list[dict]:
    """Extract structured facts from a conversation. Returns [{fact, category}]."""
    dialog = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in messages)
    if len(dialog) < 50:
        return []

    prompt = EXTRACT_PROMPT.format(dialog=dialog)
    full_response = ""
    try:
        llm = get_llm()
        async for token in llm.astream([{"role": "user", "content": prompt}]):
            full_response += token
    except Exception:
        return []

    facts = []
    for line in full_response.strip().split("\n"):
        line = line.strip()
        if not line or "[" not in line or "]" not in line:
            continue
        try:
            category = line.split("[")[1].split("]")[0].strip().lower()
            fact = line.split("]")[1].strip()
            if fact and len(fact) > 5:
                facts.append({"fact": fact, "category": category})
        except (IndexError, ValueError):
            continue
    return facts[:10]  # max 10 facts
