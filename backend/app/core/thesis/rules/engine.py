"""Rule protocol, context and registry for thesis checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.thesis.models import DocumentModel, Severity


@dataclass
class RuleContext:
    template_id: str
    template: dict[str, Any]
    citation_audit: dict[str, Any] | None = None


@dataclass
class IssueDraft:
    rule_id: str
    category: str
    severity: Severity
    title: str
    detail: str
    location: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    # A fix is only declared for deterministic, attribute-level changes.
    fix_type: str | None = None
    fix_payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    template_version: str = ""
    confidence: str = "high"


class Rule(Protocol):
    id: str
    category: str

    def evaluate(self, document: DocumentModel, context: RuleContext) -> list[IssueDraft]:
        ...


SEVERITY_ORDER = {"blocker": 0, "warn": 1, "info": 2}


def _sort_key(issue: IssueDraft) -> tuple[int, int, int, str]:
    return (
        SEVERITY_ORDER.get(issue.severity, 9),
        int(issue.location.get("block_index", -1)),
        int(issue.location.get("section_index", -1)),
        issue.rule_id,
    )


def run_rules(
    document: DocumentModel,
    template_id: str | None = None,
    *,
    citation_audit: dict[str, Any] | None = None,
) -> list[IssueDraft]:
    from app.core.thesis.citations.extract import audit_citations
    from app.core.thesis.rules.builtin import RULES, get_template

    template = get_template(template_id)
    if citation_audit is None:
        citation_audit = audit_citations(document, template)
    context = RuleContext(
        template_id=template["id"],
        template=template,
        citation_audit=citation_audit,
    )
    issues: list[IssueDraft] = []
    for rule in RULES:
        issues.extend(rule.evaluate(document, context))
    for issue in issues:
        if not issue.source:
            issue.source = str(template.get("source") or "")
        if not issue.template_version:
            issue.template_version = str(template.get("version") or "")
    issues.sort(key=_sort_key)
    return issues
