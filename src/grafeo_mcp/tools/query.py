from __future__ import annotations

import itertools
import json
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._gql import scan_query
from grafeo_mcp.tools._helpers import check_range, describe_exception, grafeo_tool, tool_error

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_RESULT_ROWS = 100  # default cap before truncation

_QUERY_HINT = "check the query syntax, and call graph_info to see the labels, edge types and property keys that exist."


def _format_results(result: Any, *, limit: int, include_counters: bool = False) -> str:
    """Convert a QueryResult into a JSON string, keeping at most *limit* rows.

    Returns a JSON object with ``columns``, ``rows`` and ``total_rows``, a
    ``truncated`` flag and ``note`` when rows were left out, ``counters`` when
    the query wrote anything (or *include_counters* is set) and
    ``execution_time_ms`` when the engine reports it.
    """
    total = len(result)
    rows = list(itertools.islice(iter(result), limit))

    payload: dict[str, Any] = {
        "columns": list(result.columns),
        "rows": rows,
        "total_rows": total,
    }

    if total > limit:
        payload["truncated"] = True
        payload["note"] = f"Showing first {limit} of {total} results. Use LIMIT in your query for more control."

    counters = dict(getattr(result, "counters", None) or {})
    if include_counters or any(counters.values()):
        payload["counters"] = counters

    if result.execution_time_ms is not None:
        payload["execution_time_ms"] = round(result.execution_time_ms, 2)

    return json.dumps(payload, default=str)


def _run_read_only(db: Any, query: str, params: dict[str, Any] | None) -> tuple[Any, bool]:
    """Run *query* in a transaction that is always rolled back.

    Returns the result and whether the query wrote anything (by its counters).
    This backs up the keyword check in read-only mode: whatever the query
    changes in the graph is undone.
    """
    tx = db.begin_transaction()
    try:
        result = tx.execute(query, params)
    finally:
        tx.rollback()
    wrote = any((getattr(result, "counters", None) or {}).values())
    return result, wrote


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@grafeo_tool(read_only=False, destructive=True)
def execute_gql(
    query: str,
    limit: int = _MAX_RESULT_ROWS,
    params: dict[str, Any] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Execute one GQL query against the graph database.

    GQL (ISO/IEC 39075) is the standard graph query language. Use MATCH
    patterns to find nodes and relationships, INSERT (or CREATE) to add data,
    SET / REMOVE / DELETE to change it, and RETURN to project results. Common
    Cypher syntax such as CREATE, MERGE, OPTIONAL MATCH and DETACH DELETE is
    accepted as written.

    Use this tool when: you need a custom query: complex filters, multi-hop
    traversals, aggregations, or mutations beyond what the CRUD tools
    (create_node, create_edge, update_node, ...) provide.
    Do NOT use this for: simple node lookups (use get_node), label browsing
    (use search_nodes_by_label), or one-hop exploration (use get_neighbors).

    Rules:
        - One statement per call. Text with several statements separated by
          ';' is rejected (a single trailing ';' is fine): send them as
          separate calls, or chain clauses in one statement
          (INSERT ... INSERT ..., or MATCH ... INSERT ...).
        - Pass values through params instead of pasting them into the query
          text: "MATCH (p:Person {name: $name}) RETURN p" with
          params={"name": "Alice"}. Every $parameter the query uses must be
          in params.
        - Store embeddings through params ("INSERT (:Doc {emb: $emb})") or
          vector([...]): a plain list literal in the query text is stored as
          a list, which vector indexes skip.
        - In read-only mode (GRAFEO_READ_ONLY=1) only reading queries run;
          queries with INSERT, CREATE, MERGE, SET, REMOVE, DELETE, DROP or
          ALTER are refused.

    Args:
        query: One GQL statement (Cypher-style syntax is accepted).
        limit: Maximum rows to return (default 100). The query itself can
            also contain a LIMIT clause for server-side limiting.
        params: Optional query parameters, referenced as $name in the query.

    Returns:
        JSON with columns, rows (each row maps column name to value; nodes
        and edges appear as maps with _id, _labels or _type, and their
        properties), total_rows, counters (nodes/edges/properties/labels
        created, deleted, set or removed) when the query wrote anything, and
        truncated/note when rows were left out.

    Examples:
        MATCH (p:Person) RETURN p.name, p.age
        MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name
        INSERT (:Person {name: 'Alice', age: 30})
        MERGE (p:Person {name: $name}) SET p += $props RETURN id(p)
            with params={"name": "Alice", "props": {"age": 31}}
        MATCH (p:Person) WHERE p.age > $min RETURN p.name LIMIT 10
            with params={"min": 25}
    """
    assert ctx is not None
    if err := check_range("execute_gql", limit=(limit, 1)):
        return err

    scan = scan_query(query)
    if scan.statements == 0:
        return tool_error(
            "execute_gql", "the query is empty", "send one GQL statement, e.g. MATCH (n) RETURN n LIMIT 10."
        )
    if scan.statements > 1:
        return tool_error(
            "execute_gql",
            f"the query holds {scan.statements} statements separated by ';', but execute_gql runs one per call",
            "send each statement in its own execute_gql call, or chain the clauses in one statement "
            "(INSERT ... INSERT ..., MATCH ... INSERT ...).",
        )
    missing = sorted(scan.parameters - set(params or {}))
    if missing:
        names = ", ".join(f"${name}" for name in missing)
        return tool_error(
            "execute_gql",
            f"the query uses {names}, but params does not supply {'it' if len(missing) == 1 else 'them'}",
            'pass every parameter in params, e.g. params={"' + missing[0] + '": ...}.',
        )

    app = ctx.request_context.lifespan_context
    if app.read_only and scan.writes:
        return tool_error(
            "execute_gql",
            "the server is in read-only mode (GRAFEO_READ_ONLY=1) and the query contains "
            + ", ".join(scan.write_keywords),
            "only reading queries (MATCH ... RETURN, SHOW, CALL of read-only procedures) run in read-only mode.",
        )

    try:
        if app.read_only:
            result, wrote = _run_read_only(app.db, query, params)
            if wrote:
                return tool_error(
                    "execute_gql",
                    "the server is in read-only mode (GRAFEO_READ_ONLY=1) and the query tried to write; "
                    "its changes were rolled back",
                    "only reading queries run in read-only mode.",
                )
        else:
            result = app.db.execute(query, params)
        return _format_results(result, limit=limit, include_counters=scan.writes)
    except Exception as exc:
        return tool_error("execute_gql", f"query failed: {describe_exception(exc)}", _QUERY_HINT)
