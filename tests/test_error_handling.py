"""Tests for error handling — verify helpful messages, not stack traces (T1-T5, T11)."""

from __future__ import annotations

import json

from grafeo_mcp.tools.graph import (
    create_edge,
    create_node,
    delete_node,
    get_neighbors,
    update_node,
)
from grafeo_mcp.tools.query import execute_gql

# ---------------------------------------------------------------------------
# T1: Malformed GQL syntax
# ---------------------------------------------------------------------------


class TestMalformedGql:
    def test_broken_syntax_returns_error(self, ctx):
        result = execute_gql("SLECT * FORM nodes", ctx=ctx)
        assert "failed" in result.lower() or "error" in result.lower()

    def test_error_includes_recovery_hint(self, ctx):
        result = execute_gql("SLECT * FORM nodes", ctx=ctx)
        # Error messages should include a recovery hint mentioning graph_info
        assert "graph_info" in result

    def test_no_python_traceback(self, ctx):
        result = execute_gql("SLECT * FORM nodes", ctx=ctx)
        assert "Traceback" not in result
        assert "File " not in result


# ---------------------------------------------------------------------------
# T2: Create edge with non-existent source/target nodes
# ---------------------------------------------------------------------------


class TestCreateEdgeNonExistentNodes:
    def test_dangling_edge_succeeds(self, ctx):
        # GrafeoDB allows dangling edges, so creating an edge to
        # non-existent nodes should succeed (returns valid JSON)
        result = create_edge(9999, 8888, "GHOST", ctx=ctx)
        parsed = json.loads(result)
        assert parsed["edge_type"] == "GHOST"
        assert parsed["source_id"] == 9999
        assert parsed["target_id"] == 8888


# ---------------------------------------------------------------------------
# T3: Duplicate node creation
# ---------------------------------------------------------------------------


class TestDuplicateNodeCreation:
    def test_same_properties_creates_two_nodes(self, ctx):
        result1 = json.loads(create_node(["Person"], {"name": "Alice"}, ctx=ctx))
        result2 = json.loads(create_node(["Person"], {"name": "Alice"}, ctx=ctx))
        # GrafeoDB assigns unique IDs, so two distinct nodes are created
        assert result1["id"] != result2["id"]
        assert result1["labels"] == result2["labels"]
        assert result1["properties"]["name"] == result2["properties"]["name"]


# ---------------------------------------------------------------------------
# T4: Update non-existent node
# ---------------------------------------------------------------------------


class TestUpdateNonExistentNode:
    def test_returns_not_found(self, ctx):
        result = update_node(9999, {"x": 1}, ctx=ctx)
        assert "not found" in result.lower()

    def test_error_includes_node_id(self, ctx):
        result = update_node(9999, {"x": 1}, ctx=ctx)
        assert "9999" in result

    def test_no_python_traceback(self, ctx):
        result = update_node(9999, {"x": 1}, ctx=ctx)
        assert "Traceback" not in result


# ---------------------------------------------------------------------------
# T5: Delete non-existent node
# ---------------------------------------------------------------------------


class TestDeleteNonExistentNode:
    def test_returns_not_found(self, ctx):
        result = delete_node(9999, ctx=ctx)
        assert "not found" in result.lower()

    def test_graceful_no_crash(self, ctx):
        # Should return a string, not raise an exception
        result = delete_node(9999, ctx=ctx)
        assert isinstance(result, str)

    def test_error_includes_node_id(self, ctx):
        result = delete_node(9999, ctx=ctx)
        assert "9999" in result


# ---------------------------------------------------------------------------
# T11: get_neighbors with invalid direction
# ---------------------------------------------------------------------------


class TestInvalidDirection:
    def test_invalid_direction_returns_error_or_falls_through(self, populated_ctx):
        # The current implementation uses an if/elif/else chain where
        # invalid direction values fall through to the "both" branch.
        # Verify this does not crash.
        result = get_neighbors(0, direction="sideways", ctx=populated_ctx)
        # Either returns valid JSON (fell through to "both") or an error
        try:
            parsed = json.loads(result)
            # If it parsed, the fallback to "both" worked
            assert "neighbors" in parsed
        except json.JSONDecodeError:
            # If it did not parse, it should be an error string
            assert "error" in result.lower() or "failed" in result.lower()
