"""Tests for tools/graph.py — CRUD operations, get_neighbors, graph_info."""

from __future__ import annotations

import json

from grafeo_mcp.tools.graph import (
    create_edge,
    create_node,
    delete_edge,
    delete_node,
    get_neighbors,
    get_node,
    graph_info,
    search_nodes_by_label,
    update_edge,
    update_node,
)

# ---------------------------------------------------------------------------
# create_node
# ---------------------------------------------------------------------------


class TestCreateNode:
    def test_basic(self, ctx):
        result = json.loads(create_node(["Person"], {"name": "Eve"}, ctx=ctx))
        assert result["labels"] == ["Person"]
        assert result["properties"]["name"] == "Eve"
        assert "id" in result

    def test_multiple_labels(self, ctx):
        result = json.loads(create_node(["Person", "Employee"], ctx=ctx))
        assert set(result["labels"]) == {"Person", "Employee"}

    def test_no_properties(self, ctx):
        result = json.loads(create_node(["Tag"], ctx=ctx))
        assert result["labels"] == ["Tag"]


# ---------------------------------------------------------------------------
# create_edge
# ---------------------------------------------------------------------------


class TestCreateEdge:
    def test_basic(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        result = json.loads(create_edge(n1["id"], n2["id"], "LINKS", ctx=ctx))
        assert result["edge_type"] == "LINKS"
        assert result["source_id"] == n1["id"]
        assert result["target_id"] == n2["id"]

    def test_with_properties(self, ctx):
        n1 = json.loads(create_node(["X"], ctx=ctx))
        n2 = json.loads(create_node(["Y"], ctx=ctx))
        result = json.loads(create_edge(n1["id"], n2["id"], "REL", {"weight": 1.5}, ctx=ctx))
        assert result["properties"]["weight"] == 1.5

    def test_dangling_edge_rejected(self, ctx):
        # Since grafeo 0.5.44 the engine refuses edges to missing nodes (it
        # allowed dangling edges before); the tool names the missing node.
        result = create_edge(9999, 8888, "GHOST", ctx=ctx)
        assert result.startswith("Error: create_edge: source node 9999 does not exist")
        assert "search_nodes_by_label" in result
        assert ctx.request_context.lifespan_context.db.edge_count == 0

    def test_missing_target_named(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        result = create_edge(n1["id"], 8888, "GHOST", ctx=ctx)
        assert result.startswith("Error: create_edge: target node 8888 does not exist")

    def test_empty_edge_type_rejected(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        result = create_edge(n1["id"], n2["id"], " ", ctx=ctx)
        assert result.startswith("Error: create_edge: edge_type must be a non-empty string")


# ---------------------------------------------------------------------------
# get_node
# ---------------------------------------------------------------------------


class TestGetNode:
    def test_existing(self, populated_ctx):
        result = json.loads(get_node(0, ctx=populated_ctx))
        assert "labels" in result
        assert "properties" in result

    def test_not_found(self, ctx):
        result = get_node(9999, ctx=ctx)
        assert "not found" in result.lower()
        assert "graph_info" in result  # recovery hint


# ---------------------------------------------------------------------------
# search_nodes_by_label
# ---------------------------------------------------------------------------


class TestSearchNodesByLabel:
    def test_basic(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Person", ctx=populated_ctx))
        assert result["label"] == "Person"
        assert result["count"] == 3  # Alice, Bob, Charlie

    def test_with_limit(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Person", limit=1, ctx=populated_ctx))
        assert result["count"] == 1
        assert result["limit"] == 1

    def test_with_offset(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Person", limit=1, offset=1, ctx=populated_ctx))
        assert result["count"] == 1
        assert result["offset"] == 1

    def test_nonexistent_label(self, populated_ctx):
        result = json.loads(search_nodes_by_label("Alien", ctx=populated_ctx))
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# graph_info
# ---------------------------------------------------------------------------


class TestGraphInfo:
    def test_empty_db(self, ctx):
        result = json.loads(graph_info(ctx=ctx))
        assert "info" in result
        assert "schema" in result
        assert "stats" in result

    def test_populated(self, populated_ctx):
        result = json.loads(graph_info(ctx=populated_ctx))
        info = result["info"]
        assert info["node_count"] == 5
        assert info["edge_count"] == 5

    def test_engine_and_server_sections(self, ctx):
        import grafeo

        result = json.loads(graph_info(ctx=ctx))
        assert result["engine"]["version"] == grafeo.__version__
        assert "gql" in result["engine"]["features"]
        assert result["server"] == {"read_only": False}

    def test_lists_vector_text_and_property_indexes(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.create_node(["Doc"], {"title": "graphs", "emb": [1.0, 0.0], "slug": "a"})
        db.create_vector_index("Doc", "emb", 2, "cosine")
        db.create_text_index("Doc", "title")
        db.create_property_index("slug")
        indexes = json.loads(graph_info(ctx=ctx))["indexes"]
        assert indexes["vector"] == [{"label": "Doc", "property": "emb", "items": 1}]
        assert indexes["text"] == [{"label": "Doc", "property": "title", "items": 1}]
        assert indexes["property"] == ["slug"]

    def test_no_indexes(self, ctx):
        indexes = json.loads(graph_info(ctx=ctx))["indexes"]
        assert indexes == {"vector": [], "text": [], "property": []}


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------


class TestGetNeighbors:
    def test_both_directions(self, populated_ctx):
        # Alice (id=0) has outgoing KNOWS->Bob and WORKS_AT->Acme
        result = json.loads(get_neighbors(0, ctx=populated_ctx))
        assert result["count"] >= 2
        assert result["direction"] == "both"

    def test_outgoing_only(self, populated_ctx):
        result = json.loads(get_neighbors(0, direction="outgoing", ctx=populated_ctx))
        assert result["direction"] == "outgoing"
        assert result["count"] >= 1

    def test_incoming_only(self, populated_ctx):
        # Bob (id=1) has incoming KNOWS from Alice
        result = json.loads(get_neighbors(1, direction="incoming", ctx=populated_ctx))
        assert result["direction"] == "incoming"

    def test_edge_type_filter(self, populated_ctx):
        result = json.loads(get_neighbors(0, edge_type="KNOWS", ctx=populated_ctx))
        assert result["edge_type_filter"] == "KNOWS"
        for neighbor in result["neighbors"]:
            assert neighbor["edge_type"] == "KNOWS"

    def test_node_not_found(self, ctx):
        result = get_neighbors(9999, ctx=ctx)
        assert "not found" in result.lower()

    def test_limit(self, populated_ctx):
        result = json.loads(get_neighbors(0, limit=1, ctx=populated_ctx))
        assert result["count"] <= 1

    def test_exact_neighbors_per_direction(self, populated_ctx):
        # Bob (1): Alice -KNOWS-> Bob, Bob -KNOWS-> Charlie, Bob -WORKS_AT-> Acme
        out = json.loads(get_neighbors(1, direction="outgoing", ctx=populated_ctx))
        inc = json.loads(get_neighbors(1, direction="incoming", ctx=populated_ctx))
        both = json.loads(get_neighbors(1, ctx=populated_ctx))
        assert sorted(n["node_id"] for n in out["neighbors"]) == [2, 3]
        assert [n["node_id"] for n in inc["neighbors"]] == [0]
        assert sorted(n["node_id"] for n in both["neighbors"]) == [0, 2, 3]

    def test_edge_type_is_a_value_not_query_text(self, populated_ctx):
        # Regression: edge_type used to be pasted into the query, so a crafted
        # value could change the query (even in read-only mode).
        injected = "KNOWS]-(b) DETACH DELETE b WITH b MATCH (a)-[r"
        result = json.loads(get_neighbors(0, edge_type=injected, ctx=populated_ctx))
        assert result["count"] == 0
        assert populated_ctx.request_context.lifespan_context.db.node_count == 5

    def test_edge_type_with_space(self, ctx):
        db = ctx.request_context.lifespan_context.db
        a = db.create_node(["A"])
        b = db.create_node(["B"])
        db.create_edge(a.id, b.id, "HAS PART")
        result = json.loads(get_neighbors(a.id, edge_type="HAS PART", ctx=ctx))
        assert [n["node_id"] for n in result["neighbors"]] == [b.id]

    def test_self_loop_listed_once(self, ctx):
        db = ctx.request_context.lifespan_context.db
        a = db.create_node(["A"])
        db.create_edge(a.id, a.id, "SELF")
        result = json.loads(get_neighbors(a.id, ctx=ctx))
        assert [n["node_id"] for n in result["neighbors"]] == [a.id]


# ---------------------------------------------------------------------------
# update_node
# ---------------------------------------------------------------------------


class TestUpdateNode:
    def test_merge_properties(self, ctx):
        node = json.loads(create_node(["Person"], {"name": "Eve", "age": 25}, ctx=ctx))
        result = json.loads(update_node(node["id"], {"age": 26}, ctx=ctx))
        assert result["properties"]["age"] == 26
        assert result["properties"]["name"] == "Eve"

    def test_replace_properties(self, ctx):
        node = json.loads(create_node(["Person"], {"name": "Eve", "age": 25}, ctx=ctx))
        result = json.loads(update_node(node["id"], {"name": "Eve"}, merge=False, ctx=ctx))
        assert result["properties"]["name"] == "Eve"
        assert "age" not in result["properties"]

    def test_add_new_property(self, ctx):
        node = json.loads(create_node(["Person"], {"name": "Eve"}, ctx=ctx))
        result = json.loads(update_node(node["id"], {"email": "eve@test.com"}, ctx=ctx))
        assert result["properties"]["email"] == "eve@test.com"
        assert result["properties"]["name"] == "Eve"

    def test_not_found(self, ctx):
        result = update_node(9999, {"x": 1}, ctx=ctx)
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# delete_node
# ---------------------------------------------------------------------------


class TestDeleteNode:
    def test_detach_delete(self, populated_ctx):
        result = delete_node(0, detach=True, ctx=populated_ctx)
        assert "deleted" in result.lower()
        assert "edge" in result.lower()
        verify = get_node(0, ctx=populated_ctx)
        assert "not found" in verify.lower()

    def test_delete_isolated_node(self, ctx):
        node = json.loads(create_node(["Temp"], ctx=ctx))
        result = delete_node(node["id"], ctx=ctx)
        assert "deleted" in result.lower()
        verify = get_node(node["id"], ctx=ctx)
        assert "not found" in verify.lower()

    def test_no_detach_fails_with_edges(self, populated_ctx):
        result = delete_node(0, detach=False, ctx=populated_ctx)
        assert "connected edge" in result.lower()

    def test_not_found(self, ctx):
        result = delete_node(9999, ctx=ctx)
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# update_edge
# ---------------------------------------------------------------------------


class TestUpdateEdge:
    def test_merge_properties(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        edge = json.loads(create_edge(n1["id"], n2["id"], "REL", {"weight": 1.0}, ctx=ctx))
        result = json.loads(update_edge(edge["id"], {"score": 0.9}, ctx=ctx))
        assert result["properties"]["weight"] == 1.0
        assert result["properties"]["score"] == 0.9

    def test_replace_properties(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        edge = json.loads(create_edge(n1["id"], n2["id"], "REL", {"weight": 1.0, "note": "hi"}, ctx=ctx))
        result = json.loads(update_edge(edge["id"], {"weight": 2.0}, merge=False, ctx=ctx))
        assert result["properties"]["weight"] == 2.0
        assert "note" not in result["properties"]

    def test_not_found(self, ctx):
        result = update_edge(9999, {"x": 1}, ctx=ctx)
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# delete_edge
# ---------------------------------------------------------------------------


class TestDeleteEdge:
    def test_basic(self, ctx):
        n1 = json.loads(create_node(["A"], ctx=ctx))
        n2 = json.loads(create_node(["B"], ctx=ctx))
        edge = json.loads(create_edge(n1["id"], n2["id"], "REL", ctx=ctx))
        result = delete_edge(edge["id"], ctx=ctx)
        assert "deleted" in result.lower()

    def test_not_found(self, ctx):
        result = delete_edge(9999, ctx=ctx)
        assert "not found" in result.lower()
