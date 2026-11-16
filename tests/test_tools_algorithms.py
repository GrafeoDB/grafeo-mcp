"""Tests for tools/algorithms.py — graph analytics."""

from __future__ import annotations

import json

import pytest

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


# ---------------------------------------------------------------------------
# The graph of the real-model agent test: Alice-WORKS_AT->Acme<-WORKS_AT-Bob-KNOWS->Carol,
# Carol-WORKS_AT->Globex<-WORKS_AT-Dave-KNOWS->Alice. No directed path leads from Alice to Carol.
# ---------------------------------------------------------------------------


@pytest.fixture()
def office_ctx(ctx):
    db = ctx.request_context.lifespan_context.db
    db.execute(
        "INSERT (alice:Person {name: 'Alice', age: 34}), (bob:Person {name: 'Bob', age: 41}), "
        "(carol:Person {name: 'Carol', age: 29}), (dave:Person {name: 'Dave', age: 52}), "
        "(acme:Company {name: 'Acme', city: 'Lyon'}), (globex:Company {name: 'Globex', city: 'Rotterdam'}), "
        "(alice)-[:WORKS_AT]->(acme), (bob)-[:WORKS_AT]->(acme), (bob)-[:KNOWS]->(carol), "
        "(carol)-[:WORKS_AT]->(globex), (dave)-[:WORKS_AT]->(globex), (dave)-[:KNOWS]->(alice)"
    )
    ids = {row["name"]: row["id"] for row in db.execute("MATCH (n) RETURN n.name AS name, id(n) AS id")}
    return ctx, ids


def _names(result: str) -> list[str]:
    return [node["properties"]["name"] for node in json.loads(result)["path"]]


class TestDijkstraDirection:
    def test_default_ignores_edge_direction(self, office_ctx):
        ctx, ids = office_ctx
        result = json.loads(dijkstra(ids["Alice"], ids["Carol"], ctx=ctx))
        assert result["direction"] == "both" and result["hop_count"] == 3
        assert [n["properties"]["name"] for n in result["path"]] in (
            ["Alice", "Acme", "Bob", "Carol"],
            ["Alice", "Dave", "Globex", "Carol"],
        )

    def test_outgoing_without_a_directed_path_says_how_to_ignore_direction(self, office_ctx):
        ctx, ids = office_ctx
        result = dijkstra(ids["Alice"], ids["Carol"], direction="outgoing", ctx=ctx)
        assert result.startswith(f"Error: dijkstra: no path found from node {ids['Alice']} to node {ids['Carol']}.")
        assert 'direction="both"' in result

    def test_outgoing_follows_edges(self, office_ctx):
        ctx, ids = office_ctx
        assert _names(dijkstra(ids["Dave"], ids["Acme"], direction="outgoing", ctx=ctx)) == ["Dave", "Alice", "Acme"]

    def test_incoming_walks_edges_backwards(self, office_ctx):
        ctx, ids = office_ctx
        assert _names(dijkstra(ids["Acme"], ids["Dave"], direction="incoming", ctx=ctx)) == ["Acme", "Alice", "Dave"]
        assert dijkstra(ids["Dave"], ids["Acme"], direction="incoming", ctx=ctx).startswith("Error: dijkstra: no path")

    def test_unconnected_nodes_point_to_connected_components(self, ctx):
        db = ctx.request_context.lifespan_context.db
        a, b = db.create_node(["N"]), db.create_node(["N"])
        assert "connected_components" in dijkstra(a.id, b.id, ctx=ctx)

    def test_unknown_direction(self, office_ctx):
        ctx, ids = office_ctx
        result = dijkstra(ids["Alice"], ids["Carol"], direction="undirected", ctx=ctx)
        assert result == "Error: dijkstra: direction must be 'both', 'outgoing' or 'incoming', got 'undirected'."

    def test_weights_in_both_directions(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.execute("INSERT (a:P {n: 'a'})<-[:R {w: 1}]-(b:P {n: 'b'})-[:R {w: 0.5}]->(c:P {n: 'c'})")
        db.execute("MATCH (a:P {n: 'a'}), (c:P {n: 'c'}) INSERT (c)-[:R {w: 5}]->(a)")
        result = json.loads(dijkstra(0, 2, weight_property="w", ctx=ctx))
        assert result["distance"] == 1.5 and [n["properties"]["n"] for n in result["path"]] == ["a", "b", "c"]

    @pytest.mark.parametrize("bad", ["'heavy'", "-1", "true"])
    def test_bad_weights_are_errors_in_both_directions(self, ctx, bad):
        db = ctx.request_context.lifespan_context.db
        db.execute(f"INSERT (:P)-[:R {{w: {bad}}}]->(:P)")
        result = dijkstra(1, 0, weight_property="w", ctx=ctx)
        assert result.startswith("Error: dijkstra: the weight 'w' of edge 0 is"), result


class TestRankingLabel:
    @pytest.mark.parametrize("tool", [pagerank, betweenness_centrality])
    def test_label_keeps_only_that_label_and_scores_the_whole_graph(self, office_ctx, tool):
        ctx, _ = office_ctx
        everything = json.loads(tool(ctx=ctx))
        people = json.loads(tool(label="Person", ctx=ctx))
        assert people["label"] == "Person"
        assert people["total_nodes_scored"] == everything["total_nodes_scored"] == 6
        assert people["results"] and all(node["labels"] == ["Person"] for node in people["results"])
        ranked_people = [n["node_id"] for n in everything["results"] if n["labels"] == ["Person"]]
        assert [n["node_id"] for n in people["results"]] == ranked_people  # same order, ranks stay graph-wide

    def test_label_with_top_k(self, office_ctx):
        ctx, _ = office_ctx
        (top,) = json.loads(pagerank(label="Person", top_k=1, ctx=ctx))["results"]
        assert top["labels"] == ["Person"]

    @pytest.mark.parametrize("tool", [pagerank, betweenness_centrality])
    def test_unknown_label(self, office_ctx, tool):
        ctx, _ = office_ctx
        result = tool(label="person", ctx=ctx)
        assert result.startswith(f"Error: {tool.__name__}: no node has the label 'person'. Hint: graph_info")
