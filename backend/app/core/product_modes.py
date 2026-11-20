"""Product surfaces (`dev` / `thesis`) shared by the tool, policy and route layers.

Keeping the mode names and per-mode tool sets in one place prevents the API,
tool registry and security policy from drifting apart when a new mode or tool
is added.
"""
from __future__ import annotations

DEV = "dev"
THESIS = "thesis"
PRODUCT_MODES = (DEV, THESIS)

# Read-only tools that only make sense inside a thesis project.
THESIS_TOOL_NAMES = frozenset({
    "thesis_outline",
    "thesis_read_section",
    "thesis_search_text",
    "thesis_issues",
    "thesis_reference_lookup",
})

# In thesis mode these need a per-call approval even in auto/full: they can
# write files, execute host commands or send content to the network.
THESIS_SENSITIVE_TOOLS = frozenset({
    "write_files", "edit_file", "run_code", "run_command", "install_deps",
    "local_run_command", "local_write_file", "fetch_url", "web_search",
})

# The subset that can mutate files on disk; the per-turn thesis file guard
# snapshots around these calls.
FILE_MUTATING_TOOLS = frozenset({
    "write_files", "edit_file", "run_code", "run_command",
    "local_run_command", "local_write_file", "install_deps",
})


def normalize_product_mode(value: str | None) -> str:
    """Unknown/legacy values fall back to dev, matching the API defaults."""
    return THESIS if value == THESIS else DEV
