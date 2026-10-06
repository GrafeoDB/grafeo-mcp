"""Tests for tools/_gql.py: the lexical scan execute_gql runs before the engine."""

from __future__ import annotations

import pytest

from grafeo_mcp.tools._gql import scan_query


class TestStatements:
    @pytest.mark.parametrize(
        ("query", "count"),
        [
            ("MATCH (n) RETURN n", 1),
            ("MATCH (n) RETURN n;", 1),
            ("MATCH (n) RETURN n ;  \n", 1),
            ("INSERT (:A); INSERT (:B)", 2),
            ("INSERT (:A);;INSERT (:B);", 2),
            ("", 0),
            ("  ;  ", 0),
            ("-- only a comment\n", 0),
            ("/* only a comment */", 0),
            ("INSERT (:A {t: 'a; b'})", 1),
            ('INSERT (:A {t: "a; b"})', 1),
            ("INSERT (:`A;B`)", 1),
            ("INSERT (:A) /* ; INSERT (:B) */", 1),
            ("INSERT (:A) -- ; INSERT (:B)", 1),
            ("INSERT (:A {t: 'it\\'s; ok'})", 1),
        ],
    )
    def test_statement_count(self, query, count):
        assert scan_query(query).statements == count


class TestParameters:
    def test_parameters_found(self):
        scan = scan_query("MATCH (n) WHERE n.a = $a AND n.b IN $list_2 RETURN n LIMIT $limit")
        assert scan.parameters == {"a", "list_2", "limit"}

    def test_parameters_in_literals_and_comments_ignored(self):
        scan = scan_query("RETURN '$a' AS x, `$b` AS y /* $c */ -- $d\n")
        assert scan.parameters == set()

    def test_lone_dollar_is_not_a_parameter(self):
        assert scan_query("RETURN '5' + $ AS x").parameters == set()


class TestWriteKeywords:
    @pytest.mark.parametrize(
        ("query", "keywords"),
        [
            ("MATCH (n) RETURN n", []),
            ("INSERT (:A)", ["INSERT"]),
            ("create (:A)", ["CREATE"]),
            ("MERGE (p:P {k: 1}) ON CREATE SET p.c = 1", ["MERGE", "CREATE", "SET"]),
            ("MATCH (n) DETACH DELETE n", ["DETACH", "DELETE"]),
            ("MATCH (n) REMOVE n.x", ["REMOVE"]),
            ("DROP GRAPH g", ["DROP"]),
            ("ALTER NODE TYPE T ADD PROPERTY x STRING", ["ALTER"]),
            ("CREATE GRAPH g", ["CREATE"]),
        ],
    )
    def test_detected(self, query, keywords):
        assert scan_query(query).write_keywords == keywords

    @pytest.mark.parametrize(
        "query",
        [
            "MATCH (n:Insert) RETURN n",
            "MATCH ()-[r:DELETE]->() RETURN r",
            "MATCH (n) RETURN n.set, n.create",
            "RETURN {set: 1, remove: 2} AS m",
            "MATCH (n) WHERE n.status = 'DELETE' RETURN n",
            "MATCH (n) RETURN n.`create`",
            "MATCH (n) RETURN n /* DELETE n */",
            "MATCH (n) RETURN n -- DELETE n",
            "MATCH (n:`SET`) RETURN n",
            "MATCH (n) RETURN n.name AS create, n.x AS delete",
        ],
    )
    def test_not_detected(self, query):
        assert scan_query(query).write_keywords == []

    def test_writes_property(self):
        assert scan_query("INSERT (:A)").writes
        assert not scan_query("MATCH (n) RETURN n").writes

    def test_unterminated_literal_hides_nothing_after_it(self):
        # An unterminated string runs to the end, as in the engine's lexer
        # (which then fails to parse the query).
        assert scan_query("MATCH (n) WHERE n.a = 'x DELETE n").write_keywords == []
