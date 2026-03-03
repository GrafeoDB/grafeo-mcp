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
