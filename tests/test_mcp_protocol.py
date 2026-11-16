"""End-to-end tests through the MCP protocol, with the SDK's in-memory client.

These run the real server (lifespan, tool registration, argument validation,
result conversion) instead of calling the tool functions directly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent, TextResourceContents

from grafeo_mcp.server import mcp
from tests.conftest import client_session

EXPECTED_TOOLS = {
    "execute_gql",
    "query_as_of",
    "create_node",
    "create_edge",
    "get_node",
    "get_node_as_of",
    "search_nodes_by_label",
    "graph_info",
    "get_neighbors",
    "update_node",
    "delete_node",
    "update_edge",
    "delete_edge",
    "batch_import",
    "create_text_index",
    "search_text",
    "vector_search",
    "create_vector_index",
    "mmr_search",
    "vector_graph_search",
    "pagerank",
    "dijkstra",
    "louvain",
    "betweenness_centrality",
    "connected_components",
}

READ_ONLY_TOOLS = {
    "get_node",
    "get_node_as_of",
    "query_as_of",
    "search_nodes_by_label",
    "graph_info",
    "get_neighbors",
    "search_text",
    "vector_search",
    "mmr_search",
    "vector_graph_search",
    "pagerank",
    "dijkstra",
    "louvain",
    "betweenness_centrality",
    "connected_components",
}

DESTRUCTIVE_TOOLS = {"execute_gql", "update_node", "delete_node", "update_edge", "delete_edge"}


@pytest.fixture(autouse=True)
def _in_memory_server(monkeypatch):
    monkeypatch.delenv("GRAFEO_DB_PATH", raising=False)
    monkeypatch.delenv("GRAFEO_READ_ONLY", raising=False)


@asynccontextmanager
async def _client() -> AsyncGenerator[ClientSession]:
    async with client_session(mcp) as client:
        yield client


def _text(result: CallToolResult) -> str:
    assert len(result.content) == 1
    content = result.content[0]
    assert isinstance(content, TextContent)
    return content.text


async def _ok(client: ClientSession, tool: str, **arguments) -> str:
    result = await client.call_tool(tool, arguments)
    text = _text(result)
    assert result.is_error is False, text
    assert result.structured_content is None  # the text is the result, sent once
    return text


async def _resource(client: ClientSession, uri: str) -> str:
    contents = (await client.read_resource(uri)).contents
    assert len(contents) == 1 and isinstance(contents[0], TextResourceContents)
    return contents[0].text


async def _error(client: ClientSession, tool: str, **arguments) -> str:
    result = await client.call_tool(tool, arguments)
    text = _text(result)
    assert result.is_error is True, text
    return text


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestToolListing:
    async def test_tool_names_are_stable(self):
        async with _client() as client:
            tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == EXPECTED_TOOLS

    async def test_annotations(self):
        async with _client() as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        for name, tool in tools.items():
            assert tool.annotations is not None, name
            assert tool.annotations.read_only_hint is (name in READ_ONLY_TOOLS), name
            assert tool.annotations.open_world_hint is False, name
            if name not in READ_ONLY_TOOLS:
                assert tool.annotations.destructive_hint is (name in DESTRUCTIVE_TOOLS), name

    async def test_descriptions_are_agent_ready(self):
        async with _client() as client:
            tools = (await client.list_tools()).tools
        for tool in tools:
            description = tool.description or ""
            assert len(description) > 40, tool.name
            assert "\N{EM DASH}" not in description and "\N{EN DASH}" not in description, tool.name
            assert "auto-normaliz" not in description.lower(), f"{tool.name} still mentions query normalization"
            assert "Args:" not in description, f"{tool.name}: argument docs belong in the input schema"
            assert tool.output_schema is None, f"{tool.name}: an output schema makes every result go out twice"

    async def test_listing_stays_within_its_token_budget(self):
        """Every session pays for the tool listing: keep it near 3,000 tokens (it was about 8,500 in 0.2)."""
        async with _client() as client:
            tools = (await client.list_tools()).tools
        size = sum(
            len(tool.description or "") + len(json.dumps(tool.input_schema, separators=(",", ":"))) for tool in tools
        )
        assert size < 13_000, size

    async def test_input_schemas_are_compact(self):
        async with _client() as client:
            tools = (await client.list_tools()).tools
        for tool in tools:
            schema = tool.input_schema
            assert "title" not in schema, tool.name
            for name, prop in schema.get("properties", {}).items():
                assert "title" not in prop, (tool.name, name)
                assert "anyOf" not in prop, (tool.name, name)  # optional arguments are plain types
        execute_gql = next(tool for tool in tools if tool.name == "execute_gql")
        assert execute_gql.input_schema["properties"]["params"] == {
            "description": 'Values for $name in the query: {"name": "Ada"}.',
            "type": "object",
        }

    async def test_execute_gql_schema_has_params(self):
        async with _client() as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        properties = tools["execute_gql"].input_schema["properties"]
        assert set(properties) == {"query", "limit", "params"}
        assert tools["execute_gql"].input_schema["required"] == ["query"]


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


class TestToolCalls:
    @pytest.mark.parametrize(
        ("tool", "arguments", "expected"),
        [
            ("get_node", {"node_id": "abc"}, "Error: get_node: node_id: input should be a valid integer"),
            ("get_node", {}, "Error: get_node: node_id: field required."),
            ("create_node", {"labels": "Person"}, "Error: create_node: labels: input should be a valid list"),
        ],
    )
    async def test_argument_errors_use_the_tool_error_format(self, tool, arguments, expected):
        async with _client() as client:
            text = await _error(client, tool, **arguments)
        assert text.startswith(expected), text
        assert text.endswith("Hint: check the argument names and types in the tool's input schema.")
        assert "pydantic" not in text and "Arguments" not in text

    async def test_unknown_tool_uses_the_tool_error_format(self):
        async with _client() as client:
            text = await _error(client, "graph_overview")
        assert text.startswith("Error: graph_overview: there is no tool of that name. Hint:")

    async def test_crud_round_trip(self):
        async with _client() as client:
            alice = json.loads(await _ok(client, "create_node", labels=["Person"], properties={"name": "Alice"}))
            bob = json.loads(await _ok(client, "create_node", labels=["Person"], properties={"name": "Bob"}))
            edge = json.loads(
                await _ok(client, "create_edge", source_id=alice["id"], target_id=bob["id"], edge_type="KNOWS")
            )
            neighbors = json.loads(await _ok(client, "get_neighbors", node_id=alice["id"]))
            assert [n["node_id"] for n in neighbors["neighbors"]] == [bob["id"]]
            await _ok(client, "update_edge", edge_id=edge["id"], properties={"since": 2020})
            deleted = await _ok(client, "delete_node", node_id=alice["id"])
            assert deleted == f"Deleted node {alice['id']} (:Person) and 1 edge(s)."
            info = json.loads(await _ok(client, "graph_info"))
            assert (info["nodes"], info["edges"]) == (1, 0)

    async def test_execute_gql_with_params(self):
        async with _client() as client:
            await _ok(
                client,
                "execute_gql",
                query="INSERT (:Person {name: $name, tags: $tags})",
                params={"name": "Ada", "tags": ["x"]},
            )
            rows = json.loads(
                await _ok(client, "execute_gql", query="MATCH (p:Person) RETURN p.name AS n, p.tags AS t")
            )["rows"]
            assert rows == [{"n": "Ada", "t": ["x"]}]

    async def test_errors_are_flagged(self):
        async with _client() as client:
            text = await _error(client, "create_edge", source_id=0, target_id=1, edge_type="KNOWS")
            assert text.startswith("Error: create_edge: source node 0 does not exist")
            text = await _error(client, "execute_gql", query="INSERT (:A); INSERT (:B)")
            assert text.startswith("Error: execute_gql: the query holds 2 statements")

    async def test_invalid_arguments_are_flagged(self):
        async with _client() as client:
            result = await client.call_tool("get_node", {"node_id": "not-a-number"})
            assert result.is_error is True

    async def test_engine_panic_does_not_stop_the_server(self):
        # A query vector of the wrong size made the 0.5.x HNSW index panic, and
        # the panic (a BaseException) closed the MCP connection. grafeo 0.6
        # refuses it with an error instead; the panic guard stays for any
        # other engine panic.
        async with _client() as client:
            await _ok(client, "execute_gql", query="UNWIND range(1, 25) AS i INSERT (:Doc {i: i})")
            await _ok(client, "execute_gql", query="INSERT (:Doc {emb: $emb})", params={"emb": [1.0, 0.0, 0.0]})
            await _ok(client, "create_vector_index", label="Doc", property="emb", dimensions=3)
            await _error(client, "vector_search", label="Doc", property="emb", query_vector=[1.0, 0.0], k=3)
            info = json.loads(await _ok(client, "graph_info"))
            assert info["nodes"] == 26
            hits = json.loads(
                await _ok(client, "vector_search", label="Doc", property="emb", query_vector=[1.0, 0.0, 0.0], k=1)
            )
            assert hits[0]["node_id"] == 25

    async def test_read_only_mode(self, monkeypatch):
        monkeypatch.setenv("GRAFEO_READ_ONLY", "true")
        async with _client() as client:
            text = await _error(client, "create_node", labels=["X"])
            assert "read-only" in text
            text = await _error(client, "execute_gql", query="INSERT (:X)")
            assert "read-only" in text
            await _ok(client, "execute_gql", query="MATCH (n) RETURN count(n) AS c")
            info = json.loads(await _ok(client, "graph_info"))
            assert info["database"]["read_only"] is True


# ---------------------------------------------------------------------------
# Resources and prompts
# ---------------------------------------------------------------------------


class TestResourcesAndPrompts:
    async def test_resources_are_listed(self):
        async with _client() as client:
            resources = {str(resource.uri) for resource in (await client.list_resources()).resources}
            templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
        assert resources == {"graph://schema", "graph://stats"}
        assert templates == {"graph://nodes/{node_id}"}

    async def test_resources(self):
        # graph://schema and graph://stats could not be read over MCP before
        # (registered as parameterless templates); graph://nodes/{id} always
        # reported "isolated node" (it read query rows by position).
        async with _client() as client:
            a = json.loads(await _ok(client, "create_node", labels=["Person"], properties={"name": "Alice"}))
            b = json.loads(await _ok(client, "create_node", labels=["Company"], properties={"name": "Acme"}))
            await _ok(client, "create_edge", source_id=a["id"], target_id=b["id"], edge_type="WORKS_AT")

            schema = await _resource(client, "graph://schema")
            assert "(:Person)-[:WORKS_AT]->(:Company)" in schema
            stats = await _resource(client, "graph://stats")
            assert "Nodes: 2" in stats
            node = await _resource(client, f"graph://nodes/{a['id']}")
            assert "Outgoing: WORKS_AT (1)" in node

    async def test_prompts(self):
        async with _client() as client:
            prompts = {prompt.name for prompt in (await client.list_prompts()).prompts}
            assert prompts == {"explore_graph", "knowledge_extraction", "graph_analysis", "similarity_search"}
            result = await client.get_prompt("similarity_search", {"label": "Doc"})
            content = result.messages[0].content
            assert isinstance(content, TextContent)
            text = content.text
            assert "indexes.vector" not in text  # label given: no discovery step needed
            assert "`similarity`" not in text


async def test_descriptions_have_no_indentation():
    """Python 3.12 keeps docstring indentation (3.13 strips it): the server cleans it on every version."""
    async with _client() as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        for line in (tool.description or "").splitlines():
            assert not line.startswith("    "), (tool.name, line)
