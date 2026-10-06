"""Tests for tools/batch.py — batch import."""

from __future__ import annotations

import json

from grafeo_mcp.tools.batch import batch_import
from grafeo_mcp.tools.graph import get_node


class TestBatchImport:
    def test_nodes_only(self, ctx):
        result = json.loads(
            batch_import(
                nodes=[
                    {"labels": ["Person"], "properties": {"name": "Alice"}},
                    {"labels": ["Person"], "properties": {"name": "Bob"}},
                ],
                ctx=ctx,
            )
        )
        assert result["created_nodes"] == 2
        assert result["created_edges"] == 0
        assert len(result["node_id_map"]) == 2

    def test_nodes_and_edges_with_batch_refs(self, ctx):
        result = json.loads(
            batch_import(
                nodes=[
                    {"labels": ["Person"], "properties": {"name": "Alice"}},
                    {"labels": ["Person"], "properties": {"name": "Bob"}},
                ],
                edges=[
                    {"source_ref": "@0", "target_ref": "@1", "edge_type": "KNOWS"},
                ],
                ctx=ctx,
            )
        )
        assert result["created_nodes"] == 2
        assert result["created_edges"] == 1

    def test_edges_with_existing_node_ids(self, ctx):
        db = ctx.request_context.lifespan_context.db
        existing = db.create_node(["Existing"], {"name": "Pre"})
        result = json.loads(
            batch_import(
                nodes=[{"labels": ["New"], "properties": {"name": "New1"}}],
                edges=[
                    {"source_ref": "@0", "target_ref": existing.id, "edge_type": "LINKS"},
                ],
                ctx=ctx,
            )
        )
        assert result["created_edges"] == 1

    def test_mixed_refs(self, ctx):
        db = ctx.request_context.lifespan_context.db
        pre = db.create_node(["Pre"], {"name": "Pre"})
        result = json.loads(
            batch_import(
                nodes=[
                    {"labels": ["A"], "properties": {"name": "A1"}},
                    {"labels": ["B"], "properties": {"name": "B1"}},
                ],
                edges=[
                    {"source_ref": "@0", "target_ref": "@1", "edge_type": "INTERNAL"},
                    {"source_ref": pre.id, "target_ref": "@0", "edge_type": "EXTERNAL"},
                ],
                ctx=ctx,
            )
        )
        assert result["created_nodes"] == 2
        assert result["created_edges"] == 2

    def test_empty_batch(self, ctx):
        result = json.loads(batch_import(nodes=[], ctx=ctx))
        assert result["created_nodes"] == 0
        assert result["created_edges"] == 0

    def test_no_labels_error(self, ctx):
        result = batch_import(nodes=[{"properties": {"name": "X"}}], ctx=ctx)
        assert "no labels" in result.lower()

    def test_invalid_batch_ref(self, ctx):
        result = batch_import(
            nodes=[{"labels": ["A"]}],
            edges=[{"source_ref": "@99", "target_ref": "@0", "edge_type": "BAD"}],
            ctx=ctx,
        )
        assert "error" in result.lower()

    def test_missing_edge_type(self, ctx):
        result = batch_import(
            nodes=[{"labels": ["A"]}, {"labels": ["B"]}],
            edges=[{"source_ref": "@0", "target_ref": "@1"}],
            ctx=ctx,
        )
        assert "no edge_type" in result.lower()

    def test_exceeds_node_limit(self, ctx):
        nodes = [{"labels": ["X"]} for _ in range(501)]
        result = batch_import(nodes=nodes, ctx=ctx)
        assert "exceeding the limit" in result.lower()

    def test_exceeds_edge_limit(self, ctx):
        edges = [{"source_ref": 0, "target_ref": 1, "edge_type": "X"} for _ in range(1001)]
        result = batch_import(nodes=[{"labels": ["A"]}], edges=edges, ctx=ctx)
        assert "exceeding the limit" in result.lower()

    def test_node_id_map_values(self, ctx):
        result = json.loads(
            batch_import(
                nodes=[
                    {"labels": ["X"], "properties": {"n": 1}},
                    {"labels": ["Y"], "properties": {"n": 2}},
                ],
                ctx=ctx,
            )
        )
        nmap = result["node_id_map"]
        # Both mapped IDs should point to real nodes
        for _idx_str, nid in nmap.items():
            node_result = json.loads(get_node(nid, ctx=ctx))
            assert "id" in node_result


# ---------------------------------------------------------------------------
# T6: Batch import is all or nothing
# ---------------------------------------------------------------------------


def _counts(ctx) -> tuple[int, int]:
    db = ctx.request_context.lifespan_context.db
    return db.node_count, db.edge_count


class TestBatchAllOrNothing:
    """batch_import used to create nodes before checking the edges, so a bad
    edge left a partial batch behind. The whole batch is now checked first, and
    an engine rejection partway removes what the call created."""

    def test_invalid_batch_ref_writes_nothing(self, ctx):
        result = batch_import(
            nodes=[{"labels": ["Item"], "properties": {"n": i}} for i in range(5)],
            edges=[
                {"source_ref": "@0", "target_ref": "@1", "edge_type": "NEXT"},
                {"source_ref": "@99", "target_ref": "@0", "edge_type": "BAD"},
            ],
            ctx=ctx,
        )
        assert result.startswith("Error: batch_import: edge at index 1 references source_ref='@99'")
        assert "nothing was written" in result
        assert _counts(ctx) == (0, 0)

    def test_missing_existing_node_writes_nothing(self, ctx):
        result = batch_import(
            nodes=[{"labels": ["Item"]}],
            edges=[{"source_ref": "@0", "target_ref": 4242, "edge_type": "LINKS"}],
            ctx=ctx,
        )
        assert "node 4242 does not exist" in result
        assert "nothing was written" in result
        assert _counts(ctx) == (0, 0)

    def test_engine_rejection_rolls_back(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.execute("CREATE CONSTRAINT person_email FOR (p:Person) ON (p.email) UNIQUE")
        result = batch_import(
            nodes=[
                {"labels": ["Person"], "properties": {"email": "a@example.org"}},
                {"labels": ["Person"], "properties": {"email": "b@example.org"}},
                {"labels": ["Person"], "properties": {"email": "a@example.org"}},
            ],
            edges=[{"source_ref": "@0", "target_ref": "@1", "edge_type": "KNOWS"}],
            ctx=ctx,
        )
        assert result.startswith("Error: batch_import: the engine rejected the node at index 2")
        assert "UNIQUE" in result
        assert "removed again" in result
        assert _counts(ctx) == (0, 0)

    def test_rollback_keeps_existing_data(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.execute("CREATE CONSTRAINT person_email FOR (p:Person) ON (p.email) UNIQUE")
        existing = db.create_node(["Person"], {"email": "taken@example.org"})
        result = batch_import(
            nodes=[{"labels": ["Person"], "properties": {"email": "new@example.org"}}],
            edges=[{"source_ref": "@0", "target_ref": existing.id, "edge_type": "KNOWS"}],
            ctx=ctx,
        )
        assert json.loads(result)["created_edges"] == 1
        result = batch_import(
            nodes=[
                {"labels": ["Person"], "properties": {"email": "other@example.org"}},
                {"labels": ["Person"], "properties": {"email": "taken@example.org"}},
            ],
            ctx=ctx,
        )
        assert result.startswith("Error: batch_import:")
        assert _counts(ctx) == (2, 1)
        assert db.get_node(existing.id) is not None

    def test_all_valid_succeeds(self, ctx):
        result = json.loads(
            batch_import(
                nodes=[{"labels": ["Item"], "properties": {"n": i}} for i in range(5)],
                edges=[
                    {"source_ref": "@0", "target_ref": "@1", "edge_type": "NEXT"},
                ],
                ctx=ctx,
            )
        )
        assert result["created_nodes"] == 5
        assert result["created_edges"] == 1

    def test_boundary_sizes_accepted(self, ctx):
        nodes = [{"labels": ["X"], "properties": {"i": i}} for i in range(500)]
        edges = [
            {"source_ref": f"@{i % 500}", "target_ref": f"@{(i + 1) % 500}", "edge_type": "E"} for i in range(1000)
        ]
        result = json.loads(batch_import(nodes=nodes, edges=edges, ctx=ctx))
        assert result["created_nodes"] == 500
        assert result["created_edges"] == 1000
        # The full node_id_map (500 entries) fits in the output budget.
        assert "truncated" not in result
        assert len(result["node_id_map"]) == 500

    def test_string_and_int_ref_forms(self, ctx):
        db = ctx.request_context.lifespan_context.db
        pre = db.create_node(["Pre"])
        result = json.loads(
            batch_import(
                nodes=[{"labels": ["A"]}],
                edges=[{"source_ref": "@0", "target_ref": str(pre.id), "edge_type": "E"}],
                ctx=ctx,
            )
        )
        assert result["created_edges"] == 1

    def test_bad_ref_forms(self, ctx):
        for bad in ("@x", "abc", -1, True, None):
            result = batch_import(
                nodes=[{"labels": ["A"]}],
                edges=[{"source_ref": bad, "target_ref": "@0", "edge_type": "E"}],
                ctx=ctx,
            )
            assert result.startswith("Error: batch_import: edge at index 0"), (bad, result)
        assert _counts(ctx) == (0, 0)

    def test_invalid_node_shapes(self, ctx):
        for nodes in ([{"labels": "Person"}], [{"labels": [""]}], ["Person"], [{"labels": ["A"], "properties": [1]}]):
            result = batch_import(nodes=nodes, ctx=ctx)
            assert result.startswith("Error: batch_import: node at index 0"), (nodes, result)
        assert _counts(ctx) == (0, 0)


class _FlakyDB:
    """Delegates to a real database, but fails the second edge and every delete."""

    def __init__(self, db):
        self._db = db
        self._edges = 0

    def __getattr__(self, name):
        return getattr(self._db, name)

    def create_edge(self, *args):
        self._edges += 1
        if self._edges == 2:
            raise RuntimeError("edge store unavailable")
        return self._db.create_edge(*args)

    def delete_edge(self, edge_id):
        raise RuntimeError("cannot delete")

    def delete_node(self, node_id):
        raise RuntimeError("cannot delete")


def test_failed_rollback_names_leftovers(db):
    from tests.conftest import _make_ctx

    ctx = _make_ctx(_FlakyDB(db))
    result = batch_import(
        nodes=[{"labels": ["A"]}, {"labels": ["B"]}],
        edges=[
            {"source_ref": "@0", "target_ref": "@1", "edge_type": "E"},
            {"source_ref": "@1", "target_ref": "@0", "edge_type": "E"},
        ],
        ctx=ctx,
    )
    assert result.startswith("Error: batch_import: the engine rejected the edge at index 1: edge store unavailable")
    assert "these could not be removed: edge 0, node 1, node 0" in result
