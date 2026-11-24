"""High-risk memory detection.

Memory is untrusted context.  Facts that talk about deployment, credentials,
permissions, safety policy or prompt overrides must not silently become
durable background instructions: they are written as ``pending`` and wait for
the user's review.  This is a deterministic keyword screen, not a classifier;
the review queue is the final authority.
"""
from __future__ import annotations

import re

_LABELS = ("安全策略", "权限与审批", "密钥凭据", "部署发布", "提示注入")

_PATTERNS = {
    "安全策略": re.compile(
        r"(安全策略|安全校验|安全审核|绕过安全|关闭(校验|审核|防护)|"
        r"disable (safety|security)|bypass (safety|security))",
        re.IGNORECASE,
    ),
    "权限与审批": re.compile(
        r"(权限|审批|自动批准|免审批|无需批准|不用问我|"
        r"auto[- ]?approve|permission|approval)",
        re.IGNORECASE,
    ),
    "密钥凭据": re.compile(
        r"(密钥|密码|口令|凭据|私钥|token|api[_ -]?key|secret|"
        r"private key|ssh key|password)",
        re.IGNORECASE,
    ),
    "部署发布": re.compile(
        r"(部署|上线|生产环境|发布到|"
        r"\bdeploy(ment)?\b|production|release)",
        re.IGNORECASE,
    ),
    "提示注入": re.compile(
        r"((忽略|无视|忘记|不要遵守)[^。！？\n]{0,12}(指令|规则|提示)|"
        r"ignore (all |the )?(previous|above) instructions|"
        r"system prompt|系统提示词|你现在是)",
        re.IGNORECASE,
    ),
}


def assess(text: str) -> list[str]:
    """Return stable Chinese labels for every high-risk category matched."""
    value = text or ""
    return [label for label in _LABELS if _PATTERNS[label].search(value)]


def is_high_risk(text: str) -> bool:
    return bool(assess(text))
