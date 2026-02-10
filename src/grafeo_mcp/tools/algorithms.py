from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_RESULT_CHARS = 8_000


def _truncate(payload: Any, *, limit: int = _MAX_RESULT_CHARS) -> str:
    """Serialise *payload* to compact JSON, truncating if it exceeds *limit*."""
    text = json.dumps(payload, default=str, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated — {len(text)} chars total)"


def _node_summary(db: Any, node_id: int) -> dict[str, Any]:
    """Lightweight node dict (id + labels + properties, no large vectors)."""
    node = db.get_node(node_id)
    if node is None:
        return {"node_id": node_id, "error": "node not found"}
    props = node.properties()
    props = {k: v for k, v in props.items() if not (isinstance(v, list) and len(v) > 32)}
    return {"node_id": node_id, "labels": node.labels, "properties": props}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def pagerank(
    damping: float = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
    top_k: int = 20,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Run PageRank and return the top-k most important nodes.

    PageRank assigns every node a score proportional to how many
    (and how important) other nodes link to it.  Higher scores mean
    more connected / influential nodes.

    Use this tool when: you want to find the most important or central
    nodes in the graph based on link structure.
    Do NOT use this for: finding similar nodes by content (use vector_search)
    or for finding shortest paths (use dijkstra).

    Args:
        damping: Probability of following a link vs. teleporting (default 0.85).
        max_iterations: Upper bound on convergence iterations (default 100).
        tolerance: Convergence threshold (default 1e-6).
        top_k: How many top-ranked nodes to return (default 20).  The algorithm
            always scores every node, but only the top-k are returned to keep
            the output manageable.

    Returns:
        JSON array of {node_id, score, labels, properties} sorted by score
        descending.  Output is truncated if it exceeds the token budget.

    Error recovery:
        If this returns an error, verify the graph is non-empty with graph_info.
        PageRank requires at least one edge.
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        scores: dict[int, float] = db.algorithms.pagerank(
            damping=damping,
            max_iterations=max_iterations,
            tolerance=tolerance,
        )

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results: list[dict[str, Any]] = []
        for node_id, score in ranked:
            summary = _node_summary(db, node_id)
            results.append(
                {
                    **summary,
                    "score": round(score, 8),
                }
            )

        return _truncate(
            {
                "algorithm": "pagerank",
                "total_nodes_scored": len(scores),
                "top_k": len(results),
                "results": results,
            }
        )
    except Exception as exc:
        return f"pagerank error: {exc}. Hint: ensure the graph has nodes and edges (check with graph_info)."


@mcp.tool()
def dijkstra(
    source_id: int,
    target_id: int,
    weight_property: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find the shortest weighted path between two nodes (Dijkstra's algorithm).

    Returns the total distance and the sequence of nodes along the path.

    Use this tool when: you need the shortest or cheapest path between two
    known nodes.
    Do NOT use this for: discovering important nodes (use pagerank) or finding
    similar content (use vector_search).

    Args:
        source_id: Starting node ID.
        target_id: Destination node ID.
        weight_property: Edge property to use as weight (e.g. "distance",
            "cost").  If None every edge has weight 1.0.

    Returns:
        JSON object with {distance, path: [{node_id, labels, properties}, ...]}.
        Returns an error message if the nodes are unreachable.

    Error recovery:
        If the result is null/unreachable, check that both node IDs exist
        (use get_node) and that there is a connecting path in the graph.
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        result = db.algorithms.dijkstra(
            source=source_id,
            target=target_id,
            weight=weight_property,
        )

        if result is None:
            return (
                f"No path found from node {source_id} to node {target_id}. "
                "Verify both nodes exist (get_node) and that connecting edges exist."
            )

        distance, path_ids = result
        path: list[dict[str, Any]] = []
        for nid in path_ids:
            path.append(_node_summary(db, nid))

        return _truncate(
            {
                "algorithm": "dijkstra",
                "source_id": source_id,
                "target_id": target_id,
                "distance": round(float(distance), 8),
                "hop_count": len(path) - 1,
                "path": path,
            }
        )
    except Exception as exc:
        return f"dijkstra error: {exc}. Hint: check that source_id and target_id are valid node IDs."


@mcp.tool()
def louvain(
    resolution: float = 1.0,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Detect communities using the Louvain modularity-optimization algorithm.

    Groups densely-connected nodes into communities.  Higher resolution
    values produce more (smaller) communities; lower values produce fewer
    (larger) communities.

    Use this tool when: you want to discover clusters or groups in the graph.
    Do NOT use this for: finding paths (use dijkstra) or ranking nodes (use
    pagerank).

    Args:
        resolution: Resolution parameter (default 1.0).  Values > 1 favor
            smaller communities, values < 1 favor larger ones.

    Returns:
        JSON object with {modularity, num_communities, communities} where
        communities maps community_id -> list of node summaries.
        Output is truncated if it exceeds the token budget.

    Error recovery:
        If this returns 0 communities, the graph may have no edges.  Check
        with graph_info.
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        result = db.algorithms.louvain(resolution=resolution)

        # result is a dict-like with communities, modularity, num_communities
        raw_communities: dict[int, int] = result["communities"]
        modularity: float = result["modularity"]
        num_communities: int = result["num_communities"]

        # Group node IDs by community
        grouped: dict[str, list[dict[str, Any]]] = {}
        for node_id, comm_id in raw_communities.items():
            key = str(comm_id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(_node_summary(db, int(node_id)))

        return _truncate(
            {
                "algorithm": "louvain",
                "modularity": round(modularity, 6),
                "num_communities": num_communities,
                "communities": grouped,
            }
        )
    except Exception as exc:
        return f"louvain error: {exc}. Hint: the graph needs edges for community detection to work."


@mcp.tool()
def betweenness_centrality(
    normalized: bool = True,
    top_k: int = 20,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Compute betweenness centrality for all nodes (Brandes' algorithm).

    Betweenness centrality measures how often a node lies on the shortest
    path between other node pairs.  High-betweenness nodes are "bridges"
    that connect different parts of the graph.

    Use this tool when: you want to find bridge or bottleneck nodes.
    Do NOT use this for: finding the most linked-to nodes (use pagerank) or
    finding communities (use louvain).

    Args:
        normalized: If True, normalize scores by 2/((n-1)(n-2)) so they fall
            in [0, 1] (default True).
        top_k: Number of top-ranked nodes to return (default 20).

    Returns:
        JSON array of {node_id, score, labels, properties} sorted by score
        descending.

    Error recovery:
        If all scores are 0 the graph may be too small or disconnected.
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        scores: dict[int, float] = db.algorithms.betweenness_centrality(
            normalized=normalized,
        )

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results: list[dict[str, Any]] = []
        for node_id, score in ranked:
            summary = _node_summary(db, node_id)
            results.append(
                {
                    **summary,
                    "score": round(score, 8),
                }
            )

        return _truncate(
            {
                "algorithm": "betweenness_centrality",
                "normalized": normalized,
                "total_nodes_scored": len(scores),
                "top_k": len(results),
                "results": results,
            }
        )
    except Exception as exc:
        return f"betweenness_centrality error: {exc}. Hint: ensure the graph has at least 3 nodes and some edges."


@mcp.tool()
def connected_components(
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find connected components (treating the graph as undirected).

    A connected component is a maximal set of nodes such that every pair
    is reachable from every other by following edges in either direction.

    Use this tool when: you want to know how many disconnected subgraphs
    exist, or which nodes belong to the same component.
    Do NOT use this for: finding dense sub-communities (use louvain).

    Returns:
        JSON object with {num_components, components} where components
        maps component_id -> list of node IDs.

    Error recovery:
        If every node is its own component, the graph has no edges.
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        assignments: dict[int, int] = db.algorithms.connected_components()

        grouped: dict[str, list[int]] = {}
        for node_id, comp_id in assignments.items():
            key = str(comp_id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(int(node_id))

        return _truncate(
            {
                "algorithm": "connected_components",
                "num_components": len(grouped),
                "components": grouped,
            }
        )
    except Exception as exc:
        return f"connected_components error: {exc}"
