from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession
from pydantic import Field

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import (
    _is_engine_panic,
    _read_only_guard,
    _truncate,
    describe_exception,
    grafeo_tool,
    tool_error,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_BATCH_NODES = 500
_MAX_BATCH_EDGES = 1000

_TOOL = "batch_import"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _BatchError(Exception):
    """A problem with the batch itself, reported before anything is written."""


def _parse_ref(ref: Any, batch_size: int, edge_idx: int, field_name: str) -> tuple[str, int]:
    """Parse a node reference into ("batch", index) or ("id", node_id)."""
    if ref is None:
        raise _BatchError(f"edge at index {edge_idx} has no {field_name}")
    if isinstance(ref, bool):
        raise _BatchError(f"edge at index {edge_idx} has invalid {field_name} {ref!r}")
    if isinstance(ref, int):
        if ref < 0:
            raise _BatchError(f"edge at index {edge_idx} has negative {field_name} {ref}")
        return ("id", ref)
    if isinstance(ref, str) and ref.startswith("@"):
        try:
            batch_idx = int(ref[1:])
        except ValueError:
            raise _BatchError(
                f"edge at index {edge_idx} has invalid {field_name} '{ref}'. Use '@N' where N is a node array index"
            ) from None
        if not 0 <= batch_idx < batch_size:
            raise _BatchError(
                f"edge at index {edge_idx} references {field_name}='{ref}', "
                f"but node index {batch_idx} does not exist "
                f"(batch has {batch_size} nodes, indices 0-{batch_size - 1})"
            )
        return ("batch", batch_idx)
    try:
        node_id = int(ref)
    except (TypeError, ValueError):
        raise _BatchError(
            f"edge at index {edge_idx} has invalid {field_name} '{ref}'. Use an integer node ID or '@N' batch reference"
        ) from None
    if node_id < 0:
        raise _BatchError(f"edge at index {edge_idx} has negative {field_name} {node_id}")
    return ("id", node_id)


def _validate(db: Any, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[tuple]:
    """Check the whole batch and return the parsed edges; raises _BatchError."""
    for idx, node_spec in enumerate(nodes):
        if not isinstance(node_spec, dict):
            raise _BatchError(f"node at index {idx} is not an object with 'labels' and 'properties'")
        labels = node_spec.get("labels")
        if not labels:
            raise _BatchError(f"node at index {idx} has no labels. Every node needs at least one label")
        if not isinstance(labels, list) or not all(isinstance(label, str) and label for label in labels):
            raise _BatchError(f"node at index {idx} has invalid labels {labels!r}: use a list of non-empty strings")
        props = node_spec.get("properties")
        if props is not None and not isinstance(props, dict):
            raise _BatchError(f"node at index {idx} has properties that are not an object")

    parsed: list[tuple] = []
    for idx, edge_spec in enumerate(edges):
        if not isinstance(edge_spec, dict):
            raise _BatchError(f"edge at index {idx} is not an object")
        edge_type = edge_spec.get("edge_type")
        if not edge_type or not isinstance(edge_type, str):
            raise _BatchError(f"edge at index {idx} has no edge_type. Every edge needs an edge_type string")
        props = edge_spec.get("properties")
        if props is not None and not isinstance(props, dict):
            raise _BatchError(f"edge at index {idx} has properties that are not an object")
        source = _parse_ref(edge_spec.get("source_ref"), len(nodes), idx, "source_ref")
        target = _parse_ref(edge_spec.get("target_ref"), len(nodes), idx, "target_ref")
        for field_name, (kind, value) in (("source_ref", source), ("target_ref", target)):
            if kind == "id" and db.get_node(value) is None:
                raise _BatchError(f"edge at index {idx} has {field_name}={value}, but node {value} does not exist")
        parsed.append((source, target, edge_type, props))
    return parsed


def _rollback(db: Any, node_ids: list[int], edge_ids: list[int]) -> str | None:
    """Delete what a failed batch created; return a description of anything left behind."""
    leftovers: list[str] = []
    for edge_id in reversed(edge_ids):
        try:
            db.delete_edge(edge_id)
        except Exception:
            leftovers.append(f"edge {edge_id}")
    for node_id in reversed(node_ids):
        try:
            db.delete_node(node_id)
        except Exception:
            leftovers.append(f"node {node_id}")
    return ", ".join(leftovers) if leftovers else None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@grafeo_tool(read_only=False)
def batch_import(
    nodes: Annotated[
        list[dict[str, Any]],
        Field(description='Up to 500 objects: {"labels": ["Person"], "properties": {...}}.'),
    ],
    edges: Annotated[
        list[dict[str, Any]] | None,
        Field(
            description='Up to 1000 objects: {"source_ref": "@0", "target_ref": 42, "edge_type": "KNOWS", '
            '"properties": {...}}. A ref is "@N" (the Nth node of this batch) or an existing node ID.'
        ),
    ] = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Create many nodes and edges in one call, all or nothing.

    The whole batch is checked before anything is written, and undone if the engine rejects part of it.
    Returns created_nodes, created_edges and node_id_map (batch index to node ID).
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx, _TOOL):
        return ro
    edges = edges or []

    if len(nodes) > _MAX_BATCH_NODES:
        return tool_error(
            _TOOL,
            f"batch contains {len(nodes)} nodes, exceeding the limit of {_MAX_BATCH_NODES}",
            "split the data into smaller batches.",
        )
    if len(edges) > _MAX_BATCH_EDGES:
        return tool_error(
            _TOOL,
            f"batch contains {len(edges)} edges, exceeding the limit of {_MAX_BATCH_EDGES}",
            "split the data into smaller batches.",
        )

    db = ctx.request_context.lifespan_context.db
    try:
        parsed_edges = _validate(db, nodes, edges)
    except _BatchError as exc:
        return tool_error(_TOOL, f"{exc}; nothing was written", "fix the batch and send it again.")

    created_nodes: list[int] = []
    created_edges: list[int] = []
    step = "node at index 0"
    try:
        for idx, node_spec in enumerate(nodes):
            step = f"node at index {idx}"
            created_nodes.append(db.create_node(node_spec["labels"], node_spec.get("properties")).id)
        for idx, ((src_kind, src), (dst_kind, dst), edge_type, props) in enumerate(parsed_edges):
            step = f"edge at index {idx}"
            source_id = created_nodes[src] if src_kind == "batch" else src
            target_id = created_nodes[dst] if dst_kind == "batch" else dst
            created_edges.append(db.create_edge(source_id, target_id, edge_type, props).id)
    except BaseException as exc:
        if not isinstance(exc, Exception) and not _is_engine_panic(exc):
            raise
        leftovers = _rollback(db, created_nodes, created_edges)
        outcome = (
            "everything this call created was removed again"
            if leftovers is None
            else f"these could not be removed: {leftovers}"
        )
        return tool_error(
            _TOOL,
            f"the engine rejected the {step}: {describe_exception(exc)}; {outcome}",
            "check the schema and constraints with graph_info, fix the batch and send it again.",
        )

    payload = {
        "created_nodes": len(created_nodes),
        "created_edges": len(created_edges),
        "node_id_map": {str(idx): node_id for idx, node_id in enumerate(created_nodes)},
    }
    return _truncate(payload)
