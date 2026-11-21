"""Persistence for the thesis stage machine.

One JSON document per project holds the current state; every transition is
also appended to ``thesis_stage_events``.  The API and the chat context read
from the same place, so a stage shown in the UI cannot diverge from the stage
the agent is told about.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.thesis import stages
from app.db import execute, query

MAX_EVENTS = 100

EVENT_COLUMNS = """
    id::text, event_type, stage, from_stage, readiness, content_sha, note, created_at
"""


def _valid_project_id(project_id: str) -> str:
    try:
        return str(uuid.UUID(str(project_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise LookupError("论文项目不存在") from exc


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _load(user_id: int, project_id: str) -> stages.StageState:
    project_id = _valid_project_id(project_id)
    rows = await query(
        "SELECT stage_state FROM thesis_projects WHERE id = %s AND user_id = %s",
        (project_id, user_id),
    )
    if not rows:
        raise LookupError("论文项目不存在或无权访问")
    return stages.StageState.from_dict(_json_object(rows[0][0]))


def _event_params(user_id: int, project_id: str, event: stages.StageEvent) -> tuple:
    return (
        str(uuid.UUID(event.id)), project_id, user_id, event.type, event.stage,
        event.from_stage, event.readiness, event.content_sha, event.note,
    )


async def _persist(
    user_id: int, project_id: str, state: stages.StageState,
    events: list[stages.StageEvent],
) -> dict[str, Any]:
    project_id = _valid_project_id(project_id)
    await execute(
        "UPDATE thesis_projects SET stage_state = %s::jsonb, updated_at = now() "
        "WHERE id = %s AND user_id = %s",
        (json.dumps(state.to_dict(), ensure_ascii=False), project_id, user_id),
    )
    for event in events:
        await execute(
            "INSERT INTO thesis_stage_events "
            "(id, project_id, user_id, event_type, stage, from_stage, readiness, "
            " content_sha, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            _event_params(user_id, project_id, event),
        )
    return await get_board(user_id, project_id)


def _event_dict(row: tuple) -> dict[str, Any]:
    created = row[7]
    return {
        "id": str(row[0]),
        "type": str(row[1]),
        "stage": str(row[2]),
        "from_stage": str(row[3] or ""),
        "readiness": str(row[4] or ""),
        "content_sha": str(row[5] or ""),
        "note": str(row[6] or ""),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
    }


async def get_state(user_id: int, project_id: str) -> stages.StageState:
    """Read state without touching events; used by the chat context."""
    return await _load(user_id, project_id)


async def get_board(user_id: int, project_id: str) -> dict[str, Any]:
    project_id = _valid_project_id(project_id)
    state = await _load(user_id, project_id)

    # A confirmation is only valid for the exact stage note the author saw.
    current_hashes = {
        stage: stages.digest_text(content) for stage, content in state.contents.items()
    }
    stale_events = stages.mark_stale(state, current_hashes)
    if stale_events:
        await execute(
            "UPDATE thesis_projects SET stage_state = %s::jsonb, updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            (json.dumps(state.to_dict(), ensure_ascii=False), project_id, user_id),
        )
        for event in stale_events:
            await execute(
                "INSERT INTO thesis_stage_events "
                "(id, project_id, user_id, event_type, stage, from_stage, readiness, "
                " content_sha, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                _event_params(user_id, project_id, event),
            )

    rows = await query(
        f"SELECT {EVENT_COLUMNS} FROM thesis_stage_events "
        "WHERE project_id = %s AND user_id = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (project_id, user_id, MAX_EVENTS),
    )
    return {
        "project_id": project_id,
        "state": state.to_dict(),
        "summary": stages.stage_summary(state),
        "current_content": state.contents.get(state.stage, ""),
        "events": [_event_dict(row) for row in rows],
    }


async def get_export_readiness(user_id: int, project_id: str) -> dict[str, Any]:
    """Preflight for the final package: what is still unconfirmed.

    This is advisory, not a hard gate.  ``get_board`` first so confirmations
    whose content changed are marked stale in the same place the UI reads.
    """
    board = await get_board(user_id, project_id)
    state = stages.StageState.from_dict(board["state"])
    warnings = stages.export_warnings(state)
    return {
        "project_id": board["project_id"],
        "ready": not warnings,
        "stage": state.stage,
        "readiness": state.readiness,
        "warnings": warnings,
    }


async def record_draft(
    user_id: int, project_id: str, content: str, note: str = "",
) -> None:
    """Append an AI-draft provenance event without changing stage state."""
    state = await _load(user_id, project_id)
    project_id = _valid_project_id(project_id)
    event = stages.draft_event(
        state,
        stages.digest_text(content),
        note or "AI 草稿，需作者核对",
    )
    await execute(
        "INSERT INTO thesis_stage_events "
        "(id, project_id, user_id, event_type, stage, from_stage, readiness, "
        " content_sha, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        _event_params(user_id, project_id, event),
    )


async def set_readiness(user_id: int, project_id: str, value: str) -> dict[str, Any]:
    state = await _load(user_id, project_id)
    event = stages.set_readiness(state, value)
    return await _persist(user_id, project_id, state, [event])


async def set_content(user_id: int, project_id: str, content: str) -> dict[str, Any]:
    state = await _load(user_id, project_id)
    events = stages.set_content(state, content)
    if not events:
        return await get_board(user_id, project_id)
    return await _persist(user_id, project_id, state, events)


async def confirm_stage(user_id: int, project_id: str, note: str = "") -> dict[str, Any]:
    state = await _load(user_id, project_id)
    content = state.contents.get(state.stage, "")
    if not content.strip():
        raise ValueError("请先填写本阶段内容，再确认")
    event = stages.confirm(state, stages.digest_text(content), note=note)
    return await _persist(user_id, project_id, state, [event])


async def advance(user_id: int, project_id: str, to_stage: str | None = None) -> dict[str, Any]:
    state = await _load(user_id, project_id)
    event = stages.advance(state, to_stage)
    return await _persist(user_id, project_id, state, [event])


async def return_to(user_id: int, project_id: str, to_stage: str) -> dict[str, Any]:
    state = await _load(user_id, project_id)
    events = stages.return_to(state, to_stage)
    return await _persist(user_id, project_id, state, events)


__all__ = [
    "advance", "confirm_stage", "get_board", "get_export_readiness", "get_state",
    "record_draft", "return_to", "set_content", "set_readiness",
]
