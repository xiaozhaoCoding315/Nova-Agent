"""Raised when a proposal's base snapshot no longer matches the workspace."""


class ConflictError(ValueError):
    """The files changed after the proposal was generated; re-read required."""
