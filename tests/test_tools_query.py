"""Tests for tools/query.py: execute_gql."""

from __future__ import annotations

import json

import pytest

from grafeo_mcp.tools.query import execute_gql

# ---------------------------------------------------------------------------
# Query text is passed to the engine unchanged
# ---------------------------------------------------------------------------


class TestQueryPassthrough:
    """Regression tests: execute_gql used to rewrite every CREATE to INSERT with a
    regex, which also rewrote string literals and broke GQL DDL such as
    CREATE GRAPH. The engine accepts Cypher-style CREATE itself."""

    def test_string_literal_with_create_is_not_rewritten(self, populated_ctx):
        result = json.loads(
            execute_gql("MATCH (n:Person) WHERE n.name = 'Alice' RETURN 'CREATE' AS s", ctx=populated_ctx)
        )
        assert result["rows"] == [{"s": "CREATE"}]

    def test_property_filter_on_create_value(self, ctx):
        execute_gql("INSERT (:Action {kind: 'CREATE'})", ctx=ctx)
        result = json.loads(execute_gql("MATCH (a:Action) WHERE a.kind = 'CREATE' RETURN count(a) AS c", ctx=ctx))
        assert result["rows"] == [{"c": 1}]

    def test_create_graph_ddl_runs(self, ctx):
        result = execute_gql("CREATE GRAPH analytics", ctx=ctx)
        assert not result.startswith("Error"), result
        assert "analytics" in ctx.request_context.lifespan_context.db.list_graphs()

    def test_cypher_create_runs_natively(self, ctx):
        result = json.loads(execute_gql("CREATE (:Person {name: 'Alice'})", ctx=ctx))
        assert result["counters"]["nodes_created"] == 1


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
        result = json.loads(execute_gql("CREATE (:TestLabel {val: 42})", ctx=ctx))
        assert result["counters"]["nodes_created"] == 1

    def test_invalid_query_returns_error(self, ctx):
        result = execute_gql("THIS IS NOT VALID GQL", ctx=ctx)
        assert result.startswith("Error: execute_gql: query failed: ")
        assert "graph_info" in result  # error recovery hint

    def test_read_query_has_no_counters(self, populated_ctx):
        result = json.loads(execute_gql("MATCH (n:Person) RETURN n.name", ctx=populated_ctx))
        assert "counters" not in result

    def test_write_query_reports_counters(self, populated_ctx):
        result = json.loads(
            execute_gql("MATCH (p:Person {name: 'Alice'}) SET p.age = 31, p.city = 'Utrecht'", ctx=populated_ctx)
        )
        assert result["counters"]["properties_set"] == 2

    def test_write_matching_nothing_reports_zero_counters(self, ctx):
        result = json.loads(execute_gql("MATCH (n) WHERE id(n) = 999 DETACH DELETE n", ctx=ctx))
        assert result["counters"]["nodes_deleted"] == 0

    def test_limit_must_be_positive(self, ctx):
        result = execute_gql("MATCH (n) RETURN n", limit=0, ctx=ctx)
        assert result.startswith("Error: execute_gql: limit must be at least 1")

    def test_trailing_semicolon_is_fine(self, populated_ctx):
        result = json.loads(execute_gql("MATCH (n:Person) RETURN count(n) AS c;", ctx=populated_ctx))
        assert result["rows"] == [{"c": 3}]


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


class TestParams:
    def test_params_are_bound(self, populated_ctx):
        result = json.loads(
            execute_gql(
                "MATCH (p:Person) WHERE p.age > $min RETURN p.name AS name ORDER BY name",
                params={"min": 26},
                ctx=populated_ctx,
            )
        )
        assert [row["name"] for row in result["rows"]] == ["Alice", "Charlie"]

    def test_params_keep_values_out_of_query_text(self, ctx):
        tricky = "x'}) DETACH DELETE n //"
        result = json.loads(execute_gql("INSERT (:Note {text: $text})", params={"text": tricky}, ctx=ctx))
        assert result["counters"]["nodes_created"] == 1
        rows = json.loads(execute_gql("MATCH (n:Note) RETURN n.text AS t", ctx=ctx))["rows"]
        assert rows == [{"t": tricky}]

    def test_missing_parameter_is_named(self, ctx):
        result = execute_gql("MATCH (n) WHERE n.name = $name RETURN n", ctx=ctx)
        assert result.startswith("Error: execute_gql: the query uses $name")
        assert "params" in result

    def test_partially_supplied_parameters(self, ctx):
        result = execute_gql("MATCH (n) WHERE n.a = $a AND n.b = $b RETURN n", params={"a": 1}, ctx=ctx)
        assert "$b" in result
        assert "$a" not in result

    def test_merge_upsert_with_params(self, ctx):
        query = "MERGE (p:Person {name: $name}) SET p += $props RETURN id(p) AS id"
        first = json.loads(execute_gql(query, params={"name": "Ada", "props": {"age": 36}}, ctx=ctx))
        second = json.loads(execute_gql(query, params={"name": "Ada", "props": {"age": 37}}, ctx=ctx))
        assert first["counters"]["nodes_created"] == 1
        assert second["counters"]["nodes_created"] == 0
        assert first["rows"][0]["id"] == second["rows"][0]["id"]
        rows = json.loads(execute_gql("MATCH (p:Person) RETURN p.age AS age", ctx=ctx))["rows"]
        assert rows == [{"age": 37}]


# ---------------------------------------------------------------------------
# One statement per call
# ---------------------------------------------------------------------------


class TestMultipleStatements:
    def test_two_statements_are_refused_before_running(self, ctx):
        result = execute_gql("INSERT (:A); INSERT (:B)", ctx=ctx)
        assert result.startswith("Error: execute_gql: the query holds 2 statements")
        assert "separate" in result
        # Nothing ran: the check happens before the engine sees the text.
        assert ctx.request_context.lifespan_context.db.node_count == 0

    def test_semicolon_inside_string_is_not_a_separator(self, ctx):
        result = json.loads(execute_gql("INSERT (:Note {text: 'a; b'})", ctx=ctx))
        assert result["counters"]["nodes_created"] == 1

    def test_empty_query(self, ctx):
        result = execute_gql("   ;  ", ctx=ctx)
        assert result.startswith("Error: execute_gql: the query is empty")

    def test_chained_inserts_run_in_one_statement(self, ctx):
        result = json.loads(execute_gql("INSERT (:A {v: 1}) INSERT (:B {v: 2})", ctx=ctx))
        assert result["counters"]["nodes_created"] == 2


# ---------------------------------------------------------------------------
# Cypher-style syntax accepted by the engine
# ---------------------------------------------------------------------------


class TestCypherSyntax:
    """grafeo 0.5.44 accepts these Cypher forms in GQL. These tests used to
    accept either a result or an error; the engine now runs all of them."""

    def test_match_passthrough(self, populated_ctx):
        result = execute_gql("MATCH (n:Person) RETURN n.name", ctx=populated_ctx)
        parsed = json.loads(result)
        assert parsed["total_rows"] == 3

    def test_merge_is_idempotent(self, ctx):
        first = json.loads(execute_gql("MERGE (n:Foo {name: 'bar'})", ctx=ctx))
        second = json.loads(execute_gql("MERGE (n:Foo {name: 'bar'})", ctx=ctx))
        assert first["counters"]["nodes_created"] == 1
        assert second["counters"]["nodes_created"] == 0

    def test_optional_match_returns_null_row(self, ctx):
        result = json.loads(execute_gql("OPTIONAL MATCH (n)-->(m) RETURN n, m", ctx=ctx))
        assert result["rows"] == [{"n": None, "m": None}]

    def test_with_clause(self, populated_ctx):
        result = json.loads(
            execute_gql("MATCH (n:Person) WITH n.name AS name RETURN name ORDER BY name", ctx=populated_ctx)
        )
        assert [row["name"] for row in result["rows"]] == ["Alice", "Bob", "Charlie"]

    @pytest.mark.parametrize(
        "query",
        [
            pytest.param("MATCH (n) WITH n.name RETURN 1", id="unaliased-with"),
            pytest.param("CALL nosuch.procedure()", id="unknown-procedure"),
            pytest.param("MATCH (a) WITH 1 AS x RETURN a.name", id="variable-dropped-by-with"),
        ],
    )
    def test_queries_the_engine_now_rejects_give_errors(self, populated_ctx, query):
        result = execute_gql(query, ctx=populated_ctx)
        assert result.startswith("Error: execute_gql: query failed: ")
