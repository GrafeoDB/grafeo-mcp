from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import _node_summary, _truncate, check_range, describe_exception, grafeo_tool, tool_error


def _ranked(db: Any, scores: dict[int, float], top_k: int) -> list[dict[str, Any]]:
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [{**_node_summary(db, node_id), "score": round(score, 8)} for node_id, score in ranked]


@grafeo_tool(read_only=True)
def pagerank(
    damping: float = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
    top_k: int = 20,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Run PageRank and return the top-k most important nodes.

    PageRank assigns every node a score proportional to how many
    (and how important) other nodes link to it. Higher scores mean
    more connected / influential nodes.

    Use this tool when: you want to find the most important or central
    nodes in the graph based on link structure.
    Do NOT use this for: finding similar nodes by content (use vector_search)
    or for finding shortest paths (use dijkstra).

    Args:
        damping: Probability of following a link vs. teleporting, between
            0 and 1 (default 0.85).
        max_iterations: Upper bound on convergence iterations (default 100).
        tolerance: Convergence threshold (default 1e-6).
        top_k: How many top-ranked nodes to return (default 20). The algorithm
            always scores every node, but only the top-k are returned to keep
            the output manageable.

    Returns:
        JSON with total_nodes_scored and results: [{node_id, labels,
        properties, score}] sorted by score descending. Truncated if it
        exceeds the output budget. An empty graph gives no results; without
        edges every node gets the same score.
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
        results = _ranked(db, scores, top_k)
        return _truncate(
            {
                "algorithm": "pagerank",
                "total_nodes_scored": len(scores),
                "top_k": len(results),
                "results": results,
            }
        )
    except Exception as exc:
        return tool_error("pagerank", describe_exception(exc), "check the graph with graph_info.")


@grafeo_tool(read_only=True)
def dijkstra(
    source_id: int,
    target_id: int,
    weight_property: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find the shortest weighted path between two nodes (Dijkstra's algorithm).

    Edges are followed in their direction (source to target). Returns the
    total distance and the sequence of nodes along the path.

    Use this tool when: you need the shortest or cheapest path between two
    known nodes.
    Do NOT use this for: discovering important nodes (use pagerank) or finding
    similar content (use vector_search).

    Args:
        source_id: Starting node ID.
        target_id: Destination node ID.
        weight_property: Edge property to use as weight (e.g. "distance",
            "cost"). If None every edge has weight 1.0; edges without a
            numeric value for the property also count as 1.0.

    Returns:
        JSON object with {distance, hop_count, path: [{node_id, labels,
        properties}, ...]}, or an error when a node does not exist or no
        path connects them.
    """
    assert ctx is not None
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
        result = db.algorithms.dijkstra(
            source=source_id,
            target=target_id,
            weight=weight_property,
        )

        if result is None:
            return tool_error(
                "dijkstra",
                f"no path found from node {source_id} to node {target_id}",
                "edges are followed in their direction; use get_neighbors to check how the nodes connect.",
            )

        distance, path_ids = result
        path = [_node_summary(db, nid) for nid in path_ids]

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
        return tool_error("dijkstra", describe_exception(exc), "check that source_id and target_id are valid node IDs.")


@grafeo_tool(read_only=True)
def louvain(
    resolution: float = 1.0,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Detect communities using the Louvain modularity-optimization algorithm.

    Groups densely-connected nodes into communities. Higher resolution
    values produce more (smaller) communities; lower values produce fewer
    (larger) communities. The result is deterministic: communities are
    numbered from 0 by their smallest node ID.

    Use this tool when: you want to discover clusters or groups in the graph.
    Do NOT use this for: finding paths (use dijkstra) or ranking nodes (use
    pagerank).

    Args:
        resolution: Resolution parameter (default 1.0). Values > 1 favor
            smaller communities, values < 1 favor larger ones.

    Returns:
        JSON object with {modularity, num_communities, communities} where
        communities maps community_id -> list of node summaries.
        Output is truncated if it exceeds the output budget. An empty graph
        has 0 communities; without edges every node is its own community.
    """
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
    normalized: bool = True,
    top_k: int = 20,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Compute betweenness centrality for all nodes (Brandes' algorithm).

    Betweenness centrality measures how often a node lies on the shortest
    path between other node pairs. High-betweenness nodes are "bridges"
    that connect different parts of the graph.

    Use this tool when: you want to find bridge or bottleneck nodes.
    Do NOT use this for: finding the most linked-to nodes (use pagerank) or
    finding communities (use louvain).

    Args:
        normalized: If True, normalize scores by 2/((n-1)(n-2)) so they fall
            in [0, 1] (default True).
        top_k: Number of top-ranked nodes to return (default 20).

    Returns:
        JSON with total_nodes_scored and results: [{node_id, labels,
        properties, score}] sorted by score descending. All scores are 0 when
        the graph is too small or has no paths through any node.
    """
    assert ctx is not None
    if err := check_range("betweenness_centrality", top_k=(top_k, 1)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        scores: dict[int, float] = db.algorithms.betweenness_centrality(normalized=normalized)
        results = _ranked(db, scores, top_k)
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
        return tool_error("betweenness_centrality", describe_exception(exc), "check the graph with graph_info.")


@grafeo_tool(read_only=True)
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
        maps component_id -> list of node IDs. If every node is its own
        component, the graph has no edges.
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
