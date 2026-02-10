from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import grafeo
from mcp.server.fastmcp import FastMCP


@dataclass
class AppContext:
    db: grafeo.GrafeoDB


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    db_path = os.environ.get("GRAFEO_DB_PATH")
    if db_path and os.path.exists(db_path):
        db = grafeo.GrafeoDB.open(db_path)
    elif db_path:
        db = grafeo.GrafeoDB(db_path)
    else:
        db = grafeo.GrafeoDB()  # in-memory
    try:
        yield AppContext(db=db)
    finally:
        db.close()


mcp = FastMCP("grafeo", lifespan=app_lifespan)


# Import tool/resource/prompt modules so they register on `mcp`.
import grafeo_mcp.prompts.templates  # noqa: E402
import grafeo_mcp.resources.nodes  # noqa: E402
import grafeo_mcp.resources.schema  # noqa: E402
import grafeo_mcp.tools.algorithms  # noqa: E402
import grafeo_mcp.tools.graph  # noqa: E402
import grafeo_mcp.tools.query  # noqa: E402
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
