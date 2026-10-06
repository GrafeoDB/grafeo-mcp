"""Persistence and database opening: file-backed databases, reopening, read-only mode."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import grafeo
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from grafeo_mcp.server import AppContext, mcp, open_database
from grafeo_mcp.tools.graph import create_node, get_node, graph_info
from grafeo_mcp.tools.query import execute_gql
from grafeo_mcp.tools.vector import vector_search
from tests.conftest import MockContext, _LifespanContext, _RequestContext


def _ctx(db: grafeo.GrafeoDB, *, read_only: bool = False) -> MockContext:
    return MockContext(request_context=_RequestContext(lifespan_context=_LifespanContext(db=db, read_only=read_only)))


def _seed(path: str) -> None:
    db = grafeo.GrafeoDB(path)
    db.create_node(["Doc"], {"title": "graph", "emb": [1.0, 0.0]})
    db.create_node(["Doc"], {"title": "vector", "emb": [0.0, 1.0]})
    db.create_vector_index("Doc", "emb", 2, "cosine")
    db.close()


# ---------------------------------------------------------------------------
# open_database
# ---------------------------------------------------------------------------


class TestOpenDatabase:
    def test_no_path_is_in_memory(self):
        db, engine_read_only = open_database(None, read_only=False)
        try:
            assert engine_read_only is False
            assert db.info()["is_persistent"] is False
        finally:
            db.close()

    def test_single_file_created_and_reopened(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        db, engine_read_only = open_database(path, read_only=False)
        assert engine_read_only is False
        create_node(["Person"], {"name": "Alice"}, ctx=_ctx(db))
        db.close()
        assert (tmp_path / "graph.grafeo").is_file()

        db, _ = open_database(path, read_only=False)
        try:
            assert json.loads(get_node(0, ctx=_ctx(db)))["properties"] == {"name": "Alice"}
        finally:
            db.close()

    def test_indexes_survive_reopen_of_single_file(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        _seed(path)
        db, _ = open_database(path, read_only=False)
        try:
            hits = json.loads(vector_search("Doc", "emb", [1.0, 0.0], k=1, ctx=_ctx(db)))
            assert hits[0]["properties"]["title"] == "graph"
            indexes = json.loads(graph_info(ctx=_ctx(db)))["indexes"]
            assert indexes["vector"] == [{"label": "Doc", "property": "emb", "items": 2}]
        finally:
            db.close()

    def test_read_only_single_file_is_enforced_by_the_engine(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        _seed(path)
        db, engine_read_only = open_database(path, read_only=True)
        try:
            assert engine_read_only is True
            # Even a direct write fails: the engine itself refuses it.
            with pytest.raises(grafeo.GrafeoError):
                db.create_node(["X"])
            ctx = _ctx(db, read_only=True)
            assert json.loads(execute_gql("MATCH (d:Doc) RETURN count(d) AS c", ctx=ctx))["rows"] == [{"c": 2}]
            assert json.loads(vector_search("Doc", "emb", [0.0, 1.0], k=1, ctx=ctx))[0]["node_id"] == 1
        finally:
            db.close()

    def test_read_only_opens_share_the_file(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        _seed(path)
        first, _ = open_database(path, read_only=True)
        second, _ = open_database(path, read_only=True)
        try:
            assert first.node_count == second.node_count == 2
        finally:
            first.close()
            second.close()

    def test_read_only_directory_database_falls_back(self, tmp_path, caplog):
        path = str(tmp_path / "graph.db")
        grafeo.GrafeoDB(path).close()
        with caplog.at_level(logging.WARNING, logger="grafeo_mcp"):
            db, engine_read_only = open_database(path, read_only=True)
        try:
            assert engine_read_only is False
            assert "only the MCP tools refuse writes" in caplog.text
            assert execute_gql("INSERT (:X)", ctx=_ctx(db, read_only=True)).startswith("Error: execute_gql:")
            assert db.node_count == 0
        finally:
            db.close()

    def test_directory_database_warns_about_indexes(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="grafeo_mcp"):
            db, _ = open_database(str(tmp_path / "graph.db"), read_only=False)
        db.close()
        assert "Prefer a single-file path ending in .grafeo" in caplog.text

    def test_single_file_does_not_warn(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="grafeo_mcp"):
            db, _ = open_database(str(tmp_path / "graph.grafeo"), read_only=False)
        db.close()
        assert caplog.text == ""

    def test_locked_database_gives_a_clear_error(self, tmp_path):
        path = str(tmp_path / "graph.grafeo")
        holder = grafeo.GrafeoDB(path)
        try:
            with pytest.raises(RuntimeError, match="could not open GRAFEO_DB_PATH="):
                open_database(path, read_only=False)
        finally:
            holder.close()

    def test_app_context_defaults(self):
        db = grafeo.GrafeoDB()
        try:
            assert AppContext(db=db, read_only=True).engine_read_only is False
        finally:
            db.close()


# ---------------------------------------------------------------------------
# The real server lifespan, through MCP
# ---------------------------------------------------------------------------


async def _call(client, tool: str, **arguments):
    result = await client.call_tool(tool, arguments)
    return result.isError, result.content[0].text


class TestLifespan:
    async def test_data_survives_a_server_restart(self, tmp_path, monkeypatch):
        path = str(tmp_path / "graph.grafeo")
        monkeypatch.setenv("GRAFEO_DB_PATH", path)
        monkeypatch.delenv("GRAFEO_READ_ONLY", raising=False)
        timeout = timedelta(seconds=30)

        async with create_connected_server_and_client_session(mcp, read_timeout_seconds=timeout) as client:
            is_error, _ = await _call(
                client,
                "batch_import",
                nodes=[
                    {"labels": ["Doc"], "properties": {"title": "a", "emb": [1.0, 0.0]}},
                    {"labels": ["Doc"], "properties": {"title": "b", "emb": [0.0, 1.0]}},
                ],
                edges=[{"source_ref": "@0", "target_ref": "@1", "edge_type": "CITES"}],
            )
            assert not is_error
            is_error, _ = await _call(client, "create_vector_index", label="Doc", property="emb", dimensions=2)
            assert not is_error

        # A second server process opens the same file (the first one closed it).
        async with create_connected_server_and_client_session(mcp, read_timeout_seconds=timeout) as client:
            is_error, text = await _call(client, "graph_info")
            info = json.loads(text)
            assert (info["info"]["node_count"], info["info"]["edge_count"]) == (2, 1)
            assert info["info"]["is_persistent"] is True
            is_error, text = await _call(client, "vector_search", label="Doc", property="emb", query_vector=[0.0, 1.0])
            assert not is_error, text
            assert json.loads(text)[0]["properties"]["title"] == "b"

    async def test_read_only_server_on_existing_file(self, tmp_path, monkeypatch):
        path = str(tmp_path / "graph.grafeo")
        _seed(path)
        monkeypatch.setenv("GRAFEO_DB_PATH", path)
        monkeypatch.setenv("GRAFEO_READ_ONLY", "1")
        async with create_connected_server_and_client_session(
            mcp, read_timeout_seconds=timedelta(seconds=30)
        ) as client:
            is_error, text = await _call(client, "create_node", labels=["X"])
            assert is_error and "read-only" in text
            is_error, text = await _call(client, "execute_gql", query="MATCH (d:Doc) RETURN d.title AS t ORDER BY t")
            assert not is_error
            assert json.loads(text)["rows"] == [{"t": "graph"}, {"t": "vector"}]
        # The file was not changed by the read-only server.
        db = grafeo.GrafeoDB.open_read_only(path)
        try:
            assert db.node_count == 2
        finally:
            db.close()

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    async def test_read_only_flag_values(self, monkeypatch, value):
        monkeypatch.delenv("GRAFEO_DB_PATH", raising=False)
        monkeypatch.setenv("GRAFEO_READ_ONLY", value)
        async with create_connected_server_and_client_session(
            mcp, read_timeout_seconds=timedelta(seconds=30)
        ) as client:
            is_error, _ = await _call(client, "create_node", labels=["X"])
            assert is_error
