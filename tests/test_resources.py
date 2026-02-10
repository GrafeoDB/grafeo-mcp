"""Tests for resources — graph://schema, graph://stats, graph://nodes/{node_id}."""

from __future__ import annotations

from grafeo_mcp.resources.nodes import get_node_resource
from grafeo_mcp.resources.schema import graph_schema, graph_stats

# ---------------------------------------------------------------------------
# graph://schema
# ---------------------------------------------------------------------------


class TestGraphSchema:
    def test_empty_db(self, ctx):
        result = graph_schema(ctx=ctx)
        assert "Graph Schema" in result
        assert "0 nodes" in result

    def test_populated(self, populated_ctx):
        result = graph_schema(ctx=populated_ctx)
        assert "Person" in result
        assert "Company" in result
        assert "KNOWS" in result
        assert "WORKS_AT" in result
        assert "5 nodes" in result


# ---------------------------------------------------------------------------
# graph://stats
# ---------------------------------------------------------------------------


class TestGraphStats:
    def test_empty_db(self, ctx):
        result = graph_stats(ctx=ctx)
        assert "Database Statistics" in result
        assert "Nodes: 0" in result

    def test_populated(self, populated_ctx):
        result = graph_stats(ctx=populated_ctx)
        assert "Nodes: 5" in result
        assert "Edges: 5" in result


# ---------------------------------------------------------------------------
# graph://nodes/{node_id}
# ---------------------------------------------------------------------------


class TestNodeResource:
    def test_existing_node(self, populated_ctx):
        result = get_node_resource("0", ctx=populated_ctx)
        assert "Node 0" in result
        assert "Person" in result
        assert "Properties:" in result

    def test_not_found(self, ctx):
        result = get_node_resource("9999", ctx=ctx)
        assert "not found" in result.lower()

    def test_invalid_id(self, ctx):
        result = get_node_resource("abc", ctx=ctx)
        assert "not a valid node ID" in result

    def test_connection_summary(self, populated_ctx):
        # Alice (0) has outgoing edges
        result = get_node_resource("0", ctx=populated_ctx)
        assert "Connections:" in result
