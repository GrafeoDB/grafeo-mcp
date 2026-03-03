from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp
from grafeo_mcp.tools._helpers import _read_only_guard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_LABEL_RESULTS = 100  # default cap for search_nodes_by_label
_MAX_NEIGHBORS = 50  # default cap for get_neighbors


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


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_node(
    labels: list[str],
    properties: dict[str, Any] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Create a new node in the graph with the given labels and properties.

    Use this tool when: you need to add a single new entity to the graph.
    Do NOT use this for: bulk inserts (use execute_gql with
    INSERT/CREATE statements) or creating relationships (use create_edge).

    Args:
        labels: One or more node labels (e.g. ["Person"] or ["Person", "Employee"]).
        properties: Optional key-value properties (e.g. {"name": "Alice", "age": 30}).
            Omit or pass null for a node with no properties.

    Returns:
        JSON with the created node's id, labels, and properties.

    Examples:
        create_node(["Person"], {"name": "Alice", "age": 30})
        create_node(["Company"], {"name": "Acme", "founded": 2010})
        create_node(["Tag"])  # no properties
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        node = db.create_node(labels, properties)
        return json.dumps(_node_to_dict(node), default=str)
    except Exception as exc:
        return (
            f"Failed to create node: {exc}. "
            "Ensure labels is a non-empty list of strings. "
            "Try graph_info to inspect the current schema."
        )


@mcp.tool()
def create_edge(
    source_id: int,
    target_id: int,
    edge_type: str,
    properties: dict[str, Any] | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Create a directed edge (relationship) between two existing nodes.

    Use this tool when: you need to connect two nodes with a typed relationship.
    Do NOT use this for: creating nodes (use create_node) or querying
    relationships (use execute_gql).

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
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        edge = db.create_edge(source_id, target_id, edge_type, properties)
        return json.dumps(_edge_to_dict(edge), default=str)
    except Exception as exc:
        return (
            f"Failed to create edge: {exc}. "
            "Verify that both source_id and target_id exist "
            "(use get_node to check). "
            "Try graph_info to see current node/edge counts."
        )


@mcp.tool()
def get_node(
    node_id: int,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get a single node by its ID.

    Returns the node's labels and all properties, or a not-found message.

    Use this tool when: you have a specific node ID and need its details.
    Do NOT use this for: searching nodes by label or property (use
    search_nodes_by_label or execute_gql).

    Args:
        node_id: The numeric node ID (e.g. 0, 1, 42).

    Returns:
        JSON with id, labels, and properties -- or an error/not-found message.

    Examples:
        get_node(0)
        get_node(42)
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        node = db.get_node(node_id)
        if node is None:
            return (
                f"Node {node_id} not found. "
                "Use graph_info to check total node count, "
                "or search_nodes_by_label to find nodes."
            )
        return json.dumps(_node_to_dict(node), default=str)
    except Exception as exc:
        return f"Failed to get node {node_id}: {exc}. Ensure node_id is a valid non-negative integer."


@mcp.tool()
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
        JSON with a list of {node_id, properties} objects, total count,
        and a truncation note if applicable.

    Examples:
        search_nodes_by_label("Person")
        search_nodes_by_label("Company", limit=10)
        search_nodes_by_label("Person", limit=50, offset=50)  # page 2
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        nodes = db.get_nodes_by_label(label, limit=limit, offset=offset)

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
        return (
            f"Failed to search nodes by label '{label}': {exc}. "
            "Try graph_info to see which labels exist in the database."
        )


@mcp.tool()
def graph_info(
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Get an overview of the graph database: counts, labels, edge types, and schema.

    Use this tool when: you need to understand what data is in the graph
    before writing queries, or to verify the database state after mutations.
    Do NOT use this for: retrieving specific node/edge data (use get_node,
    search_nodes_by_label, or execute_gql).

    Returns:
        JSON with database info (mode, node_count, edge_count, persistence),
        schema (labels with counts, edge_types with counts, property_keys),
        and detailed statistics.
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        info = db.info()
        schema = db.schema()
        stats = db.detailed_stats()

        payload: dict[str, Any] = {
            "info": info,
            "schema": schema,
            "stats": stats,
        }
        return json.dumps(payload, default=str)
    except Exception as exc:
        return f"Failed to retrieve graph info: {exc}."


@mcp.tool()
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
        limit: Maximum neighbors to return (default 50).

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
    try:
        db = ctx.request_context.lifespan_context.db

        # Verify the center node exists
        center = db.get_node(node_id)
        if center is None:
            return (
                f"Node {node_id} not found. "
                "Use graph_info to check available nodes, "
                "or search_nodes_by_label to find valid node IDs."
            )

        # Build a GQL query based on direction and optional edge type filter
        edge_filter = f":{edge_type}" if edge_type else ""

        if direction == "outgoing":
            query = (
                f"MATCH (a)-[r{edge_filter}]->(b) "
                f"WHERE id(a) = {node_id} "
                f"RETURN id(b) AS nid, id(r) AS eid, type(r) AS rtype "
                f"LIMIT {limit}"
            )
        elif direction == "incoming":
            query = (
                f"MATCH (a)<-[r{edge_filter}]-(b) "
                f"WHERE id(a) = {node_id} "
                f"RETURN id(b) AS nid, id(r) AS eid, type(r) AS rtype "
                f"LIMIT {limit}"
            )
        else:  # both
            query = (
                f"MATCH (a)-[r{edge_filter}]-(b) "
                f"WHERE id(a) = {node_id} "
                f"RETURN id(b) AS nid, id(r) AS eid, type(r) AS rtype "
                f"LIMIT {limit}"
            )

        result = db.execute(query)

        neighbors: list[dict[str, Any]] = []
        seen: set[int] = set()

        for row in result:
            neighbor_id = row.get("nid")
            edge_id = row.get("eid")
            rel_type = row.get("rtype")
            if neighbor_id is None:
                continue

            if neighbor_id in seen:
                continue
            seen.add(neighbor_id)

            neighbor_node = db.get_node(neighbor_id)
            neighbor_info: dict[str, Any] = {
                "node_id": neighbor_id,
                "edge_id": edge_id,
                "edge_type": rel_type,
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
        return (
            f"Failed to get neighbors for node {node_id}: {exc}. "
            "Verify the node exists with get_node, or try graph_info "
            "to inspect the database state."
        )


@mcp.tool()
def update_node(
    node_id: int,
    properties: dict[str, Any],
    merge: bool = True,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Update properties on an existing node.

    Use this tool when: you need to modify a node's properties after creation.
    Do NOT use for: changing labels (use execute_gql), creating new nodes
    (use create_node), or deleting nodes (use delete_node).

    Args:
        node_id: The ID of the node to update.
        properties: Key-value properties to set. Values can be strings,
            numbers, booleans, or lists.
        merge: If True (default), merge with existing properties (new keys
            are added, existing keys are overwritten, unlisted keys are
            kept). If False, replace all properties (unlisted keys are
            removed).

    Returns:
        JSON with the updated node's id, labels, and properties.

    Examples:
        update_node(0, {"age": 31})                     # merge: keep other props
        update_node(0, {"name": "Alice"}, merge=False)  # replace all props
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        node = db.get_node(node_id)
        if node is None:
            return f"Node {node_id} not found. Use search_nodes_by_label or graph_info to find valid node IDs."
        if not merge:
            for key in list(node.properties().keys()):
                if key not in properties:
                    db.remove_node_property(node_id, key)
        for key, value in properties.items():
            db.set_node_property(node_id, key, value)
        return json.dumps(_node_to_dict(db.get_node(node_id)), default=str)
    except Exception as exc:
        return f"Failed to update node {node_id}: {exc}. Verify the node exists with get_node."


@mcp.tool()
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
            node (like DETACH DELETE in Cypher). If False, fail if the node
            has any connected edges.

    Returns:
        Confirmation message on success, or an error message.

    Examples:
        delete_node(42)                # detach delete (remove edges too)
        delete_node(42, detach=False)  # fail if edges exist
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        node = db.get_node(node_id)
        if node is None:
            return f"Node {node_id} not found. Use search_nodes_by_label or graph_info to find valid node IDs."

        # Check for connected edges
        edge_query = f"MATCH (n)-[e]-() WHERE id(n) = {node_id} RETURN id(e) AS eid"
        edge_ids: set[int] = set()
        for row in db.execute(edge_query):
            eid = row.get("eid") if isinstance(row, dict) else row[0]
            edge_ids.add(int(eid))

        if edge_ids and not detach:
            return (
                f"Node {node_id} has {len(edge_ids)} connected edge(s). "
                "Use detach=True to delete the node and its edges, "
                "or delete the edges first with delete_edge."
            )

        for eid in edge_ids:
            db.delete_edge(eid)

        labels_str = ", ".join(node.labels) if node.labels else "(unlabeled)"
        db.delete_node(node_id)
        edge_note = f" and {len(edge_ids)} edge(s)" if edge_ids else ""
        return f"Deleted node {node_id} (:{labels_str}){edge_note}."
    except Exception as exc:
        return f"Failed to delete node {node_id}: {exc}. Verify the node exists with get_node."


@mcp.tool()
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
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        edge = db.get_edge(edge_id)
        if edge is None:
            return f"Edge {edge_id} not found. Use get_neighbors or execute_gql to find valid edge IDs."
        if not merge:
            for key in list(edge.properties().keys()):
                if key not in properties:
                    db.remove_edge_property(edge_id, key)
        for key, value in properties.items():
            db.set_edge_property(edge_id, key, value)
        return json.dumps(_edge_to_dict(db.get_edge(edge_id)), default=str)
    except Exception as exc:
        return f"Failed to update edge {edge_id}: {exc}. Verify the edge exists with get_neighbors or execute_gql."


@mcp.tool()
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
        Confirmation message on success, or an error message.

    Examples:
        delete_edge(5)
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        edge = db.get_edge(edge_id)
        if edge is None:
            return f"Edge {edge_id} not found. Use get_neighbors or execute_gql to find valid edge IDs."
        edge_type = edge.edge_type
        source_id = edge.source_id
        target_id = edge.target_id
        db.delete_edge(edge_id)
        return f"Deleted edge {edge_id} (:{edge_type} from node {source_id} to node {target_id})."
    except Exception as exc:
        return f"Failed to delete edge {edge_id}: {exc}. Verify the edge exists with get_neighbors or execute_gql."
