"""CLI parsing, report paths, and exit codes."""
import json

import pytest

from evals.cli import main
from evals.tasks import ALL_TASKS


def test_list_prints_every_task(capsys):
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    for task in ALL_TASKS:
        assert task.id in output


def test_scripted_run_writes_json_and_markdown(tmp_path, capsys):
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    code = main([
        "run", "--mode", "scripted", "--ci",
        "--json", str(json_path), "--md", str(md_path),
        "--report-dir", str(tmp_path),
    ])
    assert code == 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["summary"]["passed"] == 7
    assert data["summary"]["failed"] == 0
    assert md_path.read_text(encoding="utf-8").startswith("# Nova Agent Eval — scripted")
    assert "read_and_answer" in capsys.readouterr().out


def test_unknown_task_returns_2(capsys):
    assert main(["run", "--mode", "scripted", "--task", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_ci_rejects_live_mode(capsys):
    assert main(["run", "--mode", "live", "--ci"]) == 2
    assert "--ci" in capsys.readouterr().err


def test_min_pass_rate_above_one_exits_1(tmp_path):
    code = main([
        "run", "--mode", "scripted", "--min-pass-rate", "1.1",
        "--json", str(tmp_path / "r.json"), "--md", str(tmp_path / "r.md"),
    ])
    assert code == 1


def test_unknown_provider_returns_2(capsys):
    assert main(["run", "--mode", "live", "--provider", "typo"]) == 2
    assert "typo" in capsys.readouterr().err


@pytest.mark.parametrize("rate", ["nan", "-0.1"])
def test_invalid_min_pass_rate_returns_2(rate, capsys):
    assert main(["run", "--mode", "scripted", "--min-pass-rate", rate]) == 2
    assert "min-pass-rate" in capsys.readouterr().err


def test_malformed_baseline_returns_2(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text("[]", encoding="utf-8")
    code = main([
        "run", "--mode", "scripted", "--task", "read_and_answer",
        "--baseline", str(baseline),
        "--json", str(tmp_path / "r.json"), "--md", str(tmp_path / "r.md"),
    ])
    assert code == 2
    assert "基线" in capsys.readouterr().err
