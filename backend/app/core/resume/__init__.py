"""Resume mode (M4): profiles, evidence-status facts and job versions.

Public API for the resume domain.  Storage is plain per-user JSON under
``settings.user_data_dir``; no database or network access is required.
"""
from app.core.resume.models import (
    DEFAULT_TEMPLATE,
    FACT_STATUSES,
    INCLUDABLE_FACT_STATUSES,
    MAX_JD_CHARS,
    RESUME_ID_PATTERN,
    STATUS_LABELS,
    TEMPLATES,
    Fact,
    JobVersion,
    Profile,
    ResumeError,
    ResumeNotFound,
    ensure_fact_includable,
    is_valid_resume_id,
    metric_has_number,
    needs_confirmation,
    normalise_contact,
    normalise_fact_ids,
    normalise_metrics,
    normalise_status,
    require_known_status,
    requires_evidence,
)
from app.core.resume.store import (
    DISCLAIMER,
    FACT_SCHEMA,
    PROFILE_SCHEMA,
    VERSION_SCHEMA,
    add_fact,
    create_job_version,
    create_profile,
    get_job_version,
    get_profile,
    list_facts,
    list_job_versions,
    list_profiles,
    render_job_version,
    resume_root,
    update_fact,
)

__all__ = [
    "DEFAULT_TEMPLATE", "DISCLAIMER", "FACT_SCHEMA", "FACT_STATUSES",
    "INCLUDABLE_FACT_STATUSES", "MAX_JD_CHARS", "PROFILE_SCHEMA",
    "RESUME_ID_PATTERN", "STATUS_LABELS", "TEMPLATES", "VERSION_SCHEMA",
    "Fact", "JobVersion", "Profile", "ResumeError", "ResumeNotFound",
    "add_fact", "create_job_version", "create_profile", "ensure_fact_includable",
    "get_job_version", "get_profile", "is_valid_resume_id", "list_facts",
    "list_job_versions", "list_profiles", "metric_has_number",
    "needs_confirmation", "normalise_contact", "normalise_fact_ids",
    "normalise_metrics", "normalise_status", "render_job_version",
    "require_known_status", "requires_evidence", "resume_root", "update_fact",
]
