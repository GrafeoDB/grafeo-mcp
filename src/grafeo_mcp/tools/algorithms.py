from __future__ import annotations

import heapq
import math
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession
from pydantic import Field

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import _node_summary, _truncate, check_range, describe_exception, grafeo_tool, tool_error

RankLabel = Annotated[
    str | None,
    Field(description='Return only nodes with this label, e.g. "Person"; scores still cover the whole graph.'),
]


_LABELS_HINT = "graph_info lists the labels (they are case-sensitive)."


def _ranked(db: Any, scores: dict[int, float], top_k: int, label: str | None = None) -> list[dict[str, Any]]:
    """The top_k scored nodes, highest first; with *label*, only nodes that have it (ranks stay graph-wide)."""
    results: list[dict[str, Any]] = []
    for node_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        summary = _node_summary(db, node_id)
        if label is not None and label not in summary.get("labels", []):
            continue
        results.append({**summary, "score": round(score, 8)})
        if len(results) == top_k:
            break
    return results


def _ranking(algorithm: str, scores: dict[int, float], results: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"algorithm": algorithm, **extra, "total_nodes_scored": len(scores)}
    payload["top_k"] = len(results)
    payload["results"] = results
    return payload


@grafeo_tool(read_only=True)
def pagerank(
    damping: Annotated[float, Field(description="Between 0 and 1.")] = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
    top_k: Annotated[int, Field(description="Nodes to return.")] = 20,
    label: RankLabel = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Rank nodes by PageRank: how many links point at them, and from how important nodes. Returns the top_k.

    For "the most important person", pass label="Person".
    """
    assert ctx is not None
    if not 0.0 <= damping <= 1.0:
        return tool_error("pagerank", f"damping must be between 0.0 and 1.0, got {damping}")
    if err := check_range("pagerank", max_iterations=(max_iterations, 1), top_k=(top_k, 1), tolerance=(tolerance, 0)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        scores: dict[int, float] = db.algorithms.pagerank(
            damping=damping,
            max_iterations=max_iterations,
            tolerance=tolerance,
        )
        results = _ranked(db, scores, top_k, label)
        if label and scores and not results:
            return tool_error("pagerank", f"no node has the label {label!r}", _LABELS_HINT)
        extra = {"label": label} if label else {}
        return _truncate(_ranking("pagerank", scores, results, **extra))
    except Exception as exc:
        return tool_error("pagerank", describe_exception(exc), "check the graph with graph_info.")


_DIRECTION_PATTERNS = {
    "outgoing": "(a)-[r]->(b)",
    "incoming": "(a)<-[r]-(b)",
    "both": "(a)-[r]-(b)",
}


def _edge_weight(edge: dict[str, Any], weight_property: str | None) -> float:
    """The weight of *edge* (a query row's edge map): 1.0 without a property or value, else a number >= 0."""
    if weight_property is None:
        return 1.0
    value = edge.get(weight_property)
    if value is None:
        return 1.0
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValueError(
            f"the weight {weight_property!r} of edge {edge.get('_id')} is {type(value).__name__} ({value!r}), "
            "not a number"
        )
    weight = float(value)
    if not math.isfinite(weight) or weight < 0:
        raise ValueError(
            f"the weight {weight_property!r} of edge {edge.get('_id')} is {value}, not a finite number of at least 0"
        )
    return weight


def _shortest_path(
    db: Any, source: int, target: int, weight_property: str | None, direction: str
) -> tuple[float, list[int]] | None:
    """Dijkstra over *direction* ("incoming" or "both"), reading each node's edges as it is reached.

    The engine's dijkstra follows edge direction only; this walks the edges the
    other ways with the same weight rules (missing value 1.0, a non-number,
    infinite or negative weight an error). Only the nodes closer than the
    target are expanded, one query each.
    """
    query = f"MATCH {_DIRECTION_PATTERNS[direction]} WHERE id(a) = $id RETURN id(b) AS nid, r AS e"
    best: dict[int, float] = {source: 0.0}
    previous: dict[int, int] = {}
    done: set[int] = set()
    queue: list[tuple[float, int, int]] = [(0.0, 0, source)]
    order = 1
    while queue:
        distance, _, node = heapq.heappop(queue)
        if node in done:
            continue
        if node == target:
            path = [target]
            while path[-1] != source:
                path.append(previous[path[-1]])
            return distance, path[::-1]
        done.add(node)
        for row in db.execute(query, {"id": node}):
            neighbor = int(row["nid"])
            if neighbor in done:
                continue
            candidate = distance + _edge_weight(row["e"], weight_property)
            if candidate < best.get(neighbor, math.inf):
                best[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, order, neighbor))
                order += 1
    return None


@grafeo_tool(read_only=True)
def dijkstra(
    source_id: int,
    target_id: int,
    weight_property: Annotated[
        str | None, Field(description="Edge property with a non-negative number; without it each edge weighs 1.")
    ] = None,
    direction: Annotated[
        str,
        Field(description='"both" (default) ignores edge direction; "outgoing" or "incoming" follow it.'),
    ] = "both",
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Shortest weighted path from source_id to target_id. Returns distance, hop_count and the path's nodes.

    By default edges count in either direction, as "how are A and C connected" means; pass
    direction="outgoing" to follow edges only from source to target (a dependency or a flow).
    """
    assert ctx is not None
    if direction not in _DIRECTION_PATTERNS:
        return tool_error("dijkstra", f"direction must be 'both', 'outgoing' or 'incoming', got {direction!r}")
    if err := check_range("dijkstra", source_id=(source_id, 0), target_id=(target_id, 0)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        for role, node_id in (("source", source_id), ("target", target_id)):
            if db.get_node(node_id) is None:
                return tool_error(
                    "dijkstra",
                    f"{role} node {node_id} does not exist",
                    "use search_nodes_by_label or get_node to find valid node IDs.",
                )
        if direction == "outgoing":
            result = db.algorithms.dijkstra(source=source_id, target=target_id, weight=weight_property)
        else:
            result = _shortest_path(db, source_id, target_id, weight_property, direction)

        if result is None:
            hint = (
                'no path follows the edge direction; pass direction="both" to ignore it.'
                if direction != "both"
                else "the nodes are not connected at all; connected_components shows which nodes are."
            )
            return tool_error("dijkstra", f"no path found from node {source_id} to node {target_id}", hint)

        distance, path_ids = result
        path = [_node_summary(db, nid) for nid in path_ids]

        return _truncate(
            {
                "algorithm": "dijkstra",
                "source_id": source_id,
                "target_id": target_id,
                "direction": direction,
                "distance": round(float(distance), 8),
                "hop_count": len(path) - 1,
                "path": path,
            }
        )
    except Exception as exc:
        return tool_error("dijkstra", describe_exception(exc), "check that source_id and target_id are valid node IDs.")


@grafeo_tool(read_only=True)
def louvain(
    resolution: Annotated[
        float, Field(description="Above 1: more, smaller communities; below 1: fewer, larger ones.")
    ] = 1.0,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Find communities (Louvain): groups of densely linked nodes, numbered from 0 by their smallest node ID."""
    assert ctx is not None
    if err := check_range("louvain", resolution=(resolution, 0)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        result = db.algorithms.louvain(resolution=resolution)

        raw_communities: dict[int, int] = result["communities"]
        modularity: float = result["modularity"]
        num_communities: int = result["num_communities"]

        grouped: dict[str, list[dict[str, Any]]] = {}
        for node_id, comm_id in sorted(raw_communities.items(), key=lambda item: (item[1], item[0])):
            grouped.setdefault(str(comm_id), []).append(_node_summary(db, int(node_id)))

        return _truncate(
            {
                "algorithm": "louvain",
                "modularity": round(modularity, 6),
                "num_communities": num_communities,
                "communities": grouped,
            }
        )
    except Exception as exc:
        return tool_error("louvain", describe_exception(exc), "check the graph with graph_info.")


@grafeo_tool(read_only=True)
def betweenness_centrality(
    normalized: Annotated[bool, Field(description="Scale scores to 0..1.")] = True,
    top_k: Annotated[int, Field(description="Nodes to return.")] = 20,
    label: RankLabel = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Rank nodes by betweenness: how often they lie on shortest paths between others (bridges, bottlenecks)."""
    assert ctx is not None
    if err := check_range("betweenness_centrality", top_k=(top_k, 1)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        scores: dict[int, float] = db.algorithms.betweenness_centrality(normalized=normalized)
        results = _ranked(db, scores, top_k, label)
        if label and scores and not results:
            return tool_error("betweenness_centrality", f"no node has the label {label!r}", _LABELS_HINT)
        extra: dict[str, Any] = {"normalized": normalized}
        if label:
            extra["label"] = label
        return _truncate(_ranking("betweenness_centrality", scores, results, **extra))
    except Exception as exc:
        return tool_error("betweenness_centrality", describe_exception(exc), "check the graph with graph_info.")


@grafeo_tool(read_only=True)
def connected_components(
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Group nodes into connected components, ignoring edge direction.

    Returns num_components and components ({component id: [node IDs]}).
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        assignments: dict[int, int] = db.algorithms.connected_components()

        grouped: dict[str, list[int]] = {}
        for node_id, comp_id in sorted(assignments.items(), key=lambda item: (item[1], item[0])):
            grouped.setdefault(str(comp_id), []).append(int(node_id))

        return _truncate(
            {
                "algorithm": "connected_components",
                "num_components": len(grouped),
                "components": grouped,
            }
        )
    except Exception as exc:
        return tool_error("connected_components", describe_exception(exc), "check the graph with graph_info.")
