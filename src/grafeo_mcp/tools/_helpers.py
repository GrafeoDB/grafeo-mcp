from __future__ import annotations

import json
from typing import Any

_MAX_RESULT_CHARS = 8_000
"""Soft ceiling for serialised tool output.  When a JSON result exceeds this
length the helper below truncates it so the LLM context window is not wasted
on thousands of identical embedding rows."""


def _truncate(payload: Any, *, limit: int = _MAX_RESULT_CHARS) -> str:
    """Serialise *payload* to compact JSON, truncating if it exceeds *limit*.

    Returns a plain string that is safe to hand back to the MCP caller.
    """
    text = json.dumps(payload, default=str, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated: {len(text)} chars total)"


def _node_summary(db: Any, node_id: int) -> dict[str, Any]:
    """Fetch a node and return a lightweight dict (id + labels + properties)."""
    node = db.get_node(node_id)
    if node is None:
        return {"node_id": node_id, "error": "node not found"}
    props = node.properties()
    # Drop large vector/embedding properties from the summary so we don't
    # blow up the output with thousands of floats.
    props = {k: v for k, v in props.items() if not (isinstance(v, list) and len(v) > 32)}
    return {"node_id": node_id, "labels": node.labels, "properties": props}
