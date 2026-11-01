"""Extensions status: operator-provided MCP tools and SKILL.md playbooks."""
from fastapi import APIRouter, Depends

from app.config import settings
from app.core.mcp.manager import manager, server_admin_only_for
from app.core.security.auth import get_current_user
from app.core.skills.loader import load_skills
from app.models.schemas import (
    ExtensionServerOut,
    ExtensionToolOut,
    ExtensionsOut,
    SkillInfoOut,
)

router = APIRouter()


@router.get("/extensions", response_model=ExtensionsOut)
async def list_extensions(user: dict = Depends(get_current_user)) -> ExtensionsOut:
    is_admin = user.get("role") == "admin"

    grouped: dict[str, ExtensionServerOut] = {}
    if settings.mcp_enabled and manager.started:
        for info in manager.tool_infos():
            admin_only = bool(server_admin_only_for(info))
            if not is_admin and (admin_only or "secrets.read" in info.capabilities):
                continue
            server = grouped.get(info.server)
            if server is None:
                server = ExtensionServerOut(name=info.server)
                grouped[info.server] = server
            server.tools.append(ExtensionToolOut(
                name=info.name,
                description=info.description,
                admin_only=admin_only,
            ))

    skills = [
        SkillInfoOut(
            name=skill.name,
            description=skill.description,
            triggers=list(skill.triggers),
        )
        for skill in load_skills()
    ] if settings.skills_enabled else []

    return ExtensionsOut(
        mcp_enabled=settings.mcp_enabled,
        mcp_ready=bool(manager.started),
        mcp_servers=sorted(grouped.values(), key=lambda item: item.name),
        skills_enabled=settings.skills_enabled,
        skills=skills,
    )
