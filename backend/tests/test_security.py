"""Risk grading tests (the code-execution second line of defense)."""
from app.core.security.risk import RiskLevel, grade_risk


def test_risk_safe():
    assert grade_risk("print('hello')")[0] == RiskLevel.SAFE


def test_risk_block_rm():
    assert grade_risk("rm -rf /")[0] == RiskLevel.BLOCK


def test_risk_block_injection():
    assert grade_risk("hello; rm -rf /")[0] == RiskLevel.BLOCK


def test_risk_warn_pip():
    assert grade_risk("pip install numpy")[0] == RiskLevel.WARN


def test_risk_block_sql():
    assert grade_risk("DROP TABLE users")[0] == RiskLevel.BLOCK


def test_risk_block_eval():
    assert grade_risk("eval('1+1')")[0] == RiskLevel.BLOCK


def test_risk_returns_reasons():
    level, reasons = grade_risk("os.system('ls')")
    assert level == RiskLevel.BLOCK
    assert reasons