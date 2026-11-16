from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession
from pydantic import Field

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import (
    _node_summary,
    _read_only_guard,
    _truncate,
    check_range,
    describe_exception,
    grafeo_tool,
    tool_error,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_SEARCH_RESULTS = 20

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@grafeo_tool(read_only=False, idempotent=True)
def create_text_index(
    label: str,
    property: Annotated[str, Field(description='A string property, e.g. "title".')],
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Create a full-text (BM25) index on a string property, for search_text. Existing and later nodes are indexed."""
    assert ctx is not None
    if ro := _read_only_guard(ctx, "create_text_index"):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        db.create_text_index(label, property)
        return f"Text index created on :{label}.{property}."
    except Exception as exc:
        return tool_error("create_text_index", describe_exception(exc), "call graph_info to check labels.")


@grafeo_tool(read_only=True)
def search_text(
    label: str,
    property: Annotated[str, Field(description="A property with a text index (create_text_index).")],
    query: Annotated[str, Field(description="Keywords or a phrase.")],
    limit: Annotated[int, Field(description="Most results to return.")] = _MAX_SEARCH_RESULTS,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Keyword search (BM25) in a text-indexed property. Returns [{node_id, score, labels, properties}], best first."""
    assert ctx is not None
    if err := check_range("search_text", limit=(limit, 1)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        results = db.text_search(label, property, query, limit)

        output: list[dict[str, Any]] = []
        for node_id, score in results:
            summary = _node_summary(db, node_id)
            output.append(
                {
                    "node_id": node_id,
                    "score": round(float(score), 6),
                    "labels": summary.get("labels", []),
                    "properties": summary.get("properties", {}),
                }
            )

        return _truncate(output)
    except Exception as exc:
        return tool_error(
            "search_text",
            describe_exception(exc),
            f"make sure a text index exists for :{label}.{property} (graph_info lists them under "
            "indexes.text; create one with create_text_index).",
        )
