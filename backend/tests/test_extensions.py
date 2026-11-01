"""Extensions status endpoint: MCP visibility and skill listing."""
import pytest

from app.api.v1.extensions import list_extensions
from app.core.mcp.manager import MCPToolInfo, manager
from app.core.skills.loader import Skill


def _tool(server: str, name: str, admin_only: bool | None, caps: list[str]) -> MCPToolInfo:
    return MCPToolInfo(
        server=server,
        name=name,
        exposed_name=f"mcp__{server}__{name}",
        description=f"{server} {name}",
        schema={"type": "object", "properties": {}},
        capabilities=caps,
        admin_only=admin_only,
    )


@pytest.mark.asyncio
async def test_extensions_hide_admin_only_servers_from_users(monkeypatch):
    tools = [
        _tool("github", "search", False, ["net.fetch"]),
        _tool("vault", "read", True, ["fs.read"]),
    ]
    monkeypatch.setattr(manager, "_started", True)
    monkeypatch.setattr(manager, "tool_infos", lambda: tools)

    result = await list_extensions(user={"role": "demo"})
    assert [server.name for server in result.mcp_servers] == ["github"]

    result = await list_extensions(user={"role": "admin"})
    assert [server.name for server in result.mcp_servers] == ["github", "vault"]


@pytest.mark.asyncio
async def test_extensions_list_skills_without_paths(monkeypatch):
    skills = [
        Skill(
            name="release",
            description="Cut a release",
            triggers=("发布",),
            body="secret body",
            path="/srv/nova/data/skills/release/SKILL.md",
        )
    ]
    monkeypatch.setattr("app.api.v1.extensions.load_skills", lambda: skills)

    result = await list_extensions(user={"role": "demo"})
    assert result.skills[0].name == "release"
    assert result.skills[0].triggers == ["发布"]
    assert "secret body" not in result.model_dump_json()
    assert "/srv/nova" not in result.model_dump_json()
