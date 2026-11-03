"""Command line interface for task-level evals."""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from evals.models import EvalTask
from evals.report import (
    compare_baseline,
    load_baseline,
    render_summary,
    write_baseline,
    write_json,
    write_markdown,
)
from evals.runner import run_suite
from evals.tasks import ALL_TASKS, tasks_for_mode

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="Nova Agent task-level evals",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="列出所有任务")

    run = subparsers.add_parser("run", help="运行任务套件")
    run.add_argument("--mode", choices=("scripted", "live"), required=True)
    run.add_argument("--task", action="append", default=[], metavar="ID")
    run.add_argument("--ci", action="store_true", help="CI 模式（仅 scripted）")
    run.add_argument("--keep", action="store_true", help="保留临时 fixture 目录")
    run.add_argument("--report-dir", help="报告目录")
    run.add_argument("--json", help="JSON 报告路径")
    run.add_argument("--md", help="Markdown 报告路径")
    run.add_argument("--min-pass-rate", type=float, default=1.0)
    run.add_argument("--provider", default="auto")
    run.add_argument("--model")
    run.add_argument("--baseline")
    run.add_argument("--update-baseline")
    return parser


def select_tasks(mode: str, ids: list[str]) -> list[EvalTask]:
    by_id = {task.id: task for task in ALL_TASKS}
    unknown = [task_id for task_id in ids if task_id not in by_id]
    if unknown:
        raise ValueError(f"未知任务：{', '.join(unknown)}")
    mismatched = [
        task_id for task_id in ids if by_id[task_id].mode != mode
    ]
    if mismatched:
        raise ValueError(
            f"任务与模式不匹配（--mode {mode}）：{', '.join(mismatched)}"
        )
    if ids:
        return [by_id[task_id] for task_id in ids]
    return tasks_for_mode(mode)


def _print_tasks() -> None:
    print(f"{'ID':24} {'MODE':9} {'CATEGORY':10} DESCRIPTION")
    for task in ALL_TASKS:
        print(f"{task.id:24} {task.mode:9} {task.category:10} {task.description}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        _print_tasks()
        return 0

    if args.ci and args.mode != "scripted":
        print("--ci 只支持 scripted 模式", file=sys.stderr)
        return 2

    try:
        tasks = select_tasks(args.mode, args.task)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not tasks:
        print(f"没有可运行的 {args.mode} 任务", file=sys.stderr)
        return 2

    report = asyncio.run(run_suite(
        tasks,
        args.mode,
        provider=args.provider,
        model=args.model,
        keep=args.keep,
    ))

    if args.baseline:
        try:
            report.baseline = compare_baseline(report, load_baseline(args.baseline))
        except (OSError, ValueError) as exc:
            print(f"基线读取失败：{exc}", file=sys.stderr)
            return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = Path(args.report_dir) if args.report_dir else DEFAULT_REPORT_DIR
    json_path = Path(args.json) if args.json else report_dir / f"{args.mode}-{stamp}.json"
    md_path = Path(args.md) if args.md else report_dir / f"{args.mode}-{stamp}.md"
    try:
        write_json(report, json_path)
        write_markdown(report, md_path)
    except OSError as exc:
        print(f"报告写入失败：{exc}", file=sys.stderr)
        return 2

    if args.update_baseline:
        try:
            write_baseline(report, Path(args.update_baseline))
        except OSError as exc:
            print(f"基线写入失败：{exc}", file=sys.stderr)
            return 2

    print(render_summary(report))
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")

    runnable = [task for task in report.tasks if task.status != "skipped"]
    if not runnable:
        print("所有任务均已跳过（live provider 未配置）。")
        return 0

    failed = report.summary["pass_rate"] < args.min_pass_rate
    if args.ci and report.baseline:
        failed = (
            failed
            or bool(report.baseline["regressions"])
            or bool(report.baseline["missing"])
        )
    return 1 if failed else 0
