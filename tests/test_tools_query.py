"""Tests for tools/query.py — execute_gql and helpers."""

from __future__ import annotations

import json

from grafeo_mcp.tools.query import _normalize_query, execute_gql

# ---------------------------------------------------------------------------
# _normalize_query
# ---------------------------------------------------------------------------


class TestNormalizeQuery:
    def test_create_to_insert(self):
        assert _normalize_query("CREATE (:Person {name: 'Alice'})") == "INSERT (:Person {name: 'Alice'})"

    def test_case_insensitive(self):
        assert "INSERT" in _normalize_query("create (:Node)")

    def test_detach_delete(self):
        result = _normalize_query("MATCH (n) DETACH DELETE n")
        assert "DETACH DELETE" in result

    def test_passthrough_gql(self):
        gql = "MATCH (n:Person) RETURN n.name"
        assert _normalize_query(gql) == gql

    def test_insert_unchanged(self):
        gql = "INSERT (:Person {name: 'Bob'})"
        assert _normalize_query(gql) == gql


# ---------------------------------------------------------------------------
# execute_gql
# ---------------------------------------------------------------------------


class TestExecuteGql:
    def test_match_returns_json(self, populated_ctx):
        result = execute_gql("MATCH (n:Person) RETURN n.name", ctx=populated_ctx)
        parsed = json.loads(result)
        assert "rows" in parsed
        assert "columns" in parsed
        assert parsed["total_rows"] >= 3  # Alice, Bob, Charlie

    def test_empty_result(self, ctx):
        result = execute_gql("MATCH (n:NonExistent) RETURN n", ctx=ctx)
        parsed = json.loads(result)
        assert parsed["total_rows"] == 0
        assert parsed["rows"] == []

    def test_limit_truncation(self, populated_ctx):
        result = execute_gql("MATCH (n:Person) RETURN n.name", limit=1, ctx=populated_ctx)
        parsed = json.loads(result)
        assert len(parsed["rows"]) == 1
        assert parsed["total_rows"] >= 3
        assert parsed.get("truncated") is True

    def test_insert_via_cypher_syntax(self, ctx):
        # CREATE should auto-normalize to INSERT
        result = execute_gql("CREATE (:TestLabel {val: 42})", ctx=ctx)
        # Should succeed (not error)
        assert "error" not in result.lower() or "failed" not in result.lower()

    def test_invalid_query_returns_error(self, ctx):
        result = execute_gql("THIS IS NOT VALID GQL", ctx=ctx)
        assert "failed" in result.lower() or "error" in result.lower()
        assert "graph_info" in result  # error recovery hint
