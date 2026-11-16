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


class TestNames:
    """The labels, edge types and property keys a query names, for the "not in the graph" hint."""

    @pytest.mark.parametrize(
        ("query", "labels", "edge_types", "either", "keys"),
        [
            ("MATCH (n:Persn) RETURN n.name", {"Persn"}, set(), set(), {"name"}),
            (
                "MATCH (a:Person)-[r:KNOW|LIKES]->(b:Company&Org) WHERE a.nmae = $x RETURN b.title",
                {"Person", "Company", "Org"},
                {"KNOW", "LIKES"},
                set(),
                {"nmae", "title"},
            ),
            (
                "MATCH (n {name: 'x', age: 3}) WHERE n:Foo RETURN {a: 1, b: n.k}",
                set(),
                set(),
                {"Foo"},
                {"name", "age", "k"},
            ),
            ("MATCH (n:Person WHERE n.age > 1) RETURN n", {"Person"}, set(), set(), {"age"}),
            ("MATCH (n:`My Label`) RETURN n", {"My Label"}, set(), set(), set()),
            (
                "MATCH (n) WHERE EXISTS { (n)-[:WORKS_AT]->(:Company) } RETURN n",
                {"Company"},
                {"WORKS_AT"},
                set(),
                set(),
            ),
            ("MATCH (n:A:B) RETURN n", {"A", "B"}, set(), set(), set()),
        ],
    )
    def test_names(self, query, labels, edge_types, either, keys):
        scan = scan_query(query)
        assert (scan.labels, scan.edge_types, scan.label_or_type, scan.property_keys) == (
            labels,
            edge_types,
            either,
            keys,
        )

    @pytest.mark.parametrize(
        "query",
        [
            "CALL grafeo.pagerank({damping: 0.85}) YIELD node_id RETURN node_id",  # procedure name, map argument
            "MATCH p = (a)-[*1..3]->(b) RETURN length(p)",  # a range, not a property
            "RETURN $row.name, 1.5, 1.5e0",  # a parameter's field, decimals
            "RETURN 'n:Label', \"m.key\"",  # inside strings
            "RETURN x :: INT",  # a type annotation
            "RETURN {name: 1}",  # a map literal outside a pattern
        ],
    )
    def test_no_false_names(self, query):
        scan = scan_query(query)
        assert not (scan.labels or scan.edge_types or scan.label_or_type or scan.property_keys), scan
