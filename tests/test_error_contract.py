"""The error contract: every tool reports failures the same way.

A failure is a string ``Error: <tool>: <problem>`` (plus an optional
``Hint: ...``), never an exception or a traceback, and the registered MCP tool
returns it with ``isError: true`` (mcp 2.x: ``is_error``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import grafeo
import pytest
from mcp.types import CallToolResult

from grafeo_mcp.server import mcp
from grafeo_mcp.tools import algorithms, batch, graph, query, search, vector
from grafeo_mcp.tools._helpers import guard, tool_error
from tests.conftest import _make_ctx


class _BrokenDB:
    """A database whose every method fails, to reach the generic error paths."""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(f"{name} is broken")

        return fail


def _db_with_constraint() -> grafeo.GrafeoDB:
    db = grafeo.GrafeoDB()
    db.execute("CREATE CONSTRAINT person_email FOR (p:Person) ON (p.email) UNIQUE")
    db.create_node(["Person"], {"email": "taken@example.org"})
    db.create_node(["Person"], {"email": "other@example.org"})
    db.create_edge(0, 1, "KNOWS")
    db.create_node(["Lonely"])
    return db


# (tool name, function, kwargs, database factory)
CASES: list[tuple[str, Callable[..., str], dict[str, Any], Callable[[], Any]]] = [
    ("execute_gql", query.execute_gql, {"query": "SLECT * FORM nodes"}, grafeo.GrafeoDB),
    ("execute_gql", query.execute_gql, {"query": "RETURN $missing"}, grafeo.GrafeoDB),
    ("query_as_of", query.query_as_of, {"query": "MATCH (n) RETURN n", "as_of": "whenever"}, grafeo.GrafeoDB),
    ("query_as_of", query.query_as_of, {"query": "INSERT (:X)", "as_of": "60"}, grafeo.GrafeoDB),
    ("get_node_as_of", graph.get_node_as_of, {"node_id": 0, "as_of": "whenever"}, grafeo.GrafeoDB),
    (
        "create_node",
        graph.create_node,
        {"labels": ["Person"], "properties": {"email": "taken@example.org"}},
        _db_with_constraint,
    ),
    ("create_edge", graph.create_edge, {"source_id": 0, "target_id": 99, "edge_type": "KNOWS"}, _db_with_constraint),
    ("create_edge", graph.create_edge, {"source_id": -1, "target_id": 0, "edge_type": "KNOWS"}, _db_with_constraint),
    ("get_node", graph.get_node, {"node_id": 99}, grafeo.GrafeoDB),
    ("get_node", graph.get_node, {"node_id": -5}, grafeo.GrafeoDB),
    ("search_nodes_by_label", graph.search_nodes_by_label, {"label": "Person", "limit": 0}, grafeo.GrafeoDB),
    ("search_nodes_by_label", graph.search_nodes_by_label, {"label": "Person"}, _BrokenDB),
    ("graph_info", graph.graph_info, {}, _BrokenDB),
    ("get_neighbors", graph.get_neighbors, {"node_id": 99}, grafeo.GrafeoDB),
    ("get_neighbors", graph.get_neighbors, {"node_id": 0, "direction": "up"}, grafeo.GrafeoDB),
    ("update_node", graph.update_node, {"node_id": 99, "properties": {"x": 1}}, grafeo.GrafeoDB),
    (
        "update_node",
        graph.update_node,
        {"node_id": 1, "properties": {"email": "taken@example.org"}},
        _db_with_constraint,
    ),
    ("delete_node", graph.delete_node, {"node_id": 99}, grafeo.GrafeoDB),
    ("delete_node", graph.delete_node, {"node_id": 0, "detach": False}, _db_with_constraint),
    ("update_edge", graph.update_edge, {"edge_id": 99, "properties": {"x": 1}}, grafeo.GrafeoDB),
    ("delete_edge", graph.delete_edge, {"edge_id": 99}, grafeo.GrafeoDB),
    ("batch_import", batch.batch_import, {"nodes": [{"properties": {}}]}, grafeo.GrafeoDB),
    ("create_text_index", search.create_text_index, {"label": "Doc", "property": "title"}, _BrokenDB),
    ("search_text", search.search_text, {"label": "Doc", "property": "title", "query": "x"}, grafeo.GrafeoDB),
    (
        "vector_search",
        vector.vector_search,
        {"label": "Doc", "property": "emb", "query_vector": [1.0]},
        grafeo.GrafeoDB,
    ),
    ("vector_search", vector.vector_search, {"label": "Doc", "property": "emb", "query_vector": []}, grafeo.GrafeoDB),
    (
        "create_vector_index",
        vector.create_vector_index,
        {"label": "Doc", "property": "emb", "dimensions": 3, "metric": "bogus"},
        grafeo.GrafeoDB,
    ),
    ("mmr_search", vector.mmr_search, {"label": "Doc", "property": "emb", "query_vector": [1.0]}, grafeo.GrafeoDB),
    (
        "mmr_search",
        vector.mmr_search,
        {"label": "Doc", "property": "emb", "query_vector": [1.0], "lambda_mult": 2.0},
        grafeo.GrafeoDB,
    ),
    (
        "vector_graph_search",
        vector.vector_graph_search,
        {"label": "Doc", "property": "emb", "query_vector": [1.0]},
        grafeo.GrafeoDB,
    ),
    ("pagerank", algorithms.pagerank, {"damping": 1.5}, grafeo.GrafeoDB),
    ("pagerank", algorithms.pagerank, {}, _BrokenDB),
    ("dijkstra", algorithms.dijkstra, {"source_id": 0, "target_id": 99}, _db_with_constraint),
    ("dijkstra", algorithms.dijkstra, {"source_id": 1, "target_id": 0, "direction": "outgoing"}, _db_with_constraint),
    ("louvain", algorithms.louvain, {"resolution": -1.0}, grafeo.GrafeoDB),
    ("louvain", algorithms.louvain, {}, _BrokenDB),
    ("betweenness_centrality", algorithms.betweenness_centrality, {"top_k": 0}, grafeo.GrafeoDB),
    ("betweenness_centrality", algorithms.betweenness_centrality, {}, _BrokenDB),
    ("connected_components", algorithms.connected_components, {}, _BrokenDB),
]

_IDS = [f"{name}-{i}" for i, (name, *_rest) in enumerate(CASES)]


def test_every_tool_has_an_error_case():
    assert {name for name, *_ in CASES} == set(mcp._tool_manager._tools)


@pytest.mark.parametrize(("tool", "fn", "kwargs", "make_db"), CASES, ids=_IDS)
def test_error_strings(tool, fn, kwargs, make_db):
    db = make_db()
    try:
        result = fn(**kwargs, ctx=_make_ctx(db))
    finally:
        if isinstance(db, grafeo.GrafeoDB):
            db.close()
    assert isinstance(result, str)
    assert result.startswith(f"Error: {tool}: "), result
    assert "Traceback" not in result


@pytest.mark.parametrize(("tool", "fn", "kwargs", "make_db"), CASES, ids=_IDS)
def test_registered_tools_flag_errors(tool, fn, kwargs, make_db):
    registered = mcp._tool_manager.get_tool(tool)
    assert registered is not None
    db = make_db()
    try:
        result = registered.fn(**kwargs, ctx=_make_ctx(db))
    finally:
        if isinstance(db, grafeo.GrafeoDB):
            db.close()
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    text = result.content[0].text
    assert text.startswith(f"Error: {tool}: ")
    assert result.structured_content is None  # the text is the result, sent once


def test_registered_tools_pass_success_through(populated_ctx):
    registered = mcp._tool_manager.get_tool("get_node")
    assert registered is not None
    result = registered.fn(node_id=0, ctx=populated_ctx)
    assert isinstance(result, str) and result.startswith("{")


# ---------------------------------------------------------------------------
# The guard every tool is wrapped in
# ---------------------------------------------------------------------------


class PanicException(BaseException):
    """Stand-in for pyo3_runtime.PanicException, raised when the Rust engine panics."""


class TestGuard:
    def _make(self, exc: BaseException) -> Callable[..., str]:
        def raising_tool() -> str:
            raise exc

        raising_tool.__name__ = "guard_probe"
        return guard(raising_tool)

    def test_unexpected_exception_becomes_error(self):
        result = self._make(ValueError("bad value"))()
        assert result.startswith("Error: guard_probe: ")
        assert "bad value" in result

    def test_engine_panic_becomes_error(self):
        result = self._make(PanicException("assertion failed: dims"))()
        assert "the grafeo engine panicked (assertion failed: dims)" in result

    def test_interrupts_still_propagate(self):
        with pytest.raises(KeyboardInterrupt):
            self._make(KeyboardInterrupt())()


class TestToolErrorFormat:
    def test_sentence_gets_a_period_and_hint(self):
        assert tool_error("t", "it failed", "try again.") == "Error: t: it failed. Hint: try again."

    def test_existing_punctuation_kept(self):
        assert tool_error("t", "it failed!") == "Error: t: it failed!"

    def test_multiline_engine_message_keeps_its_layout(self):
        text = tool_error("t", "syntax error\n  --> query:1:1\n   |", "check it.")
        assert text == "Error: t: syntax error\n  --> query:1:1\n   |\nHint: check it."

    def test_empty_problem(self):
        assert tool_error("t", "  ") == "Error: t: unknown error."
