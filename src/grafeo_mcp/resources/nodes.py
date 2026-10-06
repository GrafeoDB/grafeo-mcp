from __future__ import annotations

from collections import Counter

import grafeo
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.resources._helpers import _format_value
from grafeo_mcp.server import AppContext, mcp

_CONNECTION_SAMPLE = 100

# Query rows are dicts keyed by column name, so every column is aliased.
_OUTGOING = "MATCH (n)-[r]->(m) WHERE id(n) = $id RETURN type(r) AS edge_type LIMIT $limit"
_INCOMING = "MATCH (m)-[r]->(n) WHERE id(n) = $id RETURN type(r) AS edge_type LIMIT $limit"


def _edge_type_counts(db: grafeo.GrafeoDB, query: str, node_id: int) -> tuple[Counter[str], int]:
    counts: Counter[str] = Counter()
    rows = 0
    for row in db.execute(query, {"id": node_id, "limit": _CONNECTION_SAMPLE}):
        counts[str(row["edge_type"])] += 1
        rows += 1
    return counts, rows


def _build_connection_summary(db: grafeo.GrafeoDB, node_id: int) -> str:
    """Query outgoing and incoming edges to build a human-readable connection summary."""
    out_types, out_rows = _edge_type_counts(db, _OUTGOING, node_id)
    in_types, in_rows = _edge_type_counts(db, _INCOMING, node_id)

    total = sum(out_types.values()) + sum(in_types.values())
    if total == 0:
        return "Connections: (isolated node, no edges)"

    parts = [f"Connections: {total} total"]
    for direction, types, rows in (("Outgoing", out_types, out_rows), ("Incoming", in_types, in_rows)):
        if not types:
            continue
        line = f"  {direction}: " + ", ".join(f"{t} ({c})" for t, c in types.most_common())
        if rows >= _CONNECTION_SAMPLE:
            line += f" (showing first {_CONNECTION_SAMPLE}, node may have more)"
        parts.append(line)

    return "\n".join(parts)


def get_node_resource(node_id: str, ctx: Context[ServerSession, AppContext]) -> str:
    """Full details for a specific node: properties, labels, and a summary of its
    connections (edge types and counts). Gives an AI agent context about a node
    without needing separate neighbor queries."""
    db = ctx.request_context.lifespan_context.db

    try:
        nid = int(node_id)
    except ValueError:
        return f"Error: '{node_id}' is not a valid node ID (expected integer)"
    if nid < 0:
        return f"Error: '{node_id}' is not a valid node ID (expected a non-negative integer)"

    node = db.get_node(nid)
    if node is None:
        return f"Error: Node {node_id} not found"

    parts: list[str] = []

    # Identity
    labels_str = ", ".join(node.labels) if node.labels else "(unlabeled)"
    parts.append(f"Node {nid}")
    parts.append(f"Labels: {labels_str}")

    # Properties
    props = node.properties()
    parts.append("")
    if props:
        parts.append("Properties:")
        for key in sorted(props.keys()):
            parts.append(f"  {key}: {_format_value(props[key])}")
    else:
        parts.append("Properties: (none)")

    # Connection summary
    parts.append("")
    parts.append(_build_connection_summary(db, nid))

    return "\n".join(parts)


# FastMCP validates template arguments with pydantic, which rebuilds a
# Context[ServerSession, AppContext] argument without its request (mcp 1.26),
# so a template that takes ctx fails on every read. The registered function
# takes only the URI parameter and fetches the request context itself.


@mcp.resource(
    "graph://nodes/{node_id}", name="get_node_resource", description=get_node_resource.__doc__, mime_type="text/plain"
)
def _node_resource(node_id: str) -> str:
    return get_node_resource(node_id, mcp.get_context())
