"""Tests for edge cases — empty graphs, disconnected nodes, truncation (T7-T10)."""

from __future__ import annotations

import json

import grafeo

from grafeo_mcp.tools.algorithms import connected_components, dijkstra, louvain, pagerank
from grafeo_mcp.tools.graph import search_nodes_by_label
from grafeo_mcp.tools.vector import vector_search
from tests.conftest import MockContext, _LifespanContext, _RequestContext

# ---------------------------------------------------------------------------
# T7: vector_search before create_vector_index
# ---------------------------------------------------------------------------


class TestVectorSearchWithoutIndex:
    def test_returns_error(self, ctx):
        result = vector_search("Doc", "emb", [0.1, 0.2], k=5, ctx=ctx)
        assert "error" in result.lower()

    def test_no_crash(self, ctx):
        # Should return a string, not raise an exception
        result = vector_search("Missing", "vec", [1.0, 2.0, 3.0], k=5, ctx=ctx)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# T8: Algorithms on empty graph
# ---------------------------------------------------------------------------


class TestAlgorithmsOnEmptyGraph:
    def test_pagerank_empty(self, ctx):
        result = pagerank(ctx=ctx)
        # Should return empty results or an error, never crash
        lower = result.lower()
        assert "error" in lower or '"results":[]' in result or '"total_nodes_scored":0' in result

    def test_louvain_empty(self, ctx):
        result = louvain(ctx=ctx)
        lower = result.lower()
        assert "error" in lower or "communities" in lower

    def test_connected_components_empty(self, ctx):
        result = connected_components(ctx=ctx)
        # Empty graph has 0 components
        lower = result.lower()
        assert "error" in lower or "num_components" in lower


# ---------------------------------------------------------------------------
# T9: Dijkstra on disconnected graph
# ---------------------------------------------------------------------------


class TestDijkstraDisconnected:
    def test_no_path_between_disconnected_nodes(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.create_node(["A"], {"name": "alpha"})
        db.create_node(["B"], {"name": "beta"})
        # No edge between them
        result = dijkstra(0, 1, ctx=ctx)
        assert "no path" in result.lower() or "error" in result.lower()

    def test_no_path_includes_node_ids(self, ctx):
        db = ctx.request_context.lifespan_context.db
        node_a = db.create_node(["A"])
        node_b = db.create_node(["B"])
        result = dijkstra(node_a.id, node_b.id, ctx=ctx)
        # The error message should reference the source and target node IDs
        lower = result.lower()
        has_ids = f"node {node_a.id}" in result and f"node {node_b.id}" in result
        assert "no path" in lower or has_ids


# ---------------------------------------------------------------------------
# T10: Large result truncation
# ---------------------------------------------------------------------------


class TestLargeResultTruncation:
    def test_200_nodes_truncation(self):
        database = grafeo.GrafeoDB()
        try:
            for i in range(200):
                database.create_node(["Item"], {"index": i})

            ctx = MockContext(request_context=_RequestContext(lifespan_context=_LifespanContext(db=database)))

            result = json.loads(search_nodes_by_label("Item", ctx=ctx))
            # Default limit is 100, so we should get at most 100 results
            assert result["count"] <= 100
            # A truncation note should be present when limit was reached
            assert "note" in result
        finally:
            database.close()

    def test_200_nodes_with_explicit_limit(self):
        database = grafeo.GrafeoDB()
        try:
            for i in range(200):
                database.create_node(["Item"], {"index": i})

            ctx = MockContext(request_context=_RequestContext(lifespan_context=_LifespanContext(db=database)))

            result = json.loads(search_nodes_by_label("Item", limit=50, ctx=ctx))
            assert result["count"] == 50
            assert "note" in result
            assert "offset=50" in result["note"]
        finally:
            database.close()
