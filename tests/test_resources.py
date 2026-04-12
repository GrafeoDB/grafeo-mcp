"""Tests for resources — graph://schema, graph://stats, graph://nodes/{node_id}."""

from __future__ import annotations

import json

from grafeo_mcp.resources.nodes import get_node_resource
from grafeo_mcp.resources.schema import graph_schema, graph_stats
from grafeo_mcp.tools.graph import create_edge, create_node

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


# ---------------------------------------------------------------------------
# T14: Resources after mutations return well-formed responses
# ---------------------------------------------------------------------------


class TestResourcesAfterMutation:
    def test_schema_reflects_new_nodes(self, ctx):
        create_node(["Widget"], {"color": "red"}, ctx=ctx)
        result = graph_schema(ctx=ctx)
        assert "Widget" in result
        assert "1 nodes" in result or "1 node" in result

    def test_stats_reflects_new_nodes_and_edges(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        create_edge(n1["id"], n2["id"], "LINKS", ctx=ctx)
        result = graph_stats(ctx=ctx)
        assert "Nodes: 2" in result
        assert "Edges: 1" in result

    def test_node_resource_reflects_mutation(self, ctx):
        node = json.loads(create_node(["Gadget"], {"name": "gizmo"}, ctx=ctx))
        result = get_node_resource(str(node["id"]), ctx=ctx)
        assert "Gadget" in result
        assert "gizmo" in result
        assert f"Node {node['id']}" in result

    def test_node_resource_well_formed_after_edge_creation(self, ctx):
        n1 = json.loads(create_node(["X"], {"name": "x1"}, ctx=ctx))
        n2 = json.loads(create_node(["Y"], {"name": "y1"}, ctx=ctx))
        create_edge(n1["id"], n2["id"], "RELATED", ctx=ctx)
        result = get_node_resource(str(n1["id"]), ctx=ctx)
        # The resource should always return a well-formed response with
        # node identity, labels, properties, and a connections section
        assert f"Node {n1['id']}" in result
        assert "Labels:" in result
        assert "Properties:" in result
        assert "Connections:" in result
