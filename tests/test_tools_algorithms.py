"""Tests for tools/algorithms.py — graph analytics."""

from __future__ import annotations

import json

from grafeo_mcp.tools.algorithms import (
    betweenness_centrality,
    connected_components,
    dijkstra,
    louvain,
    pagerank,
)

# ---------------------------------------------------------------------------
# pagerank
# ---------------------------------------------------------------------------


class TestPageRank:
    def test_basic(self, populated_ctx):
        result = json.loads(pagerank(ctx=populated_ctx))
        assert result["algorithm"] == "pagerank"
        assert result["total_nodes_scored"] == 5
        assert len(result["results"]) > 0

    def test_top_k(self, populated_ctx):
        result = json.loads(pagerank(top_k=2, ctx=populated_ctx))
        assert result["top_k"] <= 2

    def test_scores_are_positive(self, populated_ctx):
        result = json.loads(pagerank(ctx=populated_ctx))
        for entry in result["results"]:
            assert entry["score"] > 0

    def test_empty_graph_error(self, ctx):
        result = pagerank(ctx=ctx)
        # Empty graph — should either return empty results or an error
        assert "error" in result.lower() or '"results":[]' in result or '"total_nodes_scored":0' in result


# ---------------------------------------------------------------------------
# dijkstra
# ---------------------------------------------------------------------------


class TestDijkstra:
    def test_path_exists(self, populated_ctx):
        # Alice (0) -> Bob (1) via KNOWS
        result = json.loads(dijkstra(0, 1, ctx=populated_ctx))
        assert result["algorithm"] == "dijkstra"
        assert result["distance"] >= 1.0
        assert len(result["path"]) >= 2

    def test_longer_path(self, populated_ctx):
        # Alice (0) -> Charlie (2) via Alice->Bob->Charlie
        result = json.loads(dijkstra(0, 2, ctx=populated_ctx))
        assert result["hop_count"] >= 1

    def test_no_path(self, ctx):
        # Create two disconnected nodes
        db = ctx.request_context.lifespan_context.db
        db.create_node(["A"])
        db.create_node(["B"])
        result = dijkstra(0, 1, ctx=ctx)
        assert "no path" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# louvain
# ---------------------------------------------------------------------------


class TestLouvain:
    def test_basic(self, populated_ctx):
        result = json.loads(louvain(ctx=populated_ctx))
        assert result["algorithm"] == "louvain"
        assert "modularity" in result
        assert result["num_communities"] >= 1
        assert "communities" in result

    def test_empty_graph(self, ctx):
        result = louvain(ctx=ctx)
        assert "error" in result.lower() or "communities" in result.lower()


# ---------------------------------------------------------------------------
# betweenness_centrality
# ---------------------------------------------------------------------------


class TestBetweennessCentrality:
    def test_basic(self, populated_ctx):
        result = json.loads(betweenness_centrality(ctx=populated_ctx))
        assert result["algorithm"] == "betweenness_centrality"
        assert result["total_nodes_scored"] == 5
        assert len(result["results"]) > 0

    def test_top_k(self, populated_ctx):
        result = json.loads(betweenness_centrality(top_k=2, ctx=populated_ctx))
        assert result["top_k"] <= 2


# ---------------------------------------------------------------------------
# connected_components
# ---------------------------------------------------------------------------


class TestConnectedComponents:
    def test_single_component(self, populated_ctx):
        result = json.loads(connected_components(ctx=populated_ctx))
        assert result["algorithm"] == "connected_components"
        # The test graph is fully connected
        assert result["num_components"] == 1

    def test_disconnected(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.create_node(["A"])
        db.create_node(["B"])
        result = json.loads(connected_components(ctx=ctx))
        assert result["num_components"] == 2
