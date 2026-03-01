from __future__ import annotations

from collections import Counter

import grafeo
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.resources._helpers import _format_value
from grafeo_mcp.server import AppContext, mcp


def _build_connection_summary(db: grafeo.GrafeoDB, node_id: int) -> str:
    """Query outgoing and incoming edges to build a human-readable connection summary."""
    parts: list[str] = []

    # Outgoing edges
    out_types: Counter[str] = Counter()
    out_row_count = 0
    try:
        result = db.execute(f"MATCH (n)-[r]->(m) WHERE id(n) = {node_id} RETURN type(r), id(m) LIMIT 100")
        for row in result:
            out_types[str(row[0])] += 1
            out_row_count += 1
    except Exception:
        pass

    # Incoming edges
    in_types: Counter[str] = Counter()
    in_row_count = 0
    try:
        result = db.execute(f"MATCH (m)-[r]->(n) WHERE id(n) = {node_id} RETURN type(r), id(m) LIMIT 100")
        for row in result:
            in_types[str(row[0])] += 1
            in_row_count += 1
    except Exception:
        pass

    total = sum(out_types.values()) + sum(in_types.values())
    if total == 0:
        return "Connections: (isolated node, no edges)"

    parts.append(f"Connections: {total} total")

    if out_types:
        out_items = ", ".join(f"{t} ({c})" for t, c in out_types.most_common())
        line = f"  Outgoing: {out_items}"
        if out_row_count >= 100:
            line += " (showing first 100, node may have more)"
        parts.append(line)

    if in_types:
        in_items = ", ".join(f"{t} ({c})" for t, c in in_types.most_common())
        line = f"  Incoming: {in_items}"
        if in_row_count >= 100:
            line += " (showing first 100, node may have more)"
        parts.append(line)

    return "\n".join(parts)


@mcp.resource("graph://nodes/{node_id}")
def get_node_resource(node_id: str, ctx: Context[ServerSession, AppContext]) -> str:
    """Full details for a specific node: properties, labels, and a summary of its
    connections (edge types and counts). Gives an AI agent context about a node
    without needing separate neighbor queries."""
    db = ctx.request_context.lifespan_context.db

    try:
        nid = int(node_id)
    except ValueError:
        return f"Error: '{node_id}' is not a valid node ID (expected integer)"

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
