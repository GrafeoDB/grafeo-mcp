from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import grafeo
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("grafeo_mcp")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass
class AppContext:
    db: grafeo.GrafeoDB
    read_only: bool
    engine_read_only: bool = False
    """True when the engine itself rejects writes (a ``.grafeo`` file opened
    with ``GrafeoDB.open_read_only``), not only the MCP tools."""


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def open_database(db_path: str | None, *, read_only: bool) -> tuple[grafeo.GrafeoDB, bool]:
    """Open the database for *db_path* and return it with its engine read-only flag.

    * No path: a fresh in-memory database.
    * A ``.grafeo`` file in read-only mode: opened with ``open_read_only``, so
      the engine rejects every write, other processes may read the same file,
      and grafeo 0.6 reads a file written by 0.5.x without migrating it.
    * Anything else: a read-write open, which creates the database if needed.
      A path ending in ``.grafeo`` is a single-file database; any other path is
      a WAL-directory database, which grafeo 0.5.x reopens without its vector,
      text and property indexes.
    """
    if not db_path:
        return grafeo.GrafeoDB(), False

    single_file = db_path.endswith(".grafeo")  # the engine's own (case-sensitive) rule
    try:
        if read_only and single_file and os.path.isfile(db_path):
            return grafeo.GrafeoDB.open_read_only(db_path), True
        if read_only:
            logger.warning(
                "GRAFEO_READ_ONLY is set but %s is not an existing .grafeo file, so it is opened read-write "
                "and only the MCP tools refuse writes.",
                db_path,
            )
        elif not single_file:
            logger.warning(
                "%s is a WAL-directory database. Prefer a single-file path ending in .grafeo: grafeo 0.5.x "
                "reopens directory databases without their vector, text and property indexes.",
                db_path,
            )
        return grafeo.GrafeoDB(db_path), False
    except grafeo.GrafeoError as exc:
        raise RuntimeError(f"grafeo-mcp could not open GRAFEO_DB_PATH={db_path!r}: {exc}") from exc


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    read_only = _env_flag("GRAFEO_READ_ONLY")
    db, engine_read_only = open_database(os.environ.get("GRAFEO_DB_PATH") or None, read_only=read_only)
    try:
        yield AppContext(db=db, read_only=read_only, engine_read_only=engine_read_only)
    finally:
        db.close()


mcp = FastMCP("grafeo", lifespan=app_lifespan)


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
