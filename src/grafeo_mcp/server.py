from __future__ import annotations

import errno
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import grafeo
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool
from pydantic import ValidationError

logger = logging.getLogger("grafeo_mcp")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("grafeo-mcp")
    except PackageNotFoundError:  # pragma: no cover - running from a bare source tree
        return "0+unknown"


__version__ = _package_version()

INSTRUCTIONS = """\
grafeo-mcp gives you a Grafeo graph database: nodes with labels and properties, joined by directed, typed edges.

Start with graph_info: it lists the labels, edge types and property names with their types, and the vector and \
text indexes, so queries use names that exist. Node and edge IDs are integers.

- One node or edge: create_node, create_edge, get_node, update_node, delete_node, update_edge, delete_edge.
- Browse: search_nodes_by_label (one label), get_neighbors (one hop).
- Many nodes and edges at once: batch_import.
- Anything else (multi-hop patterns, filters, aggregations, MERGE upserts, label changes): execute_gql.
- Search: search_text needs create_text_index; vector_search, mmr_search and vector_graph_search need \
create_vector_index.
- Analysis: pagerank, betweenness_centrality, louvain, connected_components, dijkstra.
- History: query_as_of, get_node_as_of (only when the server keeps history).

A failed call returns "Error: <tool>: ... Hint: ..."; follow the hint. graph_info's database.read_only is true \
when writes are disabled."""


def compact_schema(schema: Any) -> Any:
    """Drop what a JSON schema from pydantic carries for humans and not for agents.

    Removes the generated ``title`` of every schema, turns an optional
    ``anyOf: [X, null]`` with a null default into plain ``X`` (the argument is
    simply left out), and drops ``additionalProperties: true`` (the default).
    Property names are kept, even one called ``title``.
    """
    if isinstance(schema, list):
        return [compact_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "additionalProperties" and value is True:
            continue
        if key in ("properties", "$defs", "definitions") and isinstance(value, dict):
            out[key] = {name: compact_schema(sub) for name, sub in value.items()}
        else:
            out[key] = compact_schema(value)
    variants = out.get("anyOf")
    if isinstance(variants, list) and "default" in out and out["default"] is None:
        non_null = [v for v in variants if v != {"type": "null"}]
        if len(non_null) == 1 and len(non_null) < len(variants):
            merged = {k: v for k, v in out.items() if k not in ("anyOf", "default")}
            merged.update(non_null[0])
            return merged
    return out


class GrafeoMCPServer(MCPServer):
    """MCPServer that lists tools with compact input schemas (see :func:`compact_schema`)."""

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema = compact_schema(tool.input_schema)
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        """Report arguments that fail validation in the tools' own error format.

        The SDK would answer ``Error executing tool get_node: 1 validation error
        for get_nodeArguments ...`` with a pydantic URL; this gives
        ``Error: get_node: node_id: input should be a valid integer (got 'abc'). Hint: ...``.
        """
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            from grafeo_mcp.tools._helpers import tool_error

            if isinstance(exc.__cause__, ValidationError):
                text = tool_error(
                    name,
                    _describe_validation(exc.__cause__),
                    "check the argument names and types in the tool's input schema.",
                )
            elif self._tool_manager.get_tool(name) is None:
                text = tool_error(name, "there is no tool of that name", "list the tools again; graph_info is a start.")
            else:
                raise
            return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


def _describe_validation(error: ValidationError, most: int = 3) -> str:
    """``node_id: input should be a valid integer (got 'abc'); limit: field required``, for the first few errors."""
    parts: list[str] = []
    for item in error.errors()[:most]:
        where = ".".join(str(part) for part in item.get("loc", ()) if part != "arguments") or "arguments"
        message = str(item.get("msg", "invalid value"))
        message = message[:1].lower() + message[1:]
        if item.get("type") != "missing" and "input" in item:
            shown = repr(item["input"])
            message += f" (got {shown if len(shown) <= 40 else shown[:37] + '...'})"
        parts.append(f"{where}: {message}")
    if len(error.errors()) > most:
        parts.append(f"and {len(error.errors()) - most} more")
    return "; ".join(parts)


@dataclass
class AppContext:
    db: grafeo.GrafeoDB
    read_only: bool
    engine_read_only: bool = False
    """True when the engine itself rejects writes (an existing database opened
    with ``GrafeoDB.open_read_only``), not only the MCP tools."""


class StartupError(RuntimeError):
    """A configuration or database problem that stops the server before it serves.

    ``main`` prints it as one line and exits with status 1, instead of the
    nested traceback an error inside the server's lifespan would give.
    """


def _sentences(*parts: str) -> str:
    """Join message parts as sentences: each ends with a period before the next starts."""
    text = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if text and not text.endswith((".", "!", "?", ":")):
            text += "."
        text = f"{text} {part}" if text else part
    return text


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
    expected = "use off, forever or a number of seconds above 0, such as 86400 for a day"
    try:
        seconds = float(raw)
    except ValueError:
        raise StartupError(f"GRAFEO_HISTORY_RETENTION={raw!r} is not valid: {expected}.") from None
    if not seconds > 0 or seconds == float("inf"):
        raise StartupError(f"GRAFEO_HISTORY_RETENTION={raw!r} is not valid: {expected}.")
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
        logger.warning(
            "GRAFEO_DB_PATH is not set, so the database is in memory and its data is lost when the server stops. "
            "Set GRAFEO_DB_PATH to a file such as graph.grafeo to keep it."
        )
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
                "GRAFEO_DB_PATH must name a database file, such as a graph.grafeo inside that directory: "
                "grafeo 0.6 opens a directory only when it holds a 0.5.x database, to migrate it."
            )
        elif "locked" in str(exc).lower():
            hint = (
                "A database another process holds cannot be opened, even read-only; "
                "several GRAFEO_READ_ONLY=1 servers can share a file only while nothing has it open for writing."
            )
        raise StartupError(_sentences(f"could not open GRAFEO_DB_PATH={db_path!r}: {exc}", hint)) from exc


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


def open_app_from_env() -> AppContext:
    """Read the GRAFEO_* environment variables and open the database they name.

    Raises StartupError for a bad setting or a database that cannot be opened.
    """
    read_only = _env_flag("GRAFEO_READ_ONLY")
    history_retention = _env_history_retention()
    db, engine_read_only = open_database(
        os.environ.get("GRAFEO_DB_PATH") or None,
        read_only=read_only,
        history_retention=history_retention,
    )
    return AppContext(db=db, read_only=read_only, engine_read_only=engine_read_only)


_opened_by_main: AppContext | None = None
"""The app ``main`` opened before starting the server; the lifespan serves it."""


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncGenerator[AppContext]:
    """Serve the database ``main`` opened, or open one (a server run without ``main``, as in tests).

    The SDK enters the lifespan once per stdio run and once per legacy SSE
    connection, so a database ``main`` opened stays open across them and
    ``main`` closes it when the server stops.
    """
    global _current_app
    if _opened_by_main is not None:
        _current_app = _opened_by_main
        try:
            yield _current_app
        finally:
            _current_app = None
        return
    app = open_app_from_env()
    _current_app = app
    try:
        yield app
    finally:
        app.db.close()
        _current_app = None


mcp = GrafeoMCPServer(
    "grafeo",
    title="Grafeo",
    version=__version__,
    instructions=INSTRUCTIONS,
    website_url="https://grafeo.dev/",
    lifespan=app_lifespan,
)


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

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _parse_args(argv: list[str] | None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="grafeo-mcp",
        description=(
            "MCP server for a Grafeo graph database. Configure it with environment variables: GRAFEO_DB_PATH "
            "(database file; in memory when unset), GRAFEO_READ_ONLY and GRAFEO_HISTORY_RETENTION."
        ),
    )
    parser.add_argument(
        "transport",
        nargs="?",
        default="stdio",
        choices=["stdio", "streamable-http", "sse"],
        help="stdio (default) for clients that start the server; streamable-http serves http://HOST:PORT/mcp; "
        "sse is the legacy HTTP transport",
    )
    parser.add_argument("--host", help="address the HTTP transports listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port of the HTTP transports (default 8000)")
    parser.add_argument(
        "--version",
        action="version",
        version=f"grafeo-mcp {__version__} (grafeo {grafeo.__version__})",
    )
    args = parser.parse_args(argv)
    if args.transport == "stdio" and (args.host is not None or args.port is not None):
        parser.error("--host and --port apply to the streamable-http and sse transports, not stdio")
    if args.port is not None and not 0 < args.port < 65536:
        parser.error(f"--port must be between 1 and 65535, got {args.port}")
    return args


def _check_port_free(host: str, port: int) -> None:
    """Raise StartupError when *host*:*port* cannot be bound (in use, or not an address of this machine)."""
    import socket

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise StartupError(
            f"--host {host!r} is not an address this machine can listen on: {exc.strerror or exc}."
        ) from None
    family, _, _, _, address = infos[0]
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if os.name == "nt":
            # Windows lets SO_REUSEADDR bind a port another process holds; exclusive use reports it.
            probe.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        try:
            probe.bind(address)
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, 10048, 10013):  # 10048/10013: WSAEADDRINUSE, WSAEACCES on Windows
                raise StartupError(
                    f"port {port} on {host} is already in use by another program: pass another one with --port."
                ) from None
            raise StartupError(f"cannot listen on {host}:{port}: {exc.strerror or exc}.") from None


def _fail(message: str) -> None:
    print(f"grafeo-mcp: error: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    global _opened_by_main
    args = _parse_args(argv)
    host = args.host or "127.0.0.1"
    port = args.port or 8000
    try:
        if args.transport != "stdio":
            _check_port_free(host, port)
        _opened_by_main = open_app_from_env()
    except StartupError as exc:
        _fail(str(exc))

    try:
        if args.transport == "stdio":
            mcp.run(transport="stdio")
            return
        if host not in _LOOPBACK_HOSTS:
            logger.warning(
                "grafeo-mcp listens on %s:%d without authentication: any client that reaches this address can "
                "read and change the database. Put it behind an authenticating proxy, or set GRAFEO_READ_ONLY=1.",
                host,
                port,
            )
        if args.transport == "sse":
            mcp.run(transport="sse", host=host, port=port)
        else:
            mcp.run(transport="streamable-http", host=host, port=port)
    finally:
        app, _opened_by_main = _opened_by_main, None
        if app is not None:
            app.db.close()


if __name__ == "__main__":
    main()
