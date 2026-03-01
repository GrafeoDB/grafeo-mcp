from __future__ import annotations

import json
import re

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_RESULT_ROWS = 100  # default cap before truncation

# Lightweight Cypher→GQL keyword mapping.  Only the most common clause-level
# differences are handled; anything deeper needs a real parser.
_CYPHER_TO_GQL = [
    (re.compile(r"\bCREATE\b", re.IGNORECASE), "INSERT"),
]


def _normalize_query(query: str) -> str:
    """Best-effort Cypher→GQL syntax normalization.

    Translates the most common Cypher keywords that differ from GQL so that
    AI agents trained predominantly on Cypher can use this tool without
    learning GQL-specific syntax.  Lightweight — no AST parsing.
    """
    for pattern, replacement in _CYPHER_TO_GQL:
        query = pattern.sub(replacement, query)
    return query


def _format_results(result, *, limit: int) -> str:
    """Convert a QueryResult into a JSON string, truncating if needed.

    Returns a JSON object with ``columns``, ``rows``, ``total_rows``, and an
    optional ``truncated`` flag with a human-readable note.
    """
    rows: list[dict] = []
    total = 0
    for row in result:
        total += 1
        if total <= limit:
            rows.append(row)

    payload: dict = {
        "columns": list(result.columns),
        "rows": rows,
        "total_rows": total,
    }

    if total > limit:
        payload["truncated"] = True
        payload["note"] = f"Showing first {limit} of {total} results. Use LIMIT in your query for more control."

    if result.execution_time_ms is not None:
        payload["execution_time_ms"] = round(result.execution_time_ms, 2)

    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def execute_gql(
    query: str,
    limit: int = _MAX_RESULT_ROWS,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Execute a GQL query against the graph database.

    GQL (Graph Query Language) is the ISO/IEC standard query language.
    Use MATCH patterns to find nodes and relationships, INSERT to add data,
    and RETURN to project results.

    Cypher syntax (e.g. CREATE) is automatically normalized to GQL (INSERT),
    so queries written in Cypher style will generally work as-is.

    Use this tool when: you need to run a custom query — complex filters,
    multi-hop traversals, aggregations, or mutations beyond what the CRUD
    tools (create_node, create_edge) provide.
    Do NOT use this for: simple node lookups (use get_node), label browsing
    (use search_nodes_by_label), or one-hop exploration (use get_neighbors).

    Args:
        query: A GQL query string (Cypher syntax is auto-normalized).
        limit: Maximum rows to return (default 100). Use to prevent
            overwhelming context windows. The query itself can also
            contain a LIMIT clause for server-side limiting.

    Examples:
        MATCH (p:Person) RETURN p.name, p.age
        MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name
        INSERT (:Person {name: 'Alice', age: 30})
        MATCH (p:Person) WHERE p.age > 25 RETURN p.name LIMIT 10
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        result = db.execute(_normalize_query(query))
        return _format_results(result, limit=limit)
    except Exception as exc:
        return (
            f"GQL query failed: {exc}. "
            "Try graph_info to check available labels and properties, "
            "or verify your GQL syntax."
        )
