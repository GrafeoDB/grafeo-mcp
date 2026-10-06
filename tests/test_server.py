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
    ctx = AppContext(db=db, read_only=False)
    assert ctx.db is db
    assert ctx.read_only is False
    db.close()


def test_app_context_read_only():
    import grafeo

    db = grafeo.GrafeoDB()
    ctx = AppContext(db=db, read_only=True)
    assert ctx.read_only is True
    db.close()


def test_main_selects_transport(monkeypatch):
    import sys

    from grafeo_mcp import server

    calls: list[str] = []
    monkeypatch.setattr(server.mcp, "run", lambda transport: calls.append(transport))
    for argv, expected in (
        (["grafeo-mcp"], "stdio"),
        (["grafeo-mcp", "streamable-http"], "streamable-http"),
        (["grafeo-mcp", "sse"], "sse"),
    ):
        monkeypatch.setattr(sys, "argv", argv)
        server.main()
        assert calls[-1] == expected
