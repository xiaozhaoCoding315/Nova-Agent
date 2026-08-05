"""RAGAS generation evaluation with robust parsing."""
import json, re, structlog
from app.core.llm.factory import get_llm

logger = structlog.get_logger()

EVAL_PROMPT = """你是一个RAG系统评测专家。请严格评估AI回答的质量。

## 问题
{question}

## AI回答
{answer}

## 参考上下文
{context}

## 评分标准
- faithfulness (忠实度): 回答是否完全基于上下文，无编造。0=完全编造，1=完全基于上下文
- answer_relevancy (回答相关性): 回答是否精准匹配问题核心。0=完全离题，1=精准切题
- context_precision (上下文精确率): 上下文中有多少比例与问题真正相关。0=全部无关，1=全部相关
- context_recall (上下文召回率): 上下文是否覆盖回答所需的全部支撑信息。0=完全缺失，1=完整覆盖

## 要求
1. 返回严格JSON格式，不要任何其他文字
2. 每个维度评分0.0-1.0，保留1位小数
3. 直接输出JSON，不要markdown代码块

返回格式：
{{"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0}}
"""

async def evaluate_generation(question: str, answer: str, context: str) -> dict:
    """Evaluate a single QA pair using LLM-as-judge. Returns 4-dimension scores."""
    prompt = EVAL_PROMPT.format(
        question=question[:500] if question else "(空)",
        answer=answer[:1000] if answer else "(空)",
        context=context[:2000] if context else "(空)")
    full_response = ""
    try:
        llm = get_llm()
        async for token in llm.astream([{"role": "user", "content": prompt}]):
            full_response += token
    except Exception as e:
        logger.warning("RAGAS LLM call failed", error=str(e))
        return _zero_scores()
    return _parse_scores(full_response)


def _parse_scores(response: str) -> dict:
    """Parse JSON scores from LLM response with robust fallback."""
    cleaned = response.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned)
    cleaned = re.sub(r'^```\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
    if not match:
        match = re.search(r'\{.+?\}', cleaned, re.DOTALL)
    if match:
        try:
            scores = json.loads(match.group())
            return {k: max(0.0, min(1.0, float(scores.get(k, 0.0))))
                    for k in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    logger.warning("Failed to parse RAGAS scores", response=response[:200])
    return _zero_scores()


def _zero_scores() -> dict:
    return {"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0}
