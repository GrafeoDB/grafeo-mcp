"""Shared fixtures for grafeo-mcp tests.

Provides a real in-memory GrafeoDB instance and a lightweight mock MCP context
so tool functions can be tested without spinning up a full MCP server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import grafeo
import pytest

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
    """Minimal stand-in for ``Context[ServerSession, AppContext]``."""

    request_context: _RequestContext


def _make_ctx(db: grafeo.GrafeoDB) -> MockContext:
    return MockContext(request_context=_RequestContext(lifespan_context=_LifespanContext(db=db)))


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
