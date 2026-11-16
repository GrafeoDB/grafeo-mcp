"""Smoke tests for the server module: it boots, has the expected shape, and its CLI parses arguments."""

from __future__ import annotations

import pytest

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


def _record_run(monkeypatch) -> list[tuple[str, dict]]:
    from grafeo_mcp import server

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(server.mcp, "run", lambda transport, **kwargs: calls.append((transport, kwargs)))
    monkeypatch.setattr(server, "_check_port_free", lambda host, port: None)  # port 8000 may be taken here
    for name in ("GRAFEO_DB_PATH", "GRAFEO_READ_ONLY", "GRAFEO_HISTORY_RETENTION"):
        monkeypatch.delenv(name, raising=False)
    return calls


# ---------------------------------------------------------------------------
# Startup errors: one line on stderr and exit status 1, before the server starts
# ---------------------------------------------------------------------------


def _startup_error(monkeypatch, capsys, argv: list[str], **env: str) -> str:
    calls = _record_run(monkeypatch)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    from grafeo_mcp import server

    with pytest.raises(SystemExit) as exc:
        server.main(argv)
    assert exc.value.code == 1
    assert calls == [], "the server must not start"
    err = capsys.readouterr().err.strip()
    assert err.startswith("grafeo-mcp: error: ") and "\n" not in err and "Traceback" not in err, err
    return err


@pytest.mark.parametrize("value", ["bogus", "0", "-5", "inf"])
def test_bad_history_retention_is_one_line(monkeypatch, capsys, value):
    err = _startup_error(monkeypatch, capsys, [], GRAFEO_HISTORY_RETENTION=value)
    assert f"GRAFEO_HISTORY_RETENTION='{value}' is not valid" in err


def test_directory_path_is_one_line_of_whole_sentences(monkeypatch, capsys, tmp_path):
    err = _startup_error(monkeypatch, capsys, [], GRAFEO_DB_PATH=str(tmp_path))
    assert "nothing was changed. GRAFEO_DB_PATH must name a database file" in err


def test_locked_database_is_one_line(monkeypatch, capsys, tmp_path):
    import grafeo

    path = str(tmp_path / "graph.grafeo")
    holder = grafeo.GrafeoDB(path)
    try:
        err = _startup_error(monkeypatch, capsys, [], GRAFEO_DB_PATH=path)
        assert "GRAFEO-S004" in err and "even read-only" in err
    finally:
        holder.close()


def test_port_in_use_is_one_line(monkeypatch, capsys):
    import socket

    from grafeo_mcp import server

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        calls = _record_run(monkeypatch)
        monkeypatch.undo()  # the real port check this time
        monkeypatch.setattr(server.mcp, "run", lambda transport, **kwargs: calls.append((transport, kwargs)))
        with pytest.raises(SystemExit) as exc:
            server.main(["streamable-http", "--port", str(port)])
    assert exc.value.code == 1 and calls == []
    assert capsys.readouterr().err.strip() == (
        f"grafeo-mcp: error: port {port} on 127.0.0.1 is already in use by another program: "
        "pass another one with --port."
    )


def test_main_serves_the_database_it_opened(monkeypatch, tmp_path):
    """main opens the database once, the lifespan serves that handle, and main closes it afterwards."""
    import asyncio

    from grafeo_mcp import server

    seen: list[object] = []

    def run(transport, **kwargs):
        async def enter_twice():  # the SDK enters the lifespan per stdio run and per SSE connection
            for _ in range(2):
                async with server.app_lifespan(server.mcp) as app:
                    seen.append(app)

        asyncio.run(enter_twice())

    _record_run(monkeypatch)
    monkeypatch.setattr(server.mcp, "run", run)
    monkeypatch.setenv("GRAFEO_DB_PATH", str(tmp_path / "graph.grafeo"))
    server.main([])
    assert len(seen) == 2 and seen[0] is seen[1]
    assert server._opened_by_main is None


def test_sentences_join_with_a_period():
    from grafeo_mcp.server import _sentences

    assert _sentences("nothing was changed", "Name a file.") == "nothing was changed. Name a file."
    assert _sentences("done.", "", "Next.") == "done. Next."


def test_main_selects_transport(monkeypatch):
    import sys

    from grafeo_mcp import server

    calls = _record_run(monkeypatch)
    for argv, expected in (
        (["grafeo-mcp"], ("stdio", {})),
        (["grafeo-mcp", "stdio"], ("stdio", {})),
        (["grafeo-mcp", "streamable-http"], ("streamable-http", {"host": "127.0.0.1", "port": 8000})),
        (["grafeo-mcp", "sse"], ("sse", {"host": "127.0.0.1", "port": 8000})),
    ):
        monkeypatch.setattr(sys, "argv", argv)
        server.main()
        assert calls[-1] == expected


def test_main_passes_host_and_port(monkeypatch, caplog):
    from grafeo_mcp import server

    calls = _record_run(monkeypatch)
    server.main(["streamable-http", "--port", "9100"])
    assert calls[-1] == ("streamable-http", {"host": "127.0.0.1", "port": 9100})
    assert "without authentication" not in caplog.text

    server.main(["streamable-http", "--host", "0.0.0.0", "--port", "9101"])
    assert calls[-1] == ("streamable-http", {"host": "0.0.0.0", "port": 9101})
    assert "without authentication" in caplog.text


@pytest.mark.parametrize(
    "argv",
    [["http"], ["--port", "9000"], ["stdio", "--host", "0.0.0.0"], ["streamable-http", "--port", "0"]],
)
def test_main_rejects_bad_arguments(monkeypatch, capsys, argv):
    """A typo or a stray flag stops with a message instead of starting a stdio server."""
    from grafeo_mcp import server

    calls = _record_run(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        server.main(argv)
    assert exc.value.code == 2
    assert "grafeo-mcp: error:" in capsys.readouterr().err
    assert calls == []


def test_main_version_and_help(monkeypatch, capsys):
    import grafeo

    from grafeo_mcp import server

    calls = _record_run(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        server.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"grafeo-mcp {server.__version__} (grafeo {grafeo.__version__})"

    with pytest.raises(SystemExit) as exc:
        server.main(["--help"])
    assert exc.value.code == 0
    assert "GRAFEO_DB_PATH" in capsys.readouterr().out
    assert calls == []


def test_server_info_has_version_and_instructions():
    from importlib.metadata import version

    from grafeo_mcp import server

    assert server.mcp.version == version("grafeo-mcp")
    assert server.mcp.instructions
    assert "graph_info" in server.mcp.instructions
    # Every tool the instructions name exists.
    import re

    tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}
    named = set(re.findall(r"\b([a-z]+(?:_[a-z]+)+)\b", server.mcp.instructions))
    named -= {"read_only"}
    assert named <= tool_names, named - tool_names


def test_in_memory_database_logs_a_warning(caplog):
    from grafeo_mcp.server import open_database

    db, engine_read_only = open_database(None, read_only=False)
    try:
        assert "data is lost when the server stops" in caplog.text
        assert engine_read_only is False
    finally:
        db.close()
