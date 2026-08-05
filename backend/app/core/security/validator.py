import html
import re
from app.core.security.risk import grade_risk, RiskLevel

MAX_PROMPT_LENGTH = 10000
MAX_CODE_LENGTH = 50000

class ValidationResult:
    def __init__(self, valid, sanitized, risk_level, messages):
        self.valid = valid
        self.sanitized = sanitized
        self.risk_level = risk_level
        self.messages = messages
    def to_dict(self):
        return {"valid": self.valid, "risk_level": self.risk_level.value, "messages": self.messages}

def validate_prompt(prompt: str) -> ValidationResult:
    if not prompt or not prompt.strip():
        return ValidationResult(False, "", RiskLevel.SAFE, ["Empty prompt"])
    if len(prompt) > MAX_PROMPT_LENGTH:
        return ValidationResult(False, "", RiskLevel.BLOCK, ["Prompt too long"])
    sanitized = html.escape(prompt.strip())
    injection_kws = ["ignore previous", "ignore above", "you are now", "pretend you are", "system prompt", "override instructions"]
    for kw in injection_kws:
        if kw.lower() in prompt.lower():
            return ValidationResult(False, sanitized, RiskLevel.BLOCK, [f"Prompt injection: '{kw}'"])
    return ValidationResult(True, sanitized, RiskLevel.SAFE, ["OK"])

def validate_code(code: str) -> ValidationResult:
    if not code or not code.strip():
        return ValidationResult(False, "", RiskLevel.SAFE, ["Empty code"])
    if len(code) > MAX_CODE_LENGTH:
        return ValidationResult(False, "", RiskLevel.BLOCK, ["Code too large"])
    risk, reasons = grade_risk(code)
    return ValidationResult(risk != RiskLevel.BLOCK, code, risk, reasons)
