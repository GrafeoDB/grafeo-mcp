"""Engine contract: the grafeo behaviors the MCP tools rely on.

Each test pins one behavior of the ``grafeo`` package that a tool, resource or
helper depends on. When a new engine release changes one of them, the test
fails with a message naming the behavior and the code that needs a look,
instead of a tool quietly returning wrong or broken output.

Error *messages* and codes are deliberately not pinned (``GRAFEO-X001`` for a
missing node is expected to change); only the exception type and the
condition that raises are.
"""

from __future__ import annotations

import grafeo
import pytest


def _rows(result) -> list[dict]:
    return list(result)


@pytest.fixture()
def db():
    database = grafeo.GrafeoDB()
    yield database
    database.close()


@pytest.fixture()
def pair(db):
    a = db.create_node(["P"], {"name": "a"})
    b = db.create_node(["P"], {"name": "b"})
    edge = db.create_edge(a.id, b.id, "KNOWS", {"w": 2.0})
    return db, a, b, edge


# ---------------------------------------------------------------------------
# Package surface
# ---------------------------------------------------------------------------


class TestPackageSurface:
    def test_grafeo_error_is_an_exception(self):
        assert issubclass(grafeo.GrafeoError, Exception), (
            "grafeo.GrafeoError must stay an Exception subclass: every tool catches engine errors with "
            "'except Exception' (server.open_database catches GrafeoError by name)"
        )

    def test_build_info_and_features(self):
        info = grafeo.build_info()
        assert info["version"] == grafeo.__version__, "graph_info reports build_info()['version']"
        assert isinstance(info["features"], list), "graph_info reports build_info()['features']"
        assert "gql" in grafeo.features(), "execute_gql needs the gql feature in the PyPI build"
        for feature in ("algos", "vector-index", "text-index"):
            assert feature in grafeo.features(), f"tools need the '{feature}' feature in the PyPI build"

    def test_counts_are_properties(self, pair):
        db, *_ = pair
        assert db.node_count == 2, "tests and tools read db.node_count as an int property"
        assert db.edge_count == 1, "tests and tools read db.edge_count as an int property"


# ---------------------------------------------------------------------------
# Direct API (create_node, create_edge, get_*, update_*, delete_*)
# ---------------------------------------------------------------------------


class TestDirectApi:
    def test_node_and_edge_objects(self, pair):
        _db, a, b, edge = pair
        assert isinstance(a.id, int) and a.labels == ["P"] and a.properties() == {"name": "a"}, (
            "_node_to_dict reads node.id, node.labels and node.properties()"
        )
        assert (edge.source_id, edge.target_id, edge.edge_type, edge.properties()) == (
            a.id,
            b.id,
            "KNOWS",
            {"w": 2.0},
        ), "_edge_to_dict reads edge.id, source_id, target_id, edge_type and properties()"

    def test_missing_entities_read_as_none(self, db):
        assert db.get_node(4242) is None, "get_node and the not-found errors rely on get_node(missing) -> None"
        assert db.get_edge(4242) is None, "update_edge/delete_edge rely on get_edge(missing) -> None"

    def test_create_edge_to_missing_node_raises(self, db):
        a = db.create_node(["P"])
        with pytest.raises(grafeo.GrafeoError, match="does not exist"):
            db.create_edge(a.id, 4242, "KNOWS")
        with pytest.raises(grafeo.GrafeoError, match="does not exist"):
            db.create_edge(4242, a.id, "KNOWS")
        assert db.edge_count == 0, "a refused edge must not be created"

    def test_delete_node_with_edges_raises(self, pair):
        db, a, *_ = pair
        with pytest.raises(grafeo.GrafeoError):
            db.delete_node(a.id)
        assert db.get_node(a.id) is not None, "delete_node(detach=False) relies on a refused delete changing nothing"

    def test_delete_missing_returns_false(self, db):
        assert db.delete_node(4242) is False, "delete_node(missing) returns False (no exception)"
        assert db.delete_edge(4242) is False, "delete_edge(missing) returns False (no exception)"

    def test_property_writes_on_missing_entities(self, db):
        with pytest.raises(grafeo.GrafeoError):
            db.set_node_property(4242, "x", 1)
        with pytest.raises(grafeo.GrafeoError):
            db.set_edge_property(4242, "x", 1)
        assert db.remove_node_property(4242, "x") is False
        assert db.remove_edge_property(4242, "x") is False

    def test_property_update_and_remove(self, pair):
        db, a, _b, edge = pair
        db.set_node_property(a.id, "age", 30)
        assert db.remove_node_property(a.id, "name") is True
        assert db.get_node(a.id).properties() == {"age": 30}, "update_node(merge=False) removes keys one by one"
        db.set_edge_property(edge.id, "since", 2020)
        assert db.remove_edge_property(edge.id, "w") is True
        assert db.get_edge(edge.id).properties() == {"since": 2020}

    def test_direct_writes_check_constraints(self, db):
        db.execute("CREATE CONSTRAINT person_email FOR (p:Person) ON (p.email) UNIQUE")
        db.create_node(["Person"], {"email": "a@example.org"})
        with pytest.raises(grafeo.GrafeoError):
            db.create_node(["Person"], {"email": "a@example.org"})
        assert db.node_count == 1, "batch_import relies on a refused node not being created"

    def test_get_nodes_by_label_pages(self, db):
        ids = [db.create_node(["Item"], {"i": i}).id for i in range(5)]
        page1 = db.get_nodes_by_label("Item", limit=2, offset=0)
        page2 = db.get_nodes_by_label("Item", limit=2, offset=2)
        assert [node_id for node_id, _ in page1 + page2] == ids[:4], (
            "search_nodes_by_label pages with get_nodes_by_label(limit, offset) -> [(id, props)] in id order"
        )
        assert page1[0][1] == {"i": 0}


# ---------------------------------------------------------------------------
# Query results
# ---------------------------------------------------------------------------


class TestQueryResult:
    def test_rows_are_dicts_keyed_by_alias(self, pair):
        db, a, *_ = pair
        result = db.execute("MATCH (n)-[r]->(m) WHERE id(n) = $id RETURN type(r) AS t, id(m) AS m", {"id": a.id})
        rows = _rows(result)
        assert rows == [{"t": "KNOWS", "m": 1}], "resources and get_neighbors read rows as dicts by alias"
        with pytest.raises(KeyError):
            rows[0][0]  # positional access does not work; graph://nodes used to rely on it

    def test_unaliased_columns_use_expression_text(self, pair):
        db, *_ = pair
        assert db.execute("MATCH (n:P) RETURN id(n), n.name").columns == ["id(n)", "n.name"]

    def test_len_columns_timing(self, pair):
        db, *_ = pair
        result = db.execute("MATCH (n:P) RETURN n.name AS name")
        assert len(result) == 2, "_format_results counts rows with len(result)"
        assert list(result.columns) == ["name"]
        assert result.execution_time_ms is None or result.execution_time_ms >= 0

    def test_counters(self, db):
        result = db.execute("INSERT (:P {name: 'x'})")
        assert result.counters == {
            "nodes_created": 1,
            "nodes_deleted": 0,
            "edges_created": 0,
            "edges_deleted": 0,
            "properties_set": 1,
            "labels_added": 1,
            "labels_removed": 0,
        }, "execute_gql reports result.counters; delete_node reads counters['edges_deleted']"
        assert not any(db.execute("MATCH (n) RETURN n").counters.values())

    def test_detach_delete_counts_edges(self, pair):
        db, a, *_ = pair
        db.create_edge(a.id, a.id, "SELF")
        counters = db.execute("MATCH (n) WHERE id(n) = $id DETACH DELETE n", {"id": a.id}).counters
        assert (counters["nodes_deleted"], counters["edges_deleted"]) == (1, 2), (
            "delete_node(detach=True) reports counters['edges_deleted'] from DETACH DELETE"
        )

    def test_nodes_come_back_as_maps(self, pair):
        db, a, *_ = pair
        row = _rows(db.execute("MATCH (n) WHERE id(n) = $id RETURN n", {"id": a.id}))[0]
        assert row["n"] == {"_id": a.id, "_labels": ["P"], "name": "a"}, "execute_gql documents nodes as maps"


# ---------------------------------------------------------------------------
# Query language behaviors execute_gql documents or relies on
# ---------------------------------------------------------------------------


class TestQueryLanguage:
    @pytest.mark.parametrize(
        "query",
        [
            "CREATE (:P {name: 'c'})",
            "MERGE (p:P {name: 'a'})",
            "OPTIONAL MATCH (n:Missing) RETURN n",
            "MATCH (n:P) WITH n.name AS name RETURN name",
            "CREATE GRAPH reports",
            "MATCH (n:P) RETURN count(n) AS c;",
        ],
    )
    def test_cypher_style_and_ddl_accepted(self, pair, query):
        db, *_ = pair
        db.execute(query)  # raises if the engine stops accepting it; execute_gql passes text unchanged

    def test_several_statements_rejected(self, db):
        with pytest.raises(grafeo.GrafeoError):
            db.execute("INSERT (:A); INSERT (:B)")
        assert db.node_count == 0, "execute_gql refuses multi-statement text itself; the engine must agree"

    def test_missing_parameter_rejected(self, db):
        with pytest.raises(grafeo.GrafeoError):
            db.execute("INSERT (:P {name: $name})")
        assert db.node_count == 0

    def test_parameters_in_filters_and_limit(self, pair):
        db, a, b, edge = pair
        rows = _rows(
            db.execute(
                "MATCH (a)-[r]-(b) WHERE id(a) = $id AND type(r) = $t RETURN id(b) AS nid, id(r) AS eid LIMIT $n",
                {"id": a.id, "t": "KNOWS", "n": 5},
            )
        )
        assert rows == [{"nid": b.id, "eid": edge.id}], "get_neighbors passes id, edge type and limit as parameters"

    def test_merge_binds_existing_node(self, pair):
        db, a, *_ = pair
        rows = _rows(
            db.execute("MERGE (p:P {name: $name}) SET p += $props RETURN id(p) AS id", {"name": "a", "props": {"x": 1}})
        )
        assert rows == [{"id": a.id}], "execute_gql documents MERGE ... SET p += $props as the upsert pattern"

    def test_comment_and_string_rules_match_the_scanner(self, db):
        # tools/_gql.py mirrors these lexer rules to count statements and find
        # write keywords; if the engine changes them the scanner must follow.
        db.execute("INSERT (:A {t: 'x; y', u: 'it\\'s'}) -- ; INSERT (:B)")
        db.execute("INSERT (:A) /* ; INSERT (:B) */")
        assert _rows(db.execute("MATCH (n) RETURN labels(n) AS l")) == [{"l": ["A"]}, {"l": ["A"]}]
        assert db.execute("MATCH (a)--(b) RETURN a").columns == ["a"], "a bare '--' is an edge, not a comment"


# ---------------------------------------------------------------------------
# Transactions (execute_gql in read-only mode)
# ---------------------------------------------------------------------------


class TestTransactions:
    def test_rollback_undoes_writes(self, pair):
        db, a, *_ = pair
        tx = db.begin_transaction()
        result = tx.execute("MATCH (n) WHERE id(n) = $id SET n.name = 'changed' RETURN n.name AS name", {"id": a.id})
        assert result.counters["properties_set"] == 1, "read-only execute_gql detects writes by tx counters"
        tx.execute("INSERT (:Temp)")
        tx.rollback()
        assert db.get_node(a.id).properties()["name"] == "a"
        assert db.node_count == 2, "read-only execute_gql relies on rollback() undoing what the query wrote"


# ---------------------------------------------------------------------------
# Indexes and search
# ---------------------------------------------------------------------------


class TestIndexesAndSearch:
    @pytest.fixture()
    def docs(self, db):
        db.create_node(["Doc"], {"title": "graph databases", "emb": [1.0, 0.0, 0.0], "slug": "g"})
        db.create_node(["Doc"], {"title": "vector search", "emb": [0.0, 1.0, 0.0], "slug": "v"})
        db.create_vector_index("Doc", "emb", 3, "cosine")
        db.create_text_index("Doc", "title")
        db.create_property_index("slug")
        return db

    def test_memory_usage_lists_vector_and_text_indexes(self, docs):
        indexes = docs.memory_usage()["indexes"]
        assert [(i["name"], i["item_count"]) for i in indexes["vector_indexes"]] == [("Doc:emb", 2)], (
            "graph_info and graph://schema list vector indexes from memory_usage()['indexes']['vector_indexes']"
        )
        assert [(i["name"], i["item_count"]) for i in indexes["text_indexes"]] == [("Doc:title", 2)]
        assert docs.has_property_index("slug") and not docs.has_property_index("title")

    def test_vector_search_shape(self, docs):
        hits = docs.vector_search("Doc", "emb", [1.0, 0.0, 0.0], 2, None)
        assert [node_id for node_id, _ in hits] == [0, 1], "vector tools read [(node_id, distance)] ascending"
        assert hits[0][1] <= hits[1][1]
        mmr = docs.mmr_search("Doc", "emb", [1.0, 0.0, 0.0], 2, None, None, None)
        assert {node_id for node_id, _ in mmr} == {0, 1}

    def test_new_nodes_join_existing_indexes(self, docs):
        node = docs.create_node(["Doc"], {"title": "graph theory", "emb": [0.9, 0.1, 0.0]})
        assert node.id in [n for n, _ in docs.vector_search("Doc", "emb", [0.9, 0.1, 0.0], 1, None)], (
            "create_vector_index documents that later nodes are indexed on write"
        )
        assert node.id in [n for n, _ in docs.text_search("Doc", "title", "theory", 5)]

    def test_query_written_vectors_are_indexed(self, docs):
        a = _rows(docs.execute("INSERT (d:Doc {emb: $emb}) RETURN id(d) AS id", {"emb": [0.0, 0.0, 1.0]}))[0]["id"]
        b = _rows(docs.execute("INSERT (d:Doc {emb: vector([0.0, 0.1, 1.0])}) RETURN id(d) AS id"))[0]["id"]
        hits = [node_id for node_id, _ in docs.vector_search("Doc", "emb", [0.0, 0.0, 1.0], 2, None)]
        assert set(hits) == {a, b}, (
            "execute_gql and create_vector_index document that $parameter and vector([...]) embeddings are indexed"
        )

    def test_search_without_index_raises(self, db):
        with pytest.raises(RuntimeError, match="create_vector_index"):
            db.vector_search("Doc", "emb", [1.0], 1, None)
        with pytest.raises(RuntimeError, match="create_text_index"):
            db.text_search("Doc", "title", "x", 1)

    def test_vector_index_needs_dimensions_without_data(self, db):
        with pytest.raises(RuntimeError, match="dimensions"):
            db.create_vector_index("Empty", "emb")
        db.create_vector_index("Empty", "emb", 4)  # create_vector_index documents dimensions for this case


# ---------------------------------------------------------------------------
# Algorithms
# ---------------------------------------------------------------------------


class TestAlgorithms:
    def test_empty_graph(self, db):
        alg = db.algorithms
        assert alg.pagerank() == {} and alg.betweenness_centrality() == {} and alg.connected_components() == {}
        assert alg.louvain() == {"communities": {}, "modularity": 0.0, "num_communities": 0}
        assert alg.dijkstra(source=0, target=1) is None

    def test_result_shapes(self, pair):
        db, a, b, _ = pair
        c = db.create_node(["P"], {"name": "c"})
        db.create_edge(b.id, c.id, "KNOWS", {"w": 0.5})
        alg = db.algorithms
        assert set(alg.pagerank(damping=0.85, max_iterations=100, tolerance=1e-6)) == {a.id, b.id, c.id}
        assert set(alg.betweenness_centrality(normalized=True)) == {a.id, b.id, c.id}
        assert set(alg.connected_components().values()) == {0}
        louvain = alg.louvain(resolution=1.0)
        assert set(louvain) == {"communities", "modularity", "num_communities"}
        assert set(louvain["communities"]) == {a.id, b.id, c.id}

    def test_dijkstra_directed_weighted_and_missing(self, pair):
        db, a, b, _ = pair
        c = db.create_node(["P"])
        db.create_edge(b.id, c.id, "KNOWS", {"w": 0.5})
        assert db.algorithms.dijkstra(source=a.id, target=c.id, weight="w") == (2.5, [a.id, b.id, c.id])
        assert db.algorithms.dijkstra(source=c.id, target=a.id) is None, "dijkstra follows edge direction"
        assert db.algorithms.dijkstra(source=a.id, target=4242) is None, (
            "dijkstra returns None for a missing node, so the tool checks node existence itself"
        )

    def test_louvain_numbering_is_deterministic(self, db):
        for _ in range(3):
            db.create_node(["N"])
        assert db.algorithms.louvain()["communities"] == {0: 0, 1: 1, 2: 2}, (
            "louvain's docstring promises communities numbered from 0 by smallest node id"
        )


# ---------------------------------------------------------------------------
# Persistence and read-only opens (server.open_database)
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_single_file_reopens_with_indexes(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        db = grafeo.GrafeoDB(path)
        db.create_node(["Doc"], {"emb": [1.0, 0.0], "title": "hello world", "slug": "h"})
        db.create_vector_index("Doc", "emb", 2, "cosine")
        db.create_text_index("Doc", "title")
        db.create_property_index("slug")
        db.close()

        db = grafeo.GrafeoDB(path)
        try:
            assert db.node_count == 1
            assert db.vector_search("Doc", "emb", [1.0, 0.0], 1, None)[0][0] == 0
            assert db.text_search("Doc", "title", "hello", 1)[0][0] == 0
            assert db.has_property_index("slug"), "README recommends .grafeo paths because indexes survive a reopen"
        finally:
            db.close()

    def test_open_read_only_rejects_writes(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        db = grafeo.GrafeoDB(path)
        db.create_node(["P"], {"name": "a"})
        db.close()

        ro = grafeo.GrafeoDB.open_read_only(path)
        try:
            assert ro.node_count == 1
            for query in ("INSERT (:X)", "MATCH (n) SET n.x = 1", "MATCH (n) DETACH DELETE n", "CREATE GRAPH g"):
                with pytest.raises(grafeo.GrafeoError):
                    ro.execute(query)
            with pytest.raises(grafeo.GrafeoError):
                ro.create_node(["X"])
            assert ro.node_count == 1
            tx = ro.begin_transaction()  # read-only execute_gql runs reads in a rolled-back transaction
            assert _rows(tx.execute("MATCH (n) RETURN count(n) AS c")) == [{"c": 1}]
            tx.rollback()
        finally:
            ro.close()

    def test_open_read_only_needs_an_existing_single_file(self, tmp_path):
        with pytest.raises(grafeo.GrafeoError):
            grafeo.GrafeoDB.open_read_only(str(tmp_path / "missing.grafeo"))
        directory = str(tmp_path / "graph.db")
        grafeo.GrafeoDB(directory).close()
        with pytest.raises(grafeo.GrafeoError):
            grafeo.GrafeoDB.open_read_only(directory)
