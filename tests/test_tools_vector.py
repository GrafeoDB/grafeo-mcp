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
