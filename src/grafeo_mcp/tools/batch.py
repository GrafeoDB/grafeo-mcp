from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp
from grafeo_mcp.tools._helpers import _read_only_guard, _truncate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_BATCH_NODES = 500
_MAX_BATCH_EDGES = 1000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_ref(
    ref: Any,
    node_id_map: dict[int, int],
    edge_idx: int,
    field_name: str,
) -> int | str:
    """Resolve a node reference to an actual node ID.

    Returns an int (the node ID) on success, or an error string on failure.
    """
    if ref is None:
        return f"Error: edge at index {edge_idx} has no {field_name}."
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str) and ref.startswith("@"):
        try:
            batch_idx = int(ref[1:])
        except ValueError:
            return (
                f"Error: edge at index {edge_idx} has invalid {field_name} "
                f"'{ref}'. Use '@N' where N is a node array index."
            )
        if batch_idx not in node_id_map:
            return (
                f"Error: edge at index {edge_idx} references {field_name}='{ref}', "
                f"but node index {batch_idx} does not exist "
                f"(batch has {len(node_id_map)} nodes, indices 0-{len(node_id_map) - 1})."
            )
        return node_id_map[batch_idx]
    try:
        return int(ref)
    except (TypeError, ValueError):
        return (
            f"Error: edge at index {edge_idx} has invalid {field_name} "
            f"'{ref}'. Use an integer node ID or '@N' batch reference."
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def batch_import(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Bulk-create nodes and edges from JSON arrays in a single call.

    Use this tool when: you need to import many nodes and edges at once,
    e.g. loading a dataset, building a graph from structured data, or
    ingesting extracted entities in bulk.
    Do NOT use for: creating a single node or edge (use create_node /
    create_edge), or updating existing data (use update_node / update_edge).

    Nodes are created first, then edges. Edges can reference nodes created
    in this batch using "@index" notation (e.g. "@0" refers to the first
    node in the nodes array).

    Note: this operation is not atomic. If an error occurs partway through,
    already-created nodes/edges remain in the graph.

    Args:
        nodes: List of node objects, each with:
            - labels: list of strings (required)
            - properties: dict of key-value pairs (optional)
        edges: List of edge objects, each with:
            - source_ref: int (existing node ID) or str ("@0", "@1", ...)
              referencing a node by its index in the nodes array
            - target_ref: int (existing node ID) or str ("@0", "@1", ...)
            - edge_type: str (required)
            - properties: dict of key-value pairs (optional)

    Returns:
        JSON with created_nodes count, created_edges count, and a
        node_id_map from batch index to actual node ID.

    Examples:
        batch_import(
            nodes=[
                {"labels": ["Person"], "properties": {"name": "Alice"}},
                {"labels": ["Person"], "properties": {"name": "Bob"}},
            ],
            edges=[
                {"source_ref": "@0", "target_ref": "@1", "edge_type": "KNOWS"},
            ],
        )
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        edges = edges or []

        if len(nodes) > _MAX_BATCH_NODES:
            return (
                f"Error: batch contains {len(nodes)} nodes, "
                f"exceeding the limit of {_MAX_BATCH_NODES}. "
                "Split into smaller batches."
            )
        if len(edges) > _MAX_BATCH_EDGES:
            return (
                f"Error: batch contains {len(edges)} edges, "
                f"exceeding the limit of {_MAX_BATCH_EDGES}. "
                "Split into smaller batches."
            )

        # --- Create nodes ---
        node_id_map: dict[int, int] = {}
        created_nodes = 0
        for idx, node_spec in enumerate(nodes):
            labels = node_spec.get("labels", [])
            if not labels:
                return f"Error: node at index {idx} has no labels. Every node needs at least one label."
            props = node_spec.get("properties")
            node = db.create_node(labels, props)
            node_id_map[idx] = node.id
            created_nodes += 1

        # --- Resolve edge references and create edges ---
        created_edges = 0
        for idx, edge_spec in enumerate(edges):
            source_ref = edge_spec.get("source_ref")
            target_ref = edge_spec.get("target_ref")
            edge_type = edge_spec.get("edge_type")
            props = edge_spec.get("properties")

            if not edge_type:
                return f"Error: edge at index {idx} has no edge_type. Every edge needs an edge_type string."

            source_id = _resolve_ref(source_ref, node_id_map, idx, "source_ref")
            if isinstance(source_id, str):
                return source_id
            target_id = _resolve_ref(target_ref, node_id_map, idx, "target_ref")
            if isinstance(target_id, str):
                return target_id

            db.create_edge(source_id, target_id, edge_type, props)
            created_edges += 1

        payload = {
            "created_nodes": created_nodes,
            "created_edges": created_edges,
            "node_id_map": {str(k): v for k, v in node_id_map.items()},
        }
        return _truncate(payload)
    except Exception as exc:
        return (
            f"Batch import failed: {exc}. "
            "Check that all node specs have 'labels' and all edge specs "
            "have 'source_ref', 'target_ref', and 'edge_type'. "
            "Try graph_info to verify the current state."
        )
