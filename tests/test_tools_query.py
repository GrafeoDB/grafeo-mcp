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


# ---------------------------------------------------------------------------
# A read that finds nothing says which names do not exist
# ---------------------------------------------------------------------------


class TestNamesHint:
    def _run(self, query, ctx):
        return json.loads(execute_gql(query, ctx=ctx))

    def test_misspelled_label(self, populated_ctx):
        result = self._run("MATCH (n:Persn) RETURN n.name", populated_ctx)
        assert result["rows"] == []
        assert result["hint"] == "Not in the graph: label :Persn (did you mean :Person?)."

    def test_label_in_the_wrong_case(self, populated_ctx):
        result = self._run("MATCH (n:person) RETURN n", populated_ctx)
        assert result["hint"] == "Not in the graph: label :person (did you mean :Person?)."

    def test_unknown_edge_type_lists_the_few_that_exist(self, populated_ctx):
        result = self._run("MATCH (a)-[:FRIEND_OF]->(b) RETURN a", populated_ctx)
        assert result["hint"] == "Not in the graph: edge type :FRIEND_OF (there are: :KNOWS, :WORKS_AT)."

    def test_misspelled_property_in_a_filter(self, populated_ctx):
        result = self._run("MATCH (n:Person) WHERE n.nmae = 'Alice' RETURN n", populated_ctx)
        assert result["hint"] == "Not in the graph: property nmae (did you mean name?)."

    def test_misspelled_property_that_returns_only_nulls(self, populated_ctx):
        result = self._run("MATCH (n:Person) RETURN n.nmae AS x", populated_ctx)
        assert result["total_rows"] == 3
        assert result["hint"] == "Not in the graph: property nmae (did you mean name?)."

    def test_empty_graph(self, ctx):
        assert self._run("MATCH (n:Person) RETURN n", ctx)["hint"] == "The graph has no nodes yet."

    @pytest.mark.parametrize(
        "query",
        [
            "MATCH (n:Person) RETURN n.name",  # rows with values
            "MATCH (n:Person) WHERE n.name = 'Nobody' RETURN n",  # empty, but every name exists
            "MATCH (n:Person) RETURN n.missing_on_purpose IS NULL AS x",  # a boolean column, never null
        ],
    )
    def test_no_hint_when_the_names_exist(self, populated_ctx, query):
        assert "hint" not in self._run(query, populated_ctx)

    def test_no_hint_for_writes(self, populated_ctx):
        result = self._run("MATCH (n:Persn) SET n.x = 1", populated_ctx)
        assert "hint" not in result


class TestErrorHints:
    """The hint follows the engine's error code: syntax, names and types, or a value at run time."""

    @pytest.mark.parametrize(
        ("query", "code", "hint"),
        [
            ("MATC (n) RETURN n", "GRAFEO-Q001", "check the query syntax"),
            ("MATCH (n) RETURN m", "GRAFEO-Q002", "fix what the message points at"),
            ("RETURN 1/0", "GRAFEO-Q006", "the query is valid but a value broke it while running"),
        ],
    )
    def test_hint_by_code(self, ctx, query, code, hint):
        result = execute_gql(query, ctx=ctx)
        assert result.startswith(f"Error: execute_gql: query failed: {code}"), result
        assert f"Hint: {hint}" in result


class TestPatternInWhere:
    """Cypher lets WHERE test a path directly; GQL needs EXISTS { ... }. The hint says so."""

    @pytest.mark.parametrize(
        "query",
        [
            "MATCH (p:Person) WHERE p.age > 30 AND (p)-[:WORKS_AT]->(:Company {industry: 'Technology'}) RETURN p.name",
            "MATCH (p:Person) WHERE (p)-[:KNOWS]->() RETURN p.name",
            "MATCH (p:Person)\nWHERE NOT (p)-->(:Company)\nRETURN p.name",
            "MATCH (c:Company) WHERE (c)<-[:WORKS_AT]-(:Person) RETURN c.name",
            "MATCH (p:Person) WHERE (p)--(:Company) RETURN p.name",
        ],
    )
    def test_pattern_in_where_gets_the_exists_hint(self, populated_ctx, query):
        result = execute_gql(query, ctx=populated_ctx)
        assert result.startswith("Error: execute_gql: query failed: GRAFEO-Q001"), result
        assert "Hint: a path pattern in WHERE needs EXISTS" in result

    @pytest.mark.parametrize(
        "query",
        ["MATC (n) RETURN n", "MATCH (p:Person)-[:KNOWS RETURN p", "MATCH (p)-[:KNOWS]-> RETURN p"],
    )
    def test_other_syntax_errors_keep_the_syntax_hint(self, populated_ctx, query):
        assert "Hint: check the query syntax" in execute_gql(query, ctx=populated_ctx)

    def test_the_hinted_forms_run(self, populated_ctx):
        exists = "MATCH (p:Person) WHERE p.age > 26 AND EXISTS { (p)-[:WORKS_AT]->(:Company {name: 'Acme'}) } "
        in_match = "MATCH (p:Person)-[:WORKS_AT]->(:Company {name: 'Acme'}) WHERE p.age > 26 "
        for query in (exists, in_match):
            rows = json.loads(execute_gql(query + "RETURN p.name AS name", ctx=populated_ctx))["rows"]
            assert rows == [{"name": "Alice"}], query


class TestPatternInDelete:
    """DELETE takes variables; a path pattern after it gets a hint saying how to bind the edge."""

    @pytest.mark.parametrize(
        "query",
        [
            "MATCH (b:Person {name: 'Bob'})-[:WORKS_AT]->(c:Company) DELETE (b)-[:WORKS_AT]->(c) RETURN b, c",
            "MATCH (b:Person)-[:KNOWS]->(c) DELETE (b)-[r]->(c)",
            "MATCH (b:Person)-[:KNOWS]->(c) DETACH DELETE b-[r]->c",
        ],
    )
    def test_pattern_after_delete_gets_the_variable_hint(self, populated_ctx, query):
        result = execute_gql(query, ctx=populated_ctx)
        assert result.startswith("Error: execute_gql: query failed: GRAFEO-Q001"), result
        assert "Hint: DELETE takes variables, not patterns" in result

    @pytest.mark.parametrize(
        "query",
        ["MATCH (b:Person) DELETE b RETRN b", "MATCH (b:Person)-[w:KNOWS]->(c) DELETE w RETURN b.name LIMT 1"],
    )
    def test_other_errors_after_delete_keep_the_syntax_hint(self, populated_ctx, query):
        assert "Hint: check the query syntax" in execute_gql(query, ctx=populated_ctx)

    def test_the_hinted_form_runs(self, populated_ctx):
        query = "MATCH (b:Person {name: 'Bob'})-[w:WORKS_AT]->(c:Company) DELETE w RETURN c.name AS company"
        result = json.loads(execute_gql(query, ctx=populated_ctx))
        assert result["rows"] == [{"company": "Acme"}] and result["counters"]["edges_deleted"] == 1
