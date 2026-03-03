from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp
from grafeo_mcp.tools._helpers import _node_summary, _read_only_guard, _truncate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_SEARCH_RESULTS = 20

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_text_index(
    label: str,
    property: str,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Create a full-text search index on a string property.

    Call this once before using search_text on the same label + property pair.
    Existing nodes with the given label and property are indexed immediately;
    future nodes are indexed on insertion.

    Use this tool when: you want to enable keyword search on a text property.
    Do NOT use for: vector/embedding search (use create_vector_index).

    Args:
        label: Node label to index (e.g. "Article").
        property: String property to index (e.g. "title", "content").

    Returns:
        Confirmation string on success, or an error message.

    Examples:
        create_text_index("Article", "title")
        create_text_index("Document", "content")
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        db.create_text_index(label, property)
        return f"Text index created on :{label}.{property}."
    except Exception as exc:
        return f"create_text_index error: {exc}."


@mcp.tool()
def search_text(
    label: str,
    property: str,
    query: str,
    limit: int = _MAX_SEARCH_RESULTS,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Full-text keyword search over string properties.

    Finds nodes whose text property matches the search query. Requires a
    text index created via create_text_index on the same label + property.

    Use this tool when: you want to search for nodes by keyword or phrase.
    Do NOT use for: semantic/vector similarity (use vector_search), exact
    property matching (use execute_gql with WHERE), or browsing by label
    (use search_nodes_by_label).

    Args:
        label: Node label to search within (e.g. "Article").
        property: String property to search (e.g. "title").
        query: Search query string (keywords or phrase).
        limit: Maximum number of results to return (default 20).

    Returns:
        JSON array of {node_id, score, labels, properties} sorted by
        relevance score descending.

    Examples:
        search_text("Article", "title", "graph database")
        search_text("Document", "content", "machine learning", limit=10)
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        results = db.text_search(label, property, query, limit)

        output: list[dict[str, Any]] = []
        for node_id, score in results:
            entry: dict[str, Any] = {
                "node_id": node_id,
                "score": round(float(score), 6),
            }
            summary = _node_summary(db, node_id)
            entry["labels"] = summary.get("labels", [])
            entry["properties"] = summary.get("properties", {})
            output.append(entry)

        return _truncate(output)
    except Exception as exc:
        return (
            f"search_text error: {exc}. "
            f"Ensure a text index exists for :{label}.{property} "
            "(use create_text_index). Try graph_info to check available labels."
        )
