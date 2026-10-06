from __future__ import annotations

import json
from typing import Any

import grafeo
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import (
    _read_only_guard,
    check_range,
    describe_exception,
    grafeo_tool,
    index_overview,
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
        "properties": node.properties(),
    }


def _edge_to_dict(edge) -> dict[str, Any]:
    """Serialize a GrafeoDB Edge to a plain dict."""
    return {
        "id": edge.id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "edge_type": edge.edge_type,
        "properties": edge.properties(),
    }


def _db(ctx: Any) -> grafeo.GrafeoDB:
    return ctx.request_context.lifespan_context.db


def _count_edges(db: grafeo.GrafeoDB, node_id: int) -> int:
    rows = list(db.execute("MATCH (n)-[r]-() WHERE id(n) = $id RETURN count(DISTINCT r) AS c", {"id": node_id}))
    return int(rows[0]["c"]) if rows else 0


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@grafeo_tool(read_only=False)
def create_node(
    labels: list[str],
    properties: dict[str, Any] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Create a new node in the graph with the given labels and properties.

    Use this tool when: you need to add a single new entity to the graph.
    Do NOT use this for: bulk inserts (use batch_import), creating
    relationships (use create_edge), or create-if-missing by a key (use
    execute_gql with MERGE).

    Args:
        labels: One or more node labels (e.g. ["Person"] or ["Person", "Employee"]).
        properties: Optional key-value properties (e.g. {"name": "Alice", "age": 30}).
            Omit or pass null for a node with no properties.

    Returns:
        JSON with the created node's id, labels, and properties. Fails if the
        node breaks a schema constraint (e.g. a duplicate UNIQUE value).

    Examples:
        create_node(["Person"], {"name": "Alice", "age": 30})
        create_node(["Company"], {"name": "Acme", "founded": 2010})
        create_node(["Tag"])  # no properties
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx, "create_node"):
        return ro
    try:
        node = _db(ctx).create_node(labels, properties)
        return json.dumps(_node_to_dict(node), default=str)
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
    edge_type: str,
    properties: dict[str, Any] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Create a directed edge (relationship) between two existing nodes.

    Both nodes must already exist: the edge is refused otherwise.

    Use this tool when: you need to connect two nodes with a typed relationship.
    Do NOT use this for: creating nodes (use create_node), many edges at once
    (use batch_import) or querying relationships (use get_neighbors or
    execute_gql).

    Args:
        source_id: The source node ID (integer).
        target_id: The target node ID (integer).
        edge_type: Relationship type string (e.g. "KNOWS", "WORKS_AT").
        properties: Optional edge properties (e.g. {"since": 2020, "weight": 1.5}).

    Returns:
        JSON with the created edge's id, source_id, target_id, edge_type, and properties.

    Examples:
        create_edge(1, 2, "KNOWS")
        create_edge(1, 3, "WORKS_AT", {"since": 2020})
    """
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
        return json.dumps(_edge_to_dict(edge), default=str)
    except Exception as exc:
        return tool_error(
            "create_edge",
            describe_exception(exc),
            "verify that both source_id and target_id exist (use get_node), and call graph_info to inspect the schema.",
        )


@grafeo_tool(read_only=True)
def get_node(
    node_id: int,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get a single node by its ID.

    Returns the node's labels and all properties.

    Use this tool when: you have a specific node ID and need its details.
    Do NOT use this for: searching nodes by label or property (use
    search_nodes_by_label or execute_gql).

    Args:
        node_id: The numeric node ID (e.g. 0, 1, 42).

    Returns:
        JSON with id, labels, and properties, or an error if there is no
        node with that ID.

    Examples:
        get_node(0)
        get_node(42)
    """
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
        return json.dumps(_node_to_dict(node), default=str)
    except Exception as exc:
        return tool_error("get_node", describe_exception(exc), "node_id must be a non-negative integer.")


@grafeo_tool(read_only=True)
def search_nodes_by_label(
    label: str,
    limit: int = _MAX_LABEL_RESULTS,
    offset: int = 0,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find nodes that have a specific label.

    Returns node IDs and their properties, paginated by limit/offset.

    Use this tool when: you want to list or browse nodes of a certain type
    (e.g. all Person nodes, all Company nodes).
    Do NOT use this for: getting a single node by ID (use get_node), or
    complex filtered queries (use execute_gql).

    Args:
        label: The label to filter by (e.g. "Person", "Company").
        limit: Maximum number of results to return (default 100).
        offset: Number of results to skip for pagination (default 0).

    Returns:
        JSON with a list of {node_id, properties} objects, the count, and a
        note when the page is full (there may be more).

    Examples:
        search_nodes_by_label("Person")
        search_nodes_by_label("Company", limit=10)
        search_nodes_by_label("Person", limit=50, offset=50)  # page 2
    """
    assert ctx is not None
    if err := check_range("search_nodes_by_label", limit=(limit, 1), offset=(offset, 0)):
        return err
    try:
        nodes = _db(ctx).get_nodes_by_label(label, limit=limit, offset=offset)

        results = [{"node_id": node_id, "properties": props} for node_id, props in nodes]

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

        return json.dumps(payload, default=str)
    except Exception as exc:
        return tool_error(
            "search_nodes_by_label",
            f"could not search label '{label}': {describe_exception(exc)}",
            "call graph_info to see which labels exist.",
        )


@grafeo_tool(read_only=True)
def graph_info(
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get an overview of the graph database: counts, labels, edge types, indexes and engine.

    Use this tool when: you need to understand what data is in the graph
    before writing queries, to see which vector and text indexes exist
    before vector_search or search_text, or to verify the database state
    after mutations.
    Do NOT use this for: retrieving specific node/edge data (use get_node,
    search_nodes_by_label, or execute_gql).

    Returns:
        JSON with:
          info: mode, node_count, edge_count, is_persistent, path, version.
          schema: labels and edge_types (each with a count), property_keys.
          stats: detailed statistics (memory_bytes, disk_bytes, ...).
          indexes: vector and text indexes ({label, property, items}) and
            the property keys that have a property index.
          engine: grafeo version and the compiled-in features (query
            languages, algorithms, vector and text search).
          server: read_only is true when mutation tools are disabled.
    """
    assert ctx is not None
    try:
        app = ctx.request_context.lifespan_context
        db = app.db
        schema = db.schema()
        build = grafeo.build_info()
        payload: dict[str, Any] = {
            "info": db.info(),
            "schema": schema,
            "stats": db.detailed_stats(),
            "indexes": index_overview(db, list(schema.get("property_keys", []))),
            "engine": {"version": build.get("version"), "features": build.get("features", [])},
            "server": {"read_only": bool(app.read_only)},
        }
        return json.dumps(payload, default=str)
    except Exception as exc:
        return tool_error("graph_info", f"could not read database info: {describe_exception(exc)}")


@grafeo_tool(read_only=True)
def get_neighbors(
    node_id: int,
    direction: str = "both",
    edge_type: str | None = None,
    limit: int = _MAX_NEIGHBORS,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get neighboring nodes connected to a given node.

    This is the primary tool for graph traversal. Use it to explore the
    neighborhood of a known node. Returns connected nodes with the edges
    that link them.

    Use this tool when: you have a node ID and want to see what it connects to.
    Do NOT use this for: finding nodes by property (use search_nodes_by_label)
    or running complex multi-hop queries (use execute_gql).

    Args:
        node_id: The ID of the node to get neighbors for.
        direction: "outgoing" (node-->neighbor), "incoming" (neighbor-->node),
            or "both" (default). Controls which direction of edges to follow.
        edge_type: Filter by relationship type (e.g. "KNOWS"). None returns
            all edge types.
        limit: Maximum number of edges to follow (default 50). A neighbor
            linked by several edges is listed once.

    Returns:
        JSON with the center node, a list of neighbors (with connecting edge
        info), and counts.

    Examples:
        get_neighbors(0)
        get_neighbors(42, direction="outgoing")
        get_neighbors(1, edge_type="KNOWS", limit=10)
        get_neighbors(5, direction="incoming", edge_type="WORKS_AT")
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
                neighbor_info["properties"] = neighbor_node.properties()

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

        return json.dumps(payload, default=str)

    except Exception as exc:
        return tool_error(
            "get_neighbors",
            f"could not read the neighbors of node {node_id}: {describe_exception(exc)}",
            "verify the node exists with get_node, or call graph_info to inspect the database.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def update_node(
    node_id: int,
    properties: dict[str, Any],
    merge: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Update properties on an existing node.

    Use this tool when: you need to modify a node's properties after creation.
    Do NOT use for: changing labels (use execute_gql with SET n:Label or
    REMOVE n:Label), creating new nodes (use create_node), or deleting nodes
    (use delete_node).

    Args:
        node_id: The ID of the node to update.
        properties: Key-value properties to set. Values can be strings,
            numbers, booleans, or lists.
        merge: If True (default), merge with existing properties (new keys
            are added, existing keys are overwritten, unlisted keys are
            kept). If False, replace all properties (unlisted keys are
            removed).

    Returns:
        JSON with the updated node's id, labels, and properties. Fails if a
        value breaks a schema constraint.

    Examples:
        update_node(0, {"age": 31})                     # merge: keep other props
        update_node(0, {"name": "Alice"}, merge=False)  # replace all props
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
        return json.dumps(_node_to_dict(db.get_node(node_id)), default=str)
    except Exception as exc:
        return tool_error(
            "update_node",
            f"could not update node {node_id}: {describe_exception(exc)}",
            "verify the node exists with get_node and check the schema with graph_info.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def delete_node(
    node_id: int,
    detach: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Delete a node from the graph.

    Use this tool when: you need to remove a node permanently.
    Do NOT use for: updating properties (use update_node) or deleting
    edges only (use delete_edge).

    Args:
        node_id: The ID of the node to delete.
        detach: If True (default), also delete all edges connected to this
            node (DETACH DELETE), in one atomic step. If False, fail if the
            node has any connected edges.

    Returns:
        A confirmation sentence on success, or an error.

    Examples:
        delete_node(42)                # detach delete (remove edges too)
        delete_node(42, detach=False)  # fail if edges exist
    """
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
    properties: dict[str, Any],
    merge: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Update properties on an existing edge.

    Use this tool when: you need to modify an edge's properties after creation.
    Do NOT use for: changing the edge type (delete and recreate), creating
    new edges (use create_edge), or deleting edges (use delete_edge).

    Args:
        edge_id: The ID of the edge to update.
        properties: Key-value properties to set.
        merge: If True (default), merge with existing properties. If False,
            replace all properties.

    Returns:
        JSON with the updated edge's id, source_id, target_id, edge_type,
        and properties.

    Examples:
        update_edge(0, {"weight": 2.5})
        update_edge(0, {"since": 2024}, merge=False)
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
        return json.dumps(_edge_to_dict(db.get_edge(edge_id)), default=str)
    except Exception as exc:
        return tool_error(
            "update_edge",
            f"could not update edge {edge_id}: {describe_exception(exc)}",
            "verify the edge exists with get_neighbors or execute_gql.",
        )


@grafeo_tool(read_only=False, destructive=True, idempotent=True)
def delete_edge(
    edge_id: int,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Delete an edge from the graph.

    Use this tool when: you need to remove a relationship between two nodes.
    Do NOT use for: deleting nodes (use delete_node) or updating edge
    properties (use update_edge).

    Args:
        edge_id: The ID of the edge to delete.

    Returns:
        A confirmation sentence on success, or an error.

    Examples:
        delete_edge(5)
    """
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
