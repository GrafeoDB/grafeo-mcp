"""Smoke tests for server module — verify the MCP server boots and has expected shape."""

from __future__ import annotations

from grafeo_mcp.server import AppContext, mcp


def test_mcp_instance_exists():
    assert mcp is not None
    assert mcp.name == "grafeo"


def test_main_entrypoint_exists():
    from grafeo_mcp.server import main

    assert callable(main)


def test_app_context_holds_db():
    import grafeo

    db = grafeo.GrafeoDB()
    ctx = AppContext(db=db)
    assert ctx.db is db
    db.close()
