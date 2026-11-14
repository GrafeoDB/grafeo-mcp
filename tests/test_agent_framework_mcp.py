"""Microsoft Agent Framework + Foundry drive grafeo-mcp over MCP stdio.

The Agent Framework's MCP client (``MCPStdioTool``) needs mcp>=2.2 (it imports
``MCPError``), which grafeo-mcp's own pin (``mcp>=2.2,<3``) satisfies, so
``agent-framework-core`` and ``agent-framework-foundry`` are dev dependencies
and these tests run in this repo's venv (``uv run pytest``). They spawn the
server from that venv's ``grafeo-mcp`` script as a subprocess and drive it from
the AF side, and skip when the script or ``agent_framework`` is missing.

Foundry agents connect to MCP servers the same way, so an AF ``MCPStdioTool``
against grafeo-mcp is exactly what a Microsoft Foundry agent uses for its
graph memory.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

pytest.importorskip("agent_framework")

from agent_framework import Agent, MCPStdioTool

REPO = Path(__file__).resolve().parents[1]
_SERVER_EXE = next(
    (p for p in (REPO / ".venv" / "Scripts" / "grafeo-mcp.exe", REPO / ".venv" / "bin" / "grafeo-mcp") if p.exists()),
    None,
)
pytestmark = pytest.mark.skipif(_SERVER_EXE is None, reason="repo venv with the grafeo-mcp script not found")


def _server_tool(**kwargs) -> MCPStdioTool:
    return MCPStdioTool(name="grafeo", command=str(_SERVER_EXE), args=["stdio"], request_timeout=60, **kwargs)


def _text(result) -> str:
    """The text of an AF tool result (a list of Content, or a plain string)."""
    if isinstance(result, list):
        return "".join(getattr(c, "text", "") or "" for c in result)
    return str(result)


def _payload(result) -> dict:
    """Parse a tool result's text as JSON, unwrapping MCP's {"result": ...} envelope."""
    import json

    text = _text(result)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
        try:
            return json.loads(data["result"])
        except json.JSONDecodeError:
            return data
    return data


def test_af_agent_uses_grafeo_mcp_over_stdio():
    async def _run():
        async with _server_tool() as tool:
            names = {f.name for f in tool.functions}
            assert {"execute_gql", "get_node", "query_as_of", "get_node_as_of"} <= names

            gql = next(f for f in tool.functions if f.name == "execute_gql")
            await gql.invoke(arguments={"query": "INSERT (:Person {name: 'AF'})"})
            result = await gql.invoke(arguments={"query": "MATCH (p:Person) RETURN p.name AS n"})
            assert "AF" in _text(result)

            # The server was started without GRAFEO_HISTORY_RETENTION, so time
            # travel reports the fix instead of failing obscurely (AF raises on
            # MCP error results).
            as_of = next(f for f in tool.functions if f.name == "query_as_of")
            with pytest.raises(Exception, match="GRAFEO_HISTORY_RETENTION"):
                await as_of.invoke(arguments={"query": "MATCH (p:Person) RETURN count(p) AS c", "as_of": "60"})

    asyncio.run(_run())


def test_time_travel_through_agent_framework():
    async def _run():
        env = {**os.environ, "GRAFEO_HISTORY_RETENTION": "forever"}
        async with _server_tool(env=env) as tool:
            gql = next(f for f in tool.functions if f.name == "execute_gql")
            await gql.invoke(arguments={"query": "INSERT (:Person {name: 'old'})"})
            import datetime

            now = datetime.datetime.now(datetime.UTC).isoformat()
            await asyncio.sleep(0.05)
            await gql.invoke(arguments={"query": "MATCH (p:Person {name: 'old'}) DETACH DELETE p"})

            as_of = next(f for f in tool.functions if f.name == "query_as_of")
            result = await as_of.invoke(arguments={"query": "MATCH (p:Person) RETURN count(p) AS c", "as_of": now})
            assert _payload(result)["rows"] == [{"c": 1}], _text(result)
            result = await gql.invoke(arguments={"query": "MATCH (p:Person) RETURN count(p) AS c"})
            assert _payload(result)["rows"] == [{"c": 0}], _text(result)

    asyncio.run(_run())


def test_foundry_agent_can_be_wired_with_grafeo_mcp():
    """A Microsoft Foundry agent accepts the grafeo-mcp tools (no network needed)."""
    foundry = pytest.importorskip("agent_framework.foundry")
    pytest.importorskip("agent_framework_foundry")

    async def _run():
        async with _server_tool() as tool:

            class _DummyCredential:
                def get_token(self, *scopes, **kwargs):  # azure TokenCredential shape
                    raise RuntimeError("no network in tests")

            client = foundry.FoundryChatClient(
                project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
                credential=_DummyCredential(),
                model="demo-deployment",
            )
            agent = Agent(client, tools=[tool])
            names = {f.name for f in tool.functions}
            assert agent is not None
            assert "execute_gql" in names and "query_as_of" in names

    asyncio.run(_run())
