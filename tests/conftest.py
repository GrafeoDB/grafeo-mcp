"""Shared fixtures for grafeo-mcp tests.

Provides a real in-memory GrafeoDB instance and a lightweight mock MCP context
so tool functions can be tested without spinning up a full MCP server.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grafeo
import pytest


@asynccontextmanager
async def client_session(server: Any, timeout_seconds: float = 30) -> AsyncGenerator[Any]:
    """An in-memory MCP client session against *server* (mcp >= 2.2 test transport)."""
    from mcp import ClientSession
    from mcp.client._memory import InMemoryTransport  # mcp 2.x in-memory transport

    async with (
        InMemoryTransport(server) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, read_timeout_seconds=timeout_seconds) as client,
    ):
        await client.initialize()
        yield client


# ---------------------------------------------------------------------------
# Mock MCP context chain: ctx.request_context.lifespan_context.db
# ---------------------------------------------------------------------------


@dataclass
class _LifespanContext:
    db: Any
    read_only: bool = False


@dataclass
class _RequestContext:
    lifespan_context: _LifespanContext


@dataclass
class MockContext:
    """Minimal stand-in for ``Context[AppContext, ServerSession]``."""

    request_context: _RequestContext


def _make_ctx(db: grafeo.GrafeoDB) -> MockContext:
    return MockContext(request_context=_RequestContext(lifespan_context=_LifespanContext(db=db)))


# ---------------------------------------------------------------------------
# Databases written by grafeo 0.5.44 (see fixtures/grafeo-0.5.44/make_fixtures.py)
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "grafeo-0.5.44"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    """Copy a grafeo 0.5.44 database from tests/fixtures into *tmp_path*."""
    source, target = FIXTURES / name, tmp_path / name
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return target


def check_fixture_data(db: grafeo.GrafeoDB) -> None:
    """The data tests/fixtures/grafeo-0.5.44/make_fixtures.py writes."""
    assert (db.node_count, db.edge_count) == (3, 2)
    people = list(db.execute("MATCH (p:Person) RETURN p.name AS n, p.age AS a, p.score AS s ORDER BY n"))
    assert people == [{"n": "Alix", "a": 30, "s": 1.5}, {"n": "Gus", "a": 25, "s": 2.25}]
    edges = list(db.execute("MATCH (a)-[r]->(b) RETURN a.name AS a, type(r) AS t, r.since AS s ORDER BY s"))
    assert edges == [{"a": "Alix", "t": "KNOWS", "s": 2020}, {"a": "Gus", "t": "WORKS_AT", "s": 2021}]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """Fresh in-memory GrafeoDB instance (empty)."""
    database = grafeo.GrafeoDB()
    yield database
    database.close()


@pytest.fixture()
def ctx(db):
    """Mock MCP context wrapping an empty in-memory DB."""
    return _make_ctx(db)


@pytest.fixture()
def populated_db():
    """In-memory GrafeoDB pre-loaded with a small test graph.

    Graph structure::

        (Alice:Person)-[:KNOWS]->(Bob:Person)
        (Alice:Person)-[:WORKS_AT]->(Acme:Company)
        (Bob:Person)-[:KNOWS]->(Charlie:Person)
        (Bob:Person)-[:WORKS_AT]->(Acme:Company)
        (Charlie:Person)-[:WORKS_AT]->(WidgetInc:Company)
    """
    database = grafeo.GrafeoDB()

    alice = database.create_node(["Person"], {"name": "Alice", "age": 30})
    bob = database.create_node(["Person"], {"name": "Bob", "age": 25})
    charlie = database.create_node(["Person"], {"name": "Charlie", "age": 35})
    acme = database.create_node(["Company"], {"name": "Acme", "industry": "Technology"})
    widget = database.create_node(["Company"], {"name": "Widget Inc", "industry": "Manufacturing"})

    database.create_edge(alice.id, bob.id, "KNOWS")
    database.create_edge(alice.id, acme.id, "WORKS_AT", {"since": 2020})
    database.create_edge(bob.id, charlie.id, "KNOWS")
    database.create_edge(bob.id, acme.id, "WORKS_AT", {"since": 2021})
    database.create_edge(charlie.id, widget.id, "WORKS_AT", {"since": 2019})

    yield database
    database.close()


@pytest.fixture()
def populated_ctx(populated_db):
    """Mock MCP context wrapping the pre-loaded test graph."""
    return _make_ctx(populated_db)
