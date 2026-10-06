"""Tests for read-only mode — verify mutations are blocked, reads allowed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import grafeo
import pytest

from grafeo_mcp.tools.batch import batch_import
from grafeo_mcp.tools.graph import (
    create_edge,
    create_node,
    delete_edge,
    delete_node,
    get_neighbors,
    get_node,
    graph_info,
    search_nodes_by_label,
    update_edge,
    update_node,
)
from grafeo_mcp.tools.query import _run_read_only, execute_gql
from grafeo_mcp.tools.search import create_text_index
from grafeo_mcp.tools.vector import create_vector_index

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _RoLifespan:
    db: Any
    read_only: bool = True


@dataclass
class _RoRequest:
    lifespan_context: _RoLifespan


@dataclass
class _RoContext:
    request_context: _RoRequest


@pytest.fixture()
def ro_ctx():
    """Mock MCP context with read_only=True and a small graph."""
    database = grafeo.GrafeoDB()
    database.create_node(["Person"], {"name": "Alice"})
    database.create_node(["Person"], {"name": "Bob"})
    database.create_edge(0, 1, "KNOWS")
    ctx = _RoContext(request_context=_RoRequest(lifespan_context=_RoLifespan(db=database)))
    yield ctx
    database.close()


# ---------------------------------------------------------------------------
# Mutation tools should be blocked
# ---------------------------------------------------------------------------


class TestReadOnlyBlocked:
    def test_create_node_blocked(self, ro_ctx):
        result = create_node(["X"], ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_create_edge_blocked(self, ro_ctx):
        result = create_edge(0, 1, "REL", ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_update_node_blocked(self, ro_ctx):
        result = update_node(0, {"age": 30}, ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_delete_node_blocked(self, ro_ctx):
        result = delete_node(0, ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_update_edge_blocked(self, ro_ctx):
        result = update_edge(0, {"weight": 1.0}, ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_delete_edge_blocked(self, ro_ctx):
        result = delete_edge(0, ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_batch_import_blocked(self, ro_ctx):
        result = batch_import(nodes=[{"labels": ["X"]}], ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_create_text_index_blocked(self, ro_ctx):
        result = create_text_index("X", "y", ctx=ro_ctx)
        assert "read-only" in result.lower()

    def test_create_vector_index_blocked(self, ro_ctx):
        result = create_vector_index("X", "y", 3, ctx=ro_ctx)
        assert "read-only" in result.lower()


# ---------------------------------------------------------------------------
# Read-only tools should still work
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T12: Exhaustive parametrized check over ALL mutation tool names
# ---------------------------------------------------------------------------

# Each entry is (callable, args) for a mutation tool. The args provide the
# minimum required positional arguments so the function reaches the
# read-only guard before doing real work.
_MUTATION_TOOLS = [
    pytest.param(lambda ctx: create_node(["X"], ctx=ctx), id="create_node"),
    pytest.param(lambda ctx: create_edge(0, 1, "REL", ctx=ctx), id="create_edge"),
    pytest.param(lambda ctx: update_node(0, {"a": 1}, ctx=ctx), id="update_node"),
    pytest.param(lambda ctx: delete_node(0, ctx=ctx), id="delete_node"),
    pytest.param(lambda ctx: update_edge(0, {"a": 1}, ctx=ctx), id="update_edge"),
    pytest.param(lambda ctx: delete_edge(0, ctx=ctx), id="delete_edge"),
    pytest.param(lambda ctx: batch_import(nodes=[{"labels": ["X"]}], ctx=ctx), id="batch_import"),
    pytest.param(lambda ctx: create_text_index("X", "y", ctx=ctx), id="create_text_index"),
    pytest.param(lambda ctx: create_vector_index("X", "y", 3, ctx=ctx), id="create_vector_index"),
]


class TestReadOnlyExhaustive:
    @pytest.mark.parametrize("call_tool", _MUTATION_TOOLS)
    def test_consistent_error_format(self, ro_ctx, call_tool):
        result = call_tool(ro_ctx)
        lower = result.lower()
        assert "read-only" in lower, f"Expected 'read-only' in: {result}"
        assert "error" in lower, f"Expected 'error' in: {result}"


class TestReadOnlyAllowed:
    def test_get_node_allowed(self, ro_ctx):
        result = get_node(0, ctx=ro_ctx)
        assert "read-only" not in result.lower()
        assert "Alice" in result

    def test_graph_info_allowed(self, ro_ctx):
        result = graph_info(ctx=ro_ctx)
        assert "read-only" not in result.lower()

    def test_search_nodes_by_label_allowed(self, ro_ctx):
        result = search_nodes_by_label("Person", ctx=ro_ctx)
        assert "read-only" not in result.lower()


# ---------------------------------------------------------------------------
# execute_gql honours read-only mode (it used to run writes unchecked)
# ---------------------------------------------------------------------------


class TestReadOnlyExecuteGql:
    @pytest.mark.parametrize(
        "query",
        [
            "INSERT (:X)",
            "CREATE (:X)",
            "MERGE (p:Person {name: 'Carol'})",
            "MATCH (p:Person) SET p.age = 1",
            "MATCH (p:Person) REMOVE p.name",
            "MATCH (p:Person) DETACH DELETE p",
            "CREATE GRAPH other",
            "DROP GRAPH other",
            "CREATE INDEX idx FOR (p:Person) ON (p.name)",
            "CREATE CONSTRAINT FOR (p:Person) ON (p.name) UNIQUE",
        ],
    )
    def test_writes_refused(self, ro_ctx, query):
        db = ro_ctx.request_context.lifespan_context.db
        result = execute_gql(query, ctx=ro_ctx)
        assert result.startswith("Error: execute_gql: the server is in read-only mode"), result
        assert db.node_count == 2
        assert db.list_graphs() == []
        assert list(db.execute("SHOW INDEXES")) == []
        assert list(db.execute("SHOW CONSTRAINTS")) == []
        assert db.get_node(0).properties() == {"name": "Alice"}

    def test_reads_allowed(self, ro_ctx):
        result = json.loads(execute_gql("MATCH (p:Person) RETURN p.name AS name ORDER BY name", ctx=ro_ctx))
        assert [row["name"] for row in result["rows"]] == ["Alice", "Bob"]

    def test_reads_with_params(self, ro_ctx):
        result = json.loads(
            execute_gql("MATCH (p:Person) WHERE p.name = $n RETURN id(p) AS id", params={"n": "Bob"}, ctx=ro_ctx)
        )
        assert result["rows"] == [{"id": 1}]

    def test_write_words_in_strings_and_properties_allowed(self, ro_ctx):
        result = json.loads(
            execute_gql(
                "MATCH (p:Person) WHERE p.name <> 'DELETE' RETURN p.name AS `create`, p.set AS unset", ctx=ro_ctx
            )
        )
        assert result["total_rows"] == 2

    def test_rollback_backstop(self, ro_ctx):
        # Writes that slip past the keyword check (none known) are undone and
        # reported: the query runs in a transaction that is always rolled back.
        db = ro_ctx.request_context.lifespan_context.db
        result, wrote = _run_read_only(db, "MATCH (p:Person) SET p.flag = true RETURN p.name AS name", None)
        assert wrote
        assert len(result) == 2
        assert "flag" not in db.get_node(0).properties()

    def test_other_read_tools_allowed(self, ro_ctx):
        assert get_neighbors(0, ctx=ro_ctx).startswith("{")
        assert json.loads(graph_info(ctx=ro_ctx))["server"] == {"read_only": True}
