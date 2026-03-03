"""Tests for tools/search.py — full-text search."""

from __future__ import annotations

import json

import grafeo
import pytest

from grafeo_mcp.tools.search import create_text_index, search_text
from tests.conftest import MockContext, _LifespanContext, _RequestContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ctx(db: grafeo.GrafeoDB) -> MockContext:
    return MockContext(request_context=_RequestContext(lifespan_context=_LifespanContext(db=db)))


@pytest.fixture()
def text_db():
    """DB with nodes containing text data and a text index."""
    database = grafeo.GrafeoDB()
    database.create_node(["Article"], {"title": "Graph Database Fundamentals", "author": "Alice"})
    database.create_node(["Article"], {"title": "Machine Learning with Graphs", "author": "Bob"})
    database.create_node(["Article"], {"title": "Introduction to SQL Databases", "author": "Charlie"})
    database.create_node(["Article"], {"title": "Advanced Graph Algorithms", "author": "Diana"})
    database.create_text_index("Article", "title")
    yield database
    database.close()


@pytest.fixture()
def text_ctx(text_db) -> MockContext:
    return _make_ctx(text_db)


# ---------------------------------------------------------------------------
# create_text_index
# ---------------------------------------------------------------------------


class TestCreateTextIndex:
    def test_basic(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.create_node(["Doc"], {"content": "hello world"})
        result = create_text_index("Doc", "content", ctx=ctx)
        assert "text index created" in result.lower()


# ---------------------------------------------------------------------------
# search_text
# ---------------------------------------------------------------------------


class TestSearchText:
    def test_basic(self, text_ctx):
        result = json.loads(search_text("Article", "title", "graph", ctx=text_ctx))
        assert len(result) >= 1
        titles = [r["properties"].get("title", "") for r in result]
        assert any("Graph" in t for t in titles)

    def test_limit(self, text_ctx):
        result = json.loads(search_text("Article", "title", "graph", limit=1, ctx=text_ctx))
        assert len(result) <= 1

    def test_no_results(self, text_ctx):
        result = json.loads(search_text("Article", "title", "quantum physics", ctx=text_ctx))
        assert len(result) == 0

    def test_no_index_error(self, ctx):
        result = search_text("Missing", "title", "test", ctx=ctx)
        assert "error" in result.lower()
