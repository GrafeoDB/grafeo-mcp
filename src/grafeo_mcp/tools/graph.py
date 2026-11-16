from __future__ import annotations

from typing import Annotated, Any

import grafeo
from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession
from pydantic import Field

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import (
    _NO_HISTORY_HINT,
    _POINT_HINT,
    AsOf,
    Properties,
    _read_only_guard,
    _truncate,
    check_range,
    compact_properties,
    describe_exception,
    grafeo_tool,
    index_overview,
    parse_time_point,
    to_json,
    tool_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_LABEL_RESULTS = 100  # default cap for search_nodes_by_label
_MAX_NEIGHBORS = 50  # default cap for get_neighbors

_DIRECTIONS = {
    "outgoing": "(a)-[r]->(b)",
    "incoming": "(a)<-[r]-(b)",
    "both": "(a)-[r]-(b)",
}

_FIND_NODE_HINT = "use search_nodes_by_label, get_neighbors or execute_gql to find valid node IDs."
_FIND_EDGE_HINT = "use get_neighbors (edge_id field) or execute_gql (RETURN id(r)) to find valid edge IDs."


def _node_to_dict(node) -> dict[str, Any]:
    """Serialize a GrafeoDB Node to a plain dict."""
    return {
        "id": node.id,
        "labels": list(node.labels),
        "properties": compact_properties(node.properties()),
    }


def _edge_to_dict(edge) -> dict[str, Any]:
    """Serialize a GrafeoDB Edge to a plain dict."""
    return {
        "id": edge.id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "edge_type": edge.edge_type,
        "properties": compact_properties(edge.properties()),
    }


def _db(ctx: Any) -> grafeo.GrafeoDB:
    return ctx.request_context.lifespan_context.db


def _schema_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """A label or edge type from ``db.schema()``, compact: properties as ``{name: type}``.

    A property seen with several types lists them as ``"INT64|STRING"``; an
    edge type's endpoints are ``"Person->Company"`` label pairs. Empty
    properties and endpoints are left out.
    """
    out: dict[str, Any] = {"name": entry["name"], "count": entry.get("count")}
    properties = {prop["name"]: "|".join(prop.get("types") or []) or "ANY" for prop in entry.get("properties") or []}
    if properties:
        out["properties"] = properties
    endpoints = [f"{ep.get('source') or '?'}->{ep.get('target') or '?'}" for ep in entry.get("endpoints") or []]
    if endpoints:
        out["endpoints"] = endpoints
    return out


def _count_edges(db: grafeo.GrafeoDB, node_id: int) -> int:
    rows = list(db.execute("MATCH (n)-[r]-() WHERE id(n) = $id RETURN count(DISTINCT r) AS c", {"id": node_id}))
    return int(rows[0]["c"]) if rows else 0


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@grafeo_tool(read_only=False)
def create_node(
    labels: Annotated[list[str], Field(description='One or more labels: ["Person"].')],
    properties: Properties = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Create one node and return it with its id.

    For many nodes use batch_import; to create only when missing, execute_gql with MERGE.
    A list of numbers is stored as a vector, so vector indexes pick it up.
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx, "create_node"):
        return ro
    try:
        node = _db(ctx).create_node(labels, properties)
        return to_json(_node_to_dict(node))
    except Exception as exc:
        return tool_error(
            "create_node",
            describe_exception(exc),
            "labels must be a list of strings; call graph_info to inspect the schema and constraints.",
        )


@grafeo_tool(read_only=False)
def create_edge(
    source_id: int,
    target_id: int,
    edge_type: Annotated[str, Field(description='Relationship type: "KNOWS".')],
    properties: Properties = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Create one directed edge from source_id to target_id (both must exist) and return it with its id."""
    assert ctx is not None
    if ro := _read_only_guard(ctx, "create_edge"):
        return ro
    if err := check_range("create_edge", source_id=(source_id, 0), target_id=(target_id, 0)):
        return err
    if not edge_type or not edge_type.strip():
        return tool_error("create_edge", "edge_type must be a non-empty string", 'use a type such as "KNOWS".')
    try:
        db = _db(ctx)
        for role, node_id in (("source", source_id), ("target", target_id)):
            if db.get_node(node_id) is None:
                return tool_error("create_edge", f"{role} node {node_id} does not exist", _FIND_NODE_HINT)
        edge = db.create_edge(source_id, target_id, edge_type, properties)
        return to_json(_edge_to_dict(edge))
    except Exception as exc:
        return tool_error(
            "create_edge",
            describe_exception(exc),
            "verify that both source_id and target_id exist (use get_node), and call graph_info to inspect the schema.",
        )


@grafeo_tool(read_only=True)
def get_node(
    node_id: int,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Get one node by ID: its labels and properties. Find IDs with search_nodes_by_label or execute_gql."""
    assert ctx is not None
    if err := check_range("get_node", node_id=(node_id, 0)):
        return err
    try:
        node = _db(ctx).get_node(node_id)
        if node is None:
            return tool_error(
                "get_node",
                f"node {node_id} not found",
                "use graph_info to check the node count, or search_nodes_by_label to find nodes.",
            )
        return to_json(_node_to_dict(node))
    except Exception as exc:
        return tool_error("get_node", describe_exception(exc), "node_id must be a non-negative integer.")


@grafeo_tool(read_only=True)
def get_node_as_of(
    node_id: int,
    as_of: AsOf,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Get a node's labels and properties as they were at as_of (time travel).

    Needs a server that keeps history (GRAFEO_HISTORY_RETENTION).
    """
    assert ctx is not None
    if err := check_range("get_node_as_of", node_id=(node_id, 0)):
        return err
    try:
        point = parse_time_point(as_of)
    except ValueError as exc:
        return tool_error("get_node_as_of", f"as_of={as_of!r} is not a point in time: {exc}", _POINT_HINT)
    db = _db(ctx)
    try:
        with db.as_of(point) as view:
            node = view.get_node(node_id)
        if node is None:
            return tool_error(
                "get_node_as_of",
                f"node {node_id} did not exist at {as_of}",
                "use get_node for the current state, or query_as_of to list the nodes that existed then.",
            )
        return to_json(_node_to_dict(node))
    except Exception as exc:
        hint = "node_id must be a non-negative integer."
        if "history" in str(exc).lower():
            hint = _NO_HISTORY_HINT
        return tool_error("get_node_as_of", describe_exception(exc), hint)


@grafeo_tool(read_only=True)
def search_nodes_by_label(
    label: str,
    limit: Annotated[int, Field(description="Page size.")] = _MAX_LABEL_RESULTS,
    offset: Annotated[int, Field(description="Nodes to skip, for the next page.")] = 0,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """List the nodes that have one label, with their properties, a page at a time. Filter with execute_gql."""
    assert ctx is not None
    if err := check_range("search_nodes_by_label", limit=(limit, 1), offset=(offset, 0)):
        return err
    try:
        nodes = _db(ctx).get_nodes_by_label(label, limit=limit, offset=offset)

        results = [{"node_id": node_id, "properties": compact_properties(props)} for node_id, props in nodes]

        payload: dict[str, Any] = {
            "label": label,
            "results": results,
            "count": len(results),
            "offset": offset,
            "limit": limit,
        }

        if len(results) == limit:
            payload["note"] = (
                f"Returned {limit} results (the limit). There may be more. "
                f"Use offset={offset + limit} to fetch the next page."
            )

        return _truncate(payload)
    except Exception as exc:
        return tool_error(
            "search_nodes_by_label",
            f"could not search label '{label}': {describe_exception(exc)}",
            "call graph_info to see which labels exist.",
        )


@grafeo_tool(read_only=True)
def graph_info(
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Overview of the graph; call it before querying.

    Returns node and edge counts; each label and edge type with its count and property types (and
    for edges the label pairs they connect); the vector, text and property indexes; and the database
    path (null in memory), whether writes are disabled, and the engine version.
    """
    assert ctx is not None
    try:
        app = ctx.request_context.lifespan_context
        db = app.db
        schema = db.schema()
        payload: dict[str, Any] = {
            "nodes": db.node_count,
            "edges": db.edge_count,
            "labels": [_schema_entry(entry) for entry in schema.get("labels", [])],
            "edge_types": [_schema_entry(entry) for entry in schema.get("edge_types", [])],
            "indexes": index_overview(db, list(schema.get("property_keys", []))),
            "database": {"path": db.path, "read_only": bool(app.read_only)},
            "engine": f"grafeo {grafeo.__version__}",
        }
        return _truncate(payload)
    except Exception as exc:
        return tool_error("graph_info", f"could not read database info: {describe_exception(exc)}")


@grafeo_tool(read_only=True)
def get_neighbors(
    node_id: int,
    direction: Annotated[str, Field(description='"outgoing", "incoming" or "both".')] = "both",
    edge_type: Annotated[str | None, Field(description="Follow only this edge type.")] = None,
    limit: Annotated[int, Field(description="Most edges to follow.")] = _MAX_NEIGHBORS,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """List the nodes one hop from node_id, each with the edge that links it (edge_id, edge_type).

    For longer paths use execute_gql.
    """
    assert ctx is not None
    pattern = _DIRECTIONS.get(direction)
    if pattern is None:
        return tool_error(
            "get_neighbors",
            f"direction must be 'outgoing', 'incoming' or 'both', got {direction!r}",
        )
    if err := check_range("get_neighbors", node_id=(node_id, 0), limit=(limit, 1)):
        return err
    try:
        db = _db(ctx)

        center = db.get_node(node_id)
        if center is None:
            return tool_error("get_neighbors", f"node {node_id} not found", _FIND_NODE_HINT)

        # Values travel as parameters, never as query text.
        params: dict[str, Any] = {"id": node_id, "limit": limit}
        type_filter = ""
        if edge_type:
            type_filter = " AND type(r) = $edge_type"
            params["edge_type"] = edge_type
        query = (
            f"MATCH {pattern} WHERE id(a) = $id{type_filter} "
            "RETURN id(b) AS nid, id(r) AS eid, type(r) AS rtype LIMIT $limit"
        )

        neighbors: list[dict[str, Any]] = []
        seen: set[int] = set()

        for row in db.execute(query, params):
            neighbor_id = row.get("nid")
            if neighbor_id is None or neighbor_id in seen:
                continue
            seen.add(neighbor_id)

            neighbor_node = db.get_node(neighbor_id)
            neighbor_info: dict[str, Any] = {
                "node_id": neighbor_id,
                "edge_id": row.get("eid"),
                "edge_type": row.get("rtype"),
            }
            if neighbor_node is not None:
                neighbor_info["labels"] = list(neighbor_node.labels)
                neighbor_info["properties"] = compact_properties(neighbor_node.properties())

            neighbors.append(neighbor_info)

        payload: dict[str, Any] = {
            "center_node": _node_to_dict(center),
            "direction": direction,
            "edge_type_filter": edge_type,
            "neighbors": neighbors,
            "count": len(neighbors),
            "limit": limit,
        }

        if len(neighbors) == limit:
            payload["note"] = (
                f"Returned {limit} neighbors (the limit). "
                "There may be more. Increase limit or use execute_gql "
                "for a full traversal query."
            )

        return _truncate(payload)

    except Exception as exc:
        return tool_error(
            "get_neighbors",
            f"could not read the neighbors of node {node_id}: {describe_exception(exc)}",
            "verify the node exists with get_node, or call graph_info to inspect the database.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def update_node(
    node_id: int,
    properties: Annotated[dict[str, Any], Field(description="Properties to set.")],
    merge: Annotated[bool, Field(description="Keep the properties not listed (true) or remove them.")] = True,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Set properties on an existing node and return it.

    Labels change with execute_gql (SET n:Label, REMOVE n:Label).
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx, "update_node"):
        return ro
    if err := check_range("update_node", node_id=(node_id, 0)):
        return err
    try:
        db = _db(ctx)
        node = db.get_node(node_id)
        if node is None:
            return tool_error("update_node", f"node {node_id} not found", _FIND_NODE_HINT)
        if not merge:
            for key in list(node.properties().keys()):
                if key not in properties:
                    db.remove_node_property(node_id, key)
        for key, value in properties.items():
            db.set_node_property(node_id, key, value)
        return to_json(_node_to_dict(db.get_node(node_id)))
    except Exception as exc:
        return tool_error(
            "update_node",
            f"could not update node {node_id}: {describe_exception(exc)}",
            "verify the node exists with get_node and check the schema with graph_info.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def delete_node(
    node_id: int,
    detach: Annotated[bool, Field(description="Also delete its edges (true), or fail when it has any.")] = True,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Delete one node, and with detach its edges, in one step."""
    assert ctx is not None
    if ro := _read_only_guard(ctx, "delete_node"):
        return ro
    if err := check_range("delete_node", node_id=(node_id, 0)):
        return err
    try:
        db = _db(ctx)
        node = db.get_node(node_id)
        if node is None:
            return tool_error("delete_node", f"node {node_id} not found", _FIND_NODE_HINT)
        labels_str = ", ".join(node.labels) if node.labels else "(unlabeled)"

        if not detach:
            edge_count = _count_edges(db, node_id)
            if edge_count:
                return tool_error(
                    "delete_node",
                    f"node {node_id} has {edge_count} connected edge(s)",
                    "use detach=True to delete the node and its edges, or delete the edges first with delete_edge.",
                )
            db.delete_node(node_id)
            return f"Deleted node {node_id} (:{labels_str})."

        result = db.execute("MATCH (n) WHERE id(n) = $id DETACH DELETE n", {"id": node_id})
        counters = result.counters or {}
        edges_deleted = int(counters.get("edges_deleted", 0))
        edge_note = f" and {edges_deleted} edge(s)" if edges_deleted else ""
        return f"Deleted node {node_id} (:{labels_str}){edge_note}."
    except Exception as exc:
        return tool_error(
            "delete_node",
            f"could not delete node {node_id}: {describe_exception(exc)}",
            "verify the node exists with get_node.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def update_edge(
    edge_id: int,
    properties: Annotated[dict[str, Any], Field(description="Properties to set.")],
    merge: Annotated[bool, Field(description="Keep the properties not listed (true) or remove them.")] = True,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Set properties on an existing edge and return it.

    The edge type cannot change: delete the edge and create a new one.
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx, "update_edge"):
        return ro
    if err := check_range("update_edge", edge_id=(edge_id, 0)):
        return err
    try:
        db = _db(ctx)
        edge = db.get_edge(edge_id)
        if edge is None:
            return tool_error("update_edge", f"edge {edge_id} not found", _FIND_EDGE_HINT)
        if not merge:
            for key in list(edge.properties().keys()):
                if key not in properties:
                    db.remove_edge_property(edge_id, key)
        for key, value in properties.items():
            db.set_edge_property(edge_id, key, value)
        return to_json(_edge_to_dict(db.get_edge(edge_id)))
    except Exception as exc:
        return tool_error(
            "update_edge",
            f"could not update edge {edge_id}: {describe_exception(exc)}",
            "verify the edge exists with get_neighbors or execute_gql.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def delete_edge(
    edge_id: int,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Delete one edge. Edge IDs come from get_neighbors (edge_id) or execute_gql (RETURN id(r) AS id)."""
    assert ctx is not None
    if ro := _read_only_guard(ctx, "delete_edge"):
        return ro
    if err := check_range("delete_edge", edge_id=(edge_id, 0)):
        return err
    try:
        db = _db(ctx)
        edge = db.get_edge(edge_id)
        if edge is None:
            return tool_error("delete_edge", f"edge {edge_id} not found", _FIND_EDGE_HINT)
        edge_type = edge.edge_type
        source_id = edge.source_id
        target_id = edge.target_id
        db.delete_edge(edge_id)
        return f"Deleted edge {edge_id} (:{edge_type} from node {source_id} to node {target_id})."
    except Exception as exc:
        return tool_error(
            "delete_edge",
            f"could not delete edge {edge_id}: {describe_exception(exc)}",
            "verify the edge exists with get_neighbors or execute_gql.",
        )
