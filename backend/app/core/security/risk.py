from enum import Enum
import re

class RiskLevel(str, Enum):
    SAFE = "safe"
    WARN = "warn"
    BLOCK = "block"

DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+(-rf?\s*/|--root\b)'),
    re.compile(r'\bdd\s+if='),
    re.compile(r'\bchmod\s+4?777\b'),
    re.compile(r'\bnc\s+-[e|l].+/bin/(ba)?sh'),
    re.compile(r'\bcurl\b.*\|.*\bsh\b'),
    re.compile(r'\bos\.system\s*\('),
    re.compile(r'\bsubprocess\b.*shell\s*=\s*True'),
    re.compile(r'__import__\s*\('),
    re.compile(r'\bdrop\s+table\b', re.IGNORECASE),
    re.compile(r'\bdrop\s+database\b', re.IGNORECASE),
    re.compile(r'\beval\s*\('),
]

WARNING_PATTERNS = [
    re.compile(r'\bsudo\b'),
    re.compile(r'\bapt\b.*\b(install|remove)\b'),
    re.compile(r'\bpip\b.*\b(uninstall|install)\b'),
    re.compile(r'\bgit\b.*\bpush\b'),
    re.compile(r'\bdocker\b.*\b(rm|kill)\b'),
]

INJECTION_PATTERNS = [
    re.compile(r'[;&|`]\s*(rm|curl|wget|bash|sh|python)\b'),
    re.compile(r'\$\(.*rm\|curl'),
    re.compile(r'`.*rm\|curl'),
]

def grade_risk(code: str) -> tuple:
    reasons = []
    for p in INJECTION_PATTERNS:
        m = p.search(code)
        if m:
            return RiskLevel.BLOCK, [f"Command injection: '{m.group()}'"]
    for p in DANGEROUS_PATTERNS:
        m = p.search(code)
        if m:
            reasons.append(f"Dangerous: '{m.group()}'")
    if reasons:
        return RiskLevel.BLOCK, reasons
    for p in WARNING_PATTERNS:
        m = p.search(code)
        if m:
            reasons.append(f"Warning: '{m.group()}'")
    if reasons:
        return RiskLevel.WARN, reasons
    return RiskLevel.SAFE, ["OK"]
