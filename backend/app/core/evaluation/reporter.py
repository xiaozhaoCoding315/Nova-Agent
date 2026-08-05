"""Evaluation report generation: aggregate results + Markdown report."""
import asyncio
from datetime import datetime
from app.core.evaluation.dataset import list_eval_results


async def generate_report(run_name: str) -> str:
    """Generate a Markdown evaluation report for a run."""
    results = await list_eval_results(run_name)
    if not results:
        return "No results found for this run."

    lines = [
        f"# NovaTech Agent 评测报告",
        f"",
        f"**运行名称**: {run_name}",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**查询数量**: {len(results)}",
        f"",
        f"## 总体指标",
        f"",
    ]

    # Aggregate metrics
    retrieval_results = [r for r in results if r.get("metrics")]
    ragas_results = [r for r in results if r.get("ragas_scores")]

    if retrieval_results:
        avg_metrics = {}
        for r in retrieval_results:
            for k, v in r["metrics"].items():
                avg_metrics[k] = avg_metrics.get(k, 0) + v
        for k in avg_metrics:
            avg_metrics[k] /= len(retrieval_results)

        lines.append("| 指标 | 平均值 |")
        lines.append("|------|--------|")
        for k, v in sorted(avg_metrics.items()):
            lines.append(f"| {k} | {v:.4f} |")
        lines.append("")

    if ragas_results:
        avg_ragas = {}
        for r in ragas_results:
            for k, v in r["ragas_scores"].items():
                if isinstance(v, (int, float)):
                    avg_ragas[k] = avg_ragas.get(k, 0) + v
        for k in avg_ragas:
            avg_ragas[k] /= len(ragas_results)

        lines.append("## RAGAS 生成质量")
        lines.append("")
        lines.append("| 维度 | 平均分 |")
        lines.append("|------|--------|")
        for k, v in sorted(avg_ragas.items()):
            lines.append(f"| {k} | {v:.4f} |")
        lines.append("")

    # Per-query details
    lines.append("## 各查询详情")
    lines.append("")
    for r in results:
        lines.append(f"### {r['query_text']}")
        lines.append(f"- 类型: {r['eval_type']}")
        lines.append(f"- 耗时: {r['duration_ms']:.0f}ms")
        if r.get("metrics"):
            lines.append(f"- 检索指标: {r['metrics']}")
        if r.get("ragas_scores"):
            lines.append(f"- RAGAS: {r['ragas_scores']}")
        lines.append("")

    return "\n".join(lines)
