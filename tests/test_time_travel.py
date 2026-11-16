"""Time-travel reads (grafeo 0.6.2 history retention): query_as_of, get_node_as_of.

The tools read the committed state at a point in time. The database must keep
history for that: opened with history_retention ("forever", a timedelta, or
GRAFEO_HISTORY_RETENTION on the server).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import grafeo
import pytest

from grafeo_mcp.server import _env_history_retention, open_database
from grafeo_mcp.tools.graph import get_node_as_of
from grafeo_mcp.tools.query import query_as_of

from .conftest import _make_ctx


@pytest.fixture()
def tt_db():
    """In-memory database that keeps its history forever."""
    db = grafeo.GrafeoDB(history_retention="forever")
    yield db
    db.close()


@pytest.fixture()
def tt_ctx(tt_db):
    return _make_ctx(tt_db)


def _now() -> str:
    """A point after every earlier commit: the engine's commit clock and this process's clock can tick
    differently (coarse on Windows), so leave a gap before reading the time."""
    time.sleep(0.05)
    return datetime.now(UTC).isoformat()


class TestQueryAsOf:
    def test_sees_the_state_at_a_datetime(self, tt_db, tt_ctx):
        tt_db.execute("INSERT (:P {n: 'a'})")
        point = _now()
        time.sleep(0.05)
        tt_db.execute("INSERT (:P {n: 'b'})")
        tt_db.execute("MATCH (n:P {n: 'a'}) SET n.n = 'a2'")

        assert json.loads(query_as_of("MATCH (n:P) RETURN n.n AS n ORDER BY n", point, ctx=tt_ctx))["rows"] == [
            {"n": "a"}
        ]
        # The current state has both changes.
        assert json.loads(query_as_of("MATCH (n:P) RETURN n.n AS n ORDER BY n", _now(), ctx=tt_ctx))["rows"] == [
            {"n": "a2"},
            {"n": "b"},
        ]

    def test_sees_a_deleted_node(self, tt_db, tt_ctx):
        tt_db.execute("INSERT (:P {n: 'gone'})")
        point = _now()
        time.sleep(0.05)
        tt_db.execute("MATCH (n:P {n: 'gone'}) DETACH DELETE n")

        assert json.loads(query_as_of("MATCH (n) RETURN count(n) AS c", point, ctx=tt_ctx))["rows"] == [{"c": 1}]
        assert json.loads(query_as_of("MATCH (n) RETURN count(n) AS c", _now(), ctx=tt_ctx))["rows"] == [{"c": 0}]

    def test_params(self, tt_db, tt_ctx):
        tt_db.execute("INSERT (:P {n: 'a'}), (:P {n: 'b'})")
        point = _now()
        rows = json.loads(
            query_as_of("MATCH (n:P) WHERE n.n = $name RETURN n.n AS n", point, params={"name": "b"}, ctx=tt_ctx)
        )["rows"]
        assert rows == [{"n": "b"}]

    def test_missing_param_is_refused(self, tt_db, tt_ctx):
        result = query_as_of("MATCH (n) WHERE n.x = $x RETURN n", _now(), ctx=tt_ctx)
        assert result.startswith("Error: query_as_of:") and "$x" in result

    def test_write_query_is_refused(self, tt_db, tt_ctx):
        result = query_as_of("INSERT (:P {n: 'x'})", _now(), ctx=tt_ctx)
        assert result.startswith("Error: query_as_of:") and "cannot write" in result
        assert tt_db.node_count == 0

    def test_multiple_statements_are_refused(self, tt_db, tt_ctx):
        result = query_as_of("MATCH (n) RETURN n; MATCH (n) RETURN n", _now(), ctx=tt_ctx)
        assert result.startswith("Error: query_as_of:") and "2 statements" in result

    def test_point_formats(self, tt_db, tt_ctx):
        tt_db.execute("INSERT (:P)")
        assert query_as_of("MATCH (n) RETURN count(n) AS c", "0", ctx=tt_ctx).startswith("Error: query_as_of:"), (
            "zero seconds ago is refused"
        )
        assert "offset" in query_as_of("MATCH (n) RETURN count(n) AS c", "2026-11-09T10:00:00", ctx=tt_ctx)
        assert "not a point in time" in query_as_of("MATCH (n) RETURN count(n) AS c", "whenever", ctx=tt_ctx)

    def test_without_history_the_error_names_the_fix(self, ctx):
        # The default db fixture keeps no history (retention off).
        result = query_as_of("MATCH (n) RETURN count(n) AS c", _now(), ctx=ctx)
        assert result.startswith("Error: query_as_of:")
        assert "GRAFEO_HISTORY_RETENTION" in result

    def test_point_before_the_history_start_is_an_error(self, tt_db, tt_ctx):
        tt_db.execute("INSERT (:P)")
        result = query_as_of("MATCH (n) RETURN count(n) AS c", "3600", ctx=tt_ctx)
        # The database was created seconds ago, so an hour ago is before its history.
        assert result.startswith("Error: query_as_of:")
        assert "GRAFEO_HISTORY_RETENTION" in result or "not retained" in result

    def test_works_in_read_only_mode(self, tt_db):
        from dataclasses import dataclass

        @dataclass
        class _Lifespan:
            db: object
            read_only: bool = True

        @dataclass
        class _Request:
            lifespan_context: _Lifespan

        @dataclass
        class _Ctx:
            request_context: _Request

        tt_db.execute("INSERT (:P {n: 'a'})")
        point = _now()
        ctx = _Ctx(request_context=_Request(lifespan_context=_Lifespan(db=tt_db, read_only=True)))
        rows = json.loads(query_as_of("MATCH (n:P) RETURN n.n AS n", point, ctx=ctx))["rows"]
        assert rows == [{"n": "a"}]


class TestGetNodeAsOf:
    def test_old_property_values(self, tt_db, tt_ctx):
        node = tt_db.create_node(["P"], {"n": "before"})
        point = _now()
        time.sleep(0.05)
        tt_db.set_node_property(node.id, "n", "after")

        old = json.loads(get_node_as_of(node.id, point, ctx=tt_ctx))
        assert old["properties"]["n"] == "before"
        current = json.loads(get_node_as_of(node.id, _now(), ctx=tt_ctx))
        assert current["properties"]["n"] == "after"

    def test_node_created_later_did_not_exist(self, tt_db, tt_ctx):
        point = _now()
        time.sleep(0.05)
        node = tt_db.create_node(["P"], {"n": "new"})
        result = get_node_as_of(node.id, point, ctx=tt_ctx)
        assert result.startswith("Error: get_node_as_of:") and "did not exist" in result

    def test_deleted_node_is_gone_now_but_was_there(self, tt_db, tt_ctx):
        node = tt_db.create_node(["P"], {"n": "temp"})
        point = _now()
        time.sleep(0.05)
        tt_db.execute("MATCH (n) WHERE id(n) = $id DETACH DELETE n", {"id": node.id})
        assert json.loads(get_node_as_of(node.id, point, ctx=tt_ctx))["properties"]["n"] == "temp"

    def test_without_history_the_error_names_the_fix(self, ctx):
        result = get_node_as_of(0, _now(), ctx=ctx)
        assert result.startswith("Error: get_node_as_of:")
        assert "GRAFEO_HISTORY_RETENTION" in result

    def test_bad_point(self, tt_ctx):
        result = get_node_as_of(0, "noon-ish", ctx=tt_ctx)
        assert result.startswith("Error: get_node_as_of:") and "not a point in time" in result


class TestOpenDatabaseRetention:
    def test_env_parsing(self, monkeypatch):
        monkeypatch.delenv("GRAFEO_HISTORY_RETENTION", raising=False)
        assert _env_history_retention() is None
        monkeypatch.setenv("GRAFEO_HISTORY_RETENTION", "forever")
        assert _env_history_retention() == "forever"
        monkeypatch.setenv("GRAFEO_HISTORY_RETENTION", "OFF")
        assert _env_history_retention() == "off"
        monkeypatch.setenv("GRAFEO_HISTORY_RETENTION", "300")
        assert _env_history_retention() == timedelta(seconds=300)
        monkeypatch.setenv("GRAFEO_HISTORY_RETENTION", "soon")
        with pytest.raises(RuntimeError, match="GRAFEO_HISTORY_RETENTION"):
            _env_history_retention()
        monkeypatch.setenv("GRAFEO_HISTORY_RETENTION", "-5")
        with pytest.raises(RuntimeError, match="above 0"):
            _env_history_retention()

    def test_in_memory_db_with_retention(self):
        db, engine_read_only = open_database(None, read_only=False, history_retention="forever")
        try:
            assert engine_read_only is False
            db.execute("INSERT (:P)")
            time.sleep(0.05)
            point = datetime.now(UTC)
            time.sleep(0.05)
            db.execute("INSERT (:P)")
            rows = list(db.execute_as_of("MATCH (n) RETURN count(n) AS c", point))
            assert rows == [{"c": 1}]
        finally:
            db.close()

    def test_file_db_stores_retention(self, tmp_path):
        path = str(tmp_path / "tt.grafeo")
        db, _ = open_database(path, read_only=False, history_retention="forever")
        db.execute("INSERT (:P)")
        db.close()
        # Reopened without asking for retention: the file stores it.
        db2, _ = open_database(path, read_only=False)
        try:
            db2.execute("INSERT (:P)")
            time.sleep(0.05)
            point = datetime.now(UTC)
            time.sleep(0.05)
            db2.execute("INSERT (:P)")
            rows = list(db2.execute_as_of("MATCH (n) RETURN count(n) AS c", point))
            assert rows == [{"c": 2}]
        finally:
            db2.close()
