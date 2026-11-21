"""GitHub delivery: explicit-authorization draft PRs, CI and review status.

The integration never merges, never force-pushes and never writes to a remote
without an explicit per-request authorization from the user.  Tokens are
encrypted at rest with the existing credential helper and are never returned
by the API.
"""
from app.core.github.service import (
    GitHubError,
    connect_token,
    connection_status,
    create_draft_pr,
    disconnect,
    list_pull_requests,
    parse_remote,
    pr_status,
    repo_remote,
)

__all__ = [
    "GitHubError",
    "connect_token",
    "connection_status",
    "create_draft_pr",
    "disconnect",
    "list_pull_requests",
    "parse_remote",
    "pr_status",
    "repo_remote",
]
