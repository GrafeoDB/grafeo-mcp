"""Tests for tools/graph.py — CRUD operations, get_neighbors, graph_info."""

from __future__ import annotations

import json

from grafeo_mcp.tools.graph import (
    create_edge,
    create_node,
    get_neighbors,
    get_node,
    graph_info,
    search_nodes_by_label,
)

# ---------------------------------------------------------------------------
# create_node
# ---------------------------------------------------------------------------


class TestCreateNode:
    def test_basic(self, ctx):
        result = json.loads(create_node(["Person"], {"name": "Eve"}, ctx=ctx))
        assert result["labels"] == ["Person"]
        assert result["properties"]["name"] == "Eve"
        assert "id" in result

    def test_multiple_labels(self, ctx):
        result = json.loads(create_node(["Person", "Employee"], ctx=ctx))
        assert set(result["labels"]) == {"Person", "Employee"}

    def test_no_properties(self, ctx):
        result = json.loads(create_node(["Tag"], ctx=ctx))
        assert result["labels"] == ["Tag"]


# ---------------------------------------------------------------------------
# create_edge
# ---------------------------------------------------------------------------


class TestCreateEdge:
    def test_basic(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        result = json.loads(create_edge(n1["id"], n2["id"], "LINKS", ctx=ctx))
        assert result["edge_type"] == "LINKS"
        assert result["source_id"] == n1["id"]
        assert result["target_id"] == n2["id"]

    def test_with_properties(self, ctx):
        n1 = json.loads(create_node(["X"], ctx=ctx))
        n2 = json.loads(create_node(["Y"], ctx=ctx))
        result = json.loads(create_edge(n1["id"], n2["id"], "REL", {"weight": 1.5}, ctx=ctx))
        assert result["properties"]["weight"] == 1.5

    def test_dangling_edge_allowed(self, ctx):
        # GrafeoDB allows creating edges to non-existent nodes (dangling edges)
        result = json.loads(create_edge(9999, 8888, "GHOST", ctx=ctx))
        assert result["edge_type"] == "GHOST"
        assert result["source_id"] == 9999
        assert result["target_id"] == 8888


# ---------------------------------------------------------------------------
# get_node
# ---------------------------------------------------------------------------


class TestGetNode:
    def test_existing(self, populated_ctx):
        result = json.loads(get_node(0, ctx=populated_ctx))
        assert "labels" in result
        assert "properties" in result

    def test_not_found(self, ctx):
        result = get_node(9999, ctx=ctx)
        assert "not found" in result.lower()
        assert "graph_info" in result  # recovery hint


# ---------------------------------------------------------------------------
# search_nodes_by_label
# ---------------------------------------------------------------------------


class TestSearchNodesByLabel:
    def test_basic(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Person", ctx=populated_ctx))
        assert result["label"] == "Person"
        assert result["count"] == 3  # Alice, Bob, Charlie

    def test_with_limit(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Person", limit=1, ctx=populated_ctx))
        assert result["count"] == 1
        assert result["limit"] == 1

    def test_with_offset(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Person", limit=1, offset=1, ctx=populated_ctx))
        assert result["count"] == 1
        assert result["offset"] == 1

    def test_nonexistent_label(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Alien", ctx=populated_ctx))
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# graph_info
# ---------------------------------------------------------------------------


class TestGraphInfo:
    def test_empty_db(self, ctx):
        result = json.loads(graph_info(ctx=ctx))
        assert "info" in result
        assert "schema" in result
        assert "stats" in result

    def test_populated(self, populated_ctx):
        result = json.loads(graph_info(ctx=populated_ctx))
        info = result["info"]
        assert info["node_count"] == 5
        assert info["edge_count"] == 5


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------


class TestGetNeighbors:
    def test_both_directions(self, populated_ctx):
        # Alice (id=0) has outgoing KNOWS->Bob and WORKS_AT->Acme
        result = json.loads(get_neighbors(0, ctx=populated_ctx))
        assert result["count"] >= 2
        assert result["direction"] == "both"

    def test_outgoing_only(self, populated_ctx):
        result = json.loads(get_neighbors(0, direction="outgoing", ctx=populated_ctx))
        assert result["direction"] == "outgoing"
        assert result["count"] >= 1

    def test_incoming_only(self, populated_ctx):
        # Bob (id=1) has incoming KNOWS from Alice
        result = json.loads(get_neighbors(1, direction="incoming", ctx=populated_ctx))
        assert result["direction"] == "incoming"

    def test_edge_type_filter(self, populated_ctx):
        result = json.loads(get_neighbors(0, edge_type="KNOWS", ctx=populated_ctx))
        assert result["edge_type_filter"] == "KNOWS"
        for neighbor in result["neighbors"]:
            assert neighbor["edge_type"] == "KNOWS"

    def test_node_not_found(self, ctx):
        result = get_neighbors(9999, ctx=ctx)
        assert "not found" in result.lower()

    def test_limit(self, populated_ctx):
        result = json.loads(get_neighbors(0, limit=1, ctx=populated_ctx))
        assert result["count"] <= 1
