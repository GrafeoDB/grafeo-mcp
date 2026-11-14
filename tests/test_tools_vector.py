"""Tests for tools/vector.py — vector search, index creation, and hybrid search.

Vector operations require creating indexes and embedding data, so these tests
build a small vector dataset from scratch.
"""

from __future__ import annotations

import json

import grafeo
import pytest

from grafeo_mcp.tools._helpers import _node_summary, _truncate
from grafeo_mcp.tools.vector import (
    create_vector_index,
    vector_graph_search,
    vector_search,
)
from tests.conftest import MockContext, _make_ctx

# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_payload(self):
        result = _truncate({"a": 1})
        assert result == '{"a":1}'

    def test_long_payload_truncated(self):
        big = {"data": "x" * 10_000}
        result = _truncate(big, limit=100)
        assert len(result) < 200
        assert "truncated" in result


class TestNodeSummary:
    def test_existing_node(self, db):
        node = db.create_node(["Test"], {"name": "foo"})
        summary = _node_summary(db, node.id)
        assert summary["node_id"] == node.id
        assert "Test" in summary["labels"]

    def test_missing_node(self, db):
        summary = _node_summary(db, 9999)
        assert "error" in summary

    def test_strips_large_vectors(self, db):
        vec = [0.1] * 100
        node = db.create_node(["Doc"], {"name": "doc", "embedding": vec})
        summary = _node_summary(db, node.id)
        # embedding should be stripped (len > 32)
        assert "embedding" not in summary["properties"]
        assert summary["properties"]["name"] == "doc"


# ---------------------------------------------------------------------------
# Fixtures with vector data
# ---------------------------------------------------------------------------


@pytest.fixture()
def vector_db():
    """DB with nodes containing 4-dimensional vectors and an HNSW index."""
    database = grafeo.GrafeoDB()

    # Create nodes with simple 4D vectors for testing
    vecs = [
        ([1.0, 0.0, 0.0, 0.0], "alpha"),
        ([0.9, 0.1, 0.0, 0.0], "beta"),
        ([0.0, 0.0, 1.0, 0.0], "gamma"),
        ([0.0, 0.0, 0.9, 0.1], "delta"),
        ([0.5, 0.5, 0.5, 0.5], "epsilon"),
    ]
    for vec, name in vecs:
        database.create_node(["Doc"], {"name": name, "emb": vec})

    # Create the HNSW index
    database.create_vector_index("Doc", "emb", 4, "cosine")

    yield database
    database.close()


@pytest.fixture()
def vector_ctx(vector_db) -> MockContext:
    return _make_ctx(vector_db)


# ---------------------------------------------------------------------------
# create_vector_index
# ---------------------------------------------------------------------------


class TestCreateVectorIndex:
    def test_basic(self, ctx):
        # Create some data first
        ctx.request_context.lifespan_context.db.create_node(["Item"], {"vec": [1.0, 2.0, 3.0]})
        result = create_vector_index("Item", "vec", 3, "cosine", ctx=ctx)
        assert "index created" in result.lower()

    def test_with_params(self, ctx):
        ctx.request_context.lifespan_context.db.create_node(["Item"], {"vec": [1.0, 2.0, 3.0]})
        result = create_vector_index("Item", "vec", 3, "euclidean", m=32, ef_construction=200, ctx=ctx)
        assert "index created" in result.lower()
        assert "m=32" in result
        assert "ef_construction=200" in result


# ---------------------------------------------------------------------------
# vector_search
# ---------------------------------------------------------------------------


class TestVectorSearch:
    def test_basic(self, vector_ctx):
        result = json.loads(vector_search("Doc", "emb", [1.0, 0.0, 0.0, 0.0], k=3, ctx=vector_ctx))
        assert len(result) >= 1
        # alpha should be nearest to [1,0,0,0]
        assert result[0]["properties"]["name"] == "alpha"

    def test_k_limit(self, vector_ctx):
        result = json.loads(vector_search("Doc", "emb", [1.0, 0.0, 0.0, 0.0], k=2, ctx=vector_ctx))
        assert len(result) <= 2

    def test_similarity_ordering(self, vector_ctx):
        result = json.loads(vector_search("Doc", "emb", [0.0, 0.0, 1.0, 0.0], k=5, ctx=vector_ctx))
        # gamma [0,0,1,0] should be most similar to query [0,0,1,0]
        assert result[0]["properties"]["name"] == "gamma"
        # Distances should be ascending
        for i in range(len(result) - 1):
            assert result[i]["distance"] <= result[i + 1]["distance"]

    def test_no_index_returns_error(self, ctx):
        result = vector_search("Missing", "vec", [1.0, 2.0], k=5, ctx=ctx)
        assert "error" in result.lower()


# ---------------------------------------------------------------------------
# vector_graph_search
# ---------------------------------------------------------------------------


class TestVectorGraphSearch:
    def test_seeds_returned(self, vector_ctx):
        result = json.loads(
            vector_graph_search("Doc", "emb", [1.0, 0.0, 0.0, 0.0], k=2, expand_depth=0, ctx=vector_ctx)
        )
        assert "seeds" in result
        assert result["seed_count"] >= 1

    def test_expand_depth_zero(self, vector_ctx):
        result = json.loads(
            vector_graph_search("Doc", "emb", [1.0, 0.0, 0.0, 0.0], k=2, expand_depth=0, ctx=vector_ctx)
        )
        # No expansion — neighbors should be empty
        assert result["neighbor_count"] == 0


# ---------------------------------------------------------------------------
# Query vector checks (a wrong size used to crash the whole server)
# ---------------------------------------------------------------------------


class TestQueryVectorChecks:
    # grafeo 0.6 refuses a query vector of the wrong size, an empty one and
    # one with NaN with an error (0.5.x panicked on a wrong size, so the tools
    # compared it with a stored vector first). The tools pass the engine's
    # message on, which names both sizes.

    def test_dimension_mismatch_is_an_error(self, vector_ctx):
        result = vector_search("Doc", "emb", [1.0, 0.0], k=3, ctx=vector_ctx)
        assert result.startswith("Error: vector_search: ")
        assert "2 dimensions" in result and "expects 4" in result
        assert "embed it with the model" in result, "the hint says how to get a vector of the right size"

    def test_dimension_mismatch_in_hybrid_and_mmr(self, vector_ctx):
        from grafeo_mcp.tools.vector import mmr_search

        assert vector_graph_search("Doc", "emb", [1.0], ctx=vector_ctx).startswith("Error: vector_graph_search:")
        assert mmr_search("Doc", "emb", [1.0], ctx=vector_ctx).startswith("Error: mmr_search:")

    def test_empty_query_vector(self, vector_ctx):
        result = vector_search("Doc", "emb", [], ctx=vector_ctx)
        assert result.startswith("Error: vector_search: ") and "0 dimensions" in result

    def test_non_finite_query_vector(self, vector_ctx):
        result = vector_search("Doc", "emb", [float("nan"), 0.0, 0.0, 0.0], ctx=vector_ctx)
        assert result.startswith("Error: vector_search: ") and "NaN" in result

    def test_mismatch_without_stored_vectors_in_view(self, ctx):
        # The 0.5.x workaround sampled 20 nodes for a stored vector and could
        # miss it; the engine checks against the index itself.
        db = ctx.request_context.lifespan_context.db
        for i in range(25):
            db.create_node(["Doc"], {"i": i})
        db.create_node(["Doc"], {"emb": [1.0, 0.0, 0.0]})
        db.create_vector_index("Doc", "emb", 3, "cosine")
        result = vector_search("Doc", "emb", [1.0, 0.0], k=3, ctx=ctx)
        assert result.startswith("Error: vector_search: ") and "expects 3" in result
        assert json.loads(vector_search("Doc", "emb", [1.0, 0.0, 0.0], k=1, ctx=ctx))[0]["node_id"] == 25

    def test_k_must_be_positive(self, vector_ctx):
        assert "k must be at least 1" in vector_search("Doc", "emb", [1.0, 0.0, 0.0, 0.0], k=0, ctx=vector_ctx)


# ---------------------------------------------------------------------------
# vector_graph_search expansion
# ---------------------------------------------------------------------------


@pytest.fixture()
def chain_ctx():
    """seed -CITES-> a -CITES-> b, and seed -MENTIONS-> c."""
    database = grafeo.GrafeoDB()
    seed = database.create_node(["Doc"], {"name": "seed", "emb": [1.0, 0.0]})
    a = database.create_node(["Doc"], {"name": "a"})
    b = database.create_node(["Doc"], {"name": "b"})
    c = database.create_node(["Doc"], {"name": "c"})
    database.create_edge(seed.id, a.id, "CITES")
    database.create_edge(a.id, b.id, "CITES")
    database.create_edge(seed.id, c.id, "MENTIONS")
    database.create_vector_index("Doc", "emb", 2, "cosine")
    yield _make_ctx(database)
    database.close()


class TestVectorGraphExpansion:
    def test_two_hops(self, chain_ctx):
        result = json.loads(vector_graph_search("Doc", "emb", [1.0, 0.0], k=1, expand_depth=2, ctx=chain_ctx))
        hops = {n["properties"]["name"]: n["hop"] for n in result["neighbors"]}
        assert hops == {"a": 1, "c": 1, "b": 2}

    def test_edge_type_filter(self, chain_ctx):
        result = json.loads(
            vector_graph_search("Doc", "emb", [1.0, 0.0], k=1, expand_depth=2, expand_edge_type="CITES", ctx=chain_ctx)
        )
        assert sorted(n["properties"]["name"] for n in result["neighbors"]) == ["a", "b"]

    def test_edge_type_is_a_value_not_query_text(self, chain_ctx):
        injected = "CITES]-(b) DETACH DELETE b WITH b MATCH (a)-[r"
        result = json.loads(
            vector_graph_search("Doc", "emb", [1.0, 0.0], k=1, expand_edge_type=injected, ctx=chain_ctx)
        )
        assert result["neighbor_count"] == 0
        assert chain_ctx.request_context.lifespan_context.db.node_count == 4
