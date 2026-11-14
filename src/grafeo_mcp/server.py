from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

import grafeo
from mcp.server.mcpserver import MCPServer

logger = logging.getLogger("grafeo_mcp")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass
class AppContext:
    db: grafeo.GrafeoDB
    read_only: bool
    engine_read_only: bool = False
    """True when the engine itself rejects writes (an existing database opened
    with ``GrafeoDB.open_read_only``), not only the MCP tools."""


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _env_history_retention() -> str | timedelta | None:
    """Parse GRAFEO_HISTORY_RETENTION: "off", "forever", or seconds as a number.

    The value is how far back the database keeps its history for time-travel
    reads (``query_as_of``, ``get_node_as_of``); None keeps the engine default.
    """
    raw = os.environ.get("GRAFEO_HISTORY_RETENTION", "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in ("off", "forever"):
        return low
    try:
        seconds = float(raw)
    except ValueError:
        raise RuntimeError(f"GRAFEO_HISTORY_RETENTION={raw!r} is not 'off', 'forever' or a number of seconds") from None
    if seconds <= 0:
        raise RuntimeError(f"GRAFEO_HISTORY_RETENTION must be positive, got {raw!r}")
    return timedelta(seconds=seconds)


def open_database(
    db_path: str | None,
    *,
    read_only: bool,
    history_retention: str | timedelta | None = None,
) -> tuple[grafeo.GrafeoDB, bool]:
    """Open the database for *db_path* and return it with its engine read-only flag.

    * No path: a fresh in-memory database.
    * Read-only mode and an existing database: opened with ``open_read_only``,
      so the engine rejects every write, other processes may read the same
      database, and a 0.5.x database is read as it is, without migrating it.
    * Anything else: a read-write open. grafeo 0.6 keeps a database in a single
      file at the path, whatever its extension (its WAL lives in
      ``<path>.wal/`` while it is open), and creates it when nothing exists
      there. The first read-write open of a 0.5.x database (a ``.grafeo`` file
      or a WAL directory) migrates it and keeps the original as
      ``<path>.pre-0.6``.

    *history_retention* ("off", "forever" or a timedelta) is passed to a
    read-write open, so the database keeps the history that time-travel reads
    (``query_as_of``, ``get_node_as_of``) need; a database file stores it, and
    an engine read-only open keeps the stored one.
    """
    if not db_path:
        return grafeo.GrafeoDB(history_retention=history_retention), False

    try:
        if read_only and os.path.exists(db_path):
            return grafeo.GrafeoDB.open_read_only(db_path), True
        if read_only:
            logger.warning(
                "GRAFEO_READ_ONLY is set but there is no database at %s yet, so a new one is created read-write "
                "and only the MCP tools refuse writes.",
                db_path,
            )
        pre_06 = f"{db_path}.pre-0.6"
        had_pre_06 = os.path.exists(pre_06)
        db = grafeo.GrafeoDB(db_path, history_retention=history_retention)
        if not had_pre_06 and os.path.exists(pre_06):
            logger.warning(
                "Migrated the grafeo 0.5.x database at %s to the grafeo 0.6 format. The original is kept unchanged "
                "at %s; grafeo 0.5.x cannot open the migrated database.",
                db_path,
                pre_06,
            )
        return db, False
    except grafeo.GrafeoError as exc:
        hint = ""
        if os.path.isdir(db_path):
            hint = (
                " GRAFEO_DB_PATH must name a database file, such as a graph.grafeo inside that directory: "
                "grafeo 0.6 opens a directory only when it holds a 0.5.x database, to migrate it."
            )
        raise RuntimeError(f"grafeo-mcp could not open GRAFEO_DB_PATH={db_path!r}: {exc}{hint}") from exc


_current_app: AppContext | None = None


class AppContextView:
    """Context-shaped view of the AppContext: static resources cannot take a
    Context parameter in mcp 2.x, so they read this from the lifespan."""

    def __init__(self, app: AppContext) -> None:
        from types import SimpleNamespace

        self.request_context = SimpleNamespace(lifespan_context=app)


def current_app() -> AppContextView:
    """The app context of the running server, shaped like a Context."""
    assert _current_app is not None, "the server lifespan is not running"
    return AppContextView(_current_app)


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncGenerator[AppContext]:
    global _current_app
    read_only = _env_flag("GRAFEO_READ_ONLY")
    db, engine_read_only = open_database(
        os.environ.get("GRAFEO_DB_PATH") or None,
        read_only=read_only,
        history_retention=_env_history_retention(),
    )
    _current_app = AppContext(db=db, read_only=read_only, engine_read_only=engine_read_only)
    try:
        yield _current_app
    finally:
        db.close()
        _current_app = None


mcp = MCPServer("grafeo", lifespan=app_lifespan)


# Import tool/resource/prompt modules so they register on `mcp`.
import grafeo_mcp.prompts.templates  # noqa: E402
import grafeo_mcp.resources.nodes  # noqa: E402
import grafeo_mcp.resources.schema  # noqa: E402
import grafeo_mcp.tools.algorithms  # noqa: E402
import grafeo_mcp.tools.batch  # noqa: E402
import grafeo_mcp.tools.graph  # noqa: E402
import grafeo_mcp.tools.query  # noqa: E402
import grafeo_mcp.tools.search  # noqa: E402
import grafeo_mcp.tools.vector  # noqa: E402, F401


def main():
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if arg == "sse":
        mcp.run(transport="sse")
    elif arg == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
