"""Shared document workspace contracts.

M1 defines the intermediate representation (IR), change sets, versions and
fidelity reports.  Format adapters (Markdown, DOCX, PDF) build on these
contracts in later milestones; the contracts deliberately do not claim that
every source format can be represented losslessly.
"""
from app.core.documents.ir import (
    Asset,
    Block,
    ChangeOperation,
    ChangeSet,
    Diagnostic,
    DocumentCapabilities,
    DocumentIR,
    FidelityReport,
    Inline,
    SourceLocator,
    VersionRef,
)
from app.core.documents.markdown import parse_markdown
from app.core.documents.serialize import (
    SCHEMA_VERSION,
    document_from_dict,
    document_to_dict,
)

__all__ = [
    "Asset",
    "Block",
    "ChangeOperation",
    "ChangeSet",
    "Diagnostic",
    "DocumentCapabilities",
    "DocumentIR",
    "FidelityReport",
    "Inline",
    "SCHEMA_VERSION",
    "SourceLocator",
    "VersionRef",
    "document_from_dict",
    "document_to_dict",
    "parse_markdown",
]
