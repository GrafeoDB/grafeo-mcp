"""Tests for read-only mode — verify mutations are blocked, reads allowed."""

from __future__ import annotations

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
    get_node,
    graph_info,
    search_nodes_by_label,
    update_edge,
    update_node,
)
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
