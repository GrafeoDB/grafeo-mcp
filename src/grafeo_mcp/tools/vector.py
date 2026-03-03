from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp
from grafeo_mcp.tools._helpers import _node_summary, _read_only_guard, _truncate


@mcp.tool()
def vector_search(
    label: str,
    property: str,
    query_vector: list[float],
    k: int = 10,
    ef: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find the k nearest nodes by vector similarity (HNSW index).

    Use this tool when you have an embedding vector and want to find
    semantically similar nodes.  Requires a vector index created via
    create_vector_index on the same label + property.

    Do NOT use this for keyword or property search — use search_nodes_by_label
    or execute_gql for that.

    Args:
        label: Node label to search within (e.g. "Document").
        property: Property that holds the embedding vector (e.g. "embedding").
        query_vector: The query embedding as a list of floats.
        k: Number of nearest neighbors to return (default 10).
        ef: HNSW search beam width.  Higher values improve recall at the cost
            of speed.  Leave as None to use the index default.

    Returns:
        JSON array of {node_id, distance, labels, properties}
        sorted by distance ascending (most similar first).

    Example call:
        vector_search("Document", "embedding", [0.12, -0.34, ...], k=5)
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        results = db.vector_search(label, property, query_vector, k, ef)

        output: list[dict[str, Any]] = []
        for node_id, distance in results:
            entry: dict[str, Any] = {
                "node_id": node_id,
                "distance": round(float(distance), 6),
            }
            summary = _node_summary(db, node_id)
            entry["labels"] = summary.get("labels", [])
            entry["properties"] = summary.get("properties", {})
            output.append(entry)

        return _truncate(output)
    except Exception as exc:
        return f"vector_search error: {exc}"


@mcp.tool()
def create_vector_index(
    label: str,
    property: str,
    dimensions: int | None = None,
    metric: str = "cosine",
    m: int | None = None,
    ef_construction: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Create an HNSW vector index for fast similarity search.

    Call this once before using vector_search on a label + property pair.
    If nodes with the given label already have vector values in the property,
    they are indexed immediately; future nodes are indexed on insertion.

    Args:
        label: Node label to index (e.g. "Document").
        property: Property containing embedding vectors (e.g. "embedding").
        dimensions: Vector dimensionality (e.g. 1536 for OpenAI, 384 for
            MiniLM).  If None the engine infers it from existing data.
        metric: Distance metric — "cosine" (default), "euclidean",
            "dot_product", or "manhattan".
        m: HNSW links per node (default 16 inside the engine).  Higher
            values give better recall but use more memory.
        ef_construction: HNSW construction beam width (default 128 inside the
            engine).  Higher values build a higher-quality index but take
            longer.

    Returns:
        Confirmation string on success, or an error message.

    Example call:
        create_vector_index("Document", "embedding", 1536, "cosine", m=32,
                            ef_construction=200)
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx):
        return ro
    try:
        db = ctx.request_context.lifespan_context.db
        db.create_vector_index(
            label,
            property,
            dimensions,
            metric,
            m,
            ef_construction,
        )
        parts = [f":{label}.{property}"]
        if dimensions is not None:
            parts.append(f"{dimensions}d")
        parts.append(metric)
        if m is not None:
            parts.append(f"m={m}")
        if ef_construction is not None:
            parts.append(f"ef_construction={ef_construction}")
        return f"HNSW index created on {', '.join(parts)}"
    except Exception as exc:
        return f"create_vector_index error: {exc}"


@mcp.tool()
def mmr_search(
    label: str,
    property: str,
    query_vector: list[float],
    k: int = 10,
    fetch_k: int | None = None,
    lambda_mult: float | None = None,
    ef: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find diverse nearest neighbors using Maximal Marginal Relevance (MMR).

    MMR balances relevance to the query with diversity among results,
    avoiding redundant near-duplicate results. This is ideal for RAG
    pipelines where you want broad coverage rather than 10 variations
    of the same paragraph.

    Use this tool when: you need diverse vector search results for RAG or
    when vector_search returns too many near-duplicates.
    Use vector_search when: you want the absolute closest matches regardless
    of diversity.

    Args:
        label: Node label to search within (e.g. "Document").
        property: Property that holds the embedding vector (e.g. "embedding").
        query_vector: The query embedding as a list of floats.
        k: Number of diverse results to return (default 10).
        fetch_k: Initial candidates from HNSW before MMR re-ranking
            (default: 4*k). Higher values give MMR more to choose from.
        lambda_mult: Balance between relevance and diversity.
            0.0 = maximize diversity, 1.0 = maximize relevance.
            Default: 0.5 (balanced). For RAG, try 0.3-0.7.
        ef: HNSW search beam width. Leave as None for index default.

    Returns:
        JSON array of {node_id, distance, labels, properties}
        ordered by MMR selection (not pure distance).

    Example call:
        mmr_search("Document", "embedding", [0.12, -0.34, ...], k=5, lambda_mult=0.3)
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db
        results = db.mmr_search(label, property, query_vector, k, fetch_k, lambda_mult, ef)

        output: list[dict[str, Any]] = []
        for node_id, distance in results:
            entry: dict[str, Any] = {
                "node_id": node_id,
                "distance": round(float(distance), 6),
            }
            summary = _node_summary(db, node_id)
            entry["labels"] = summary.get("labels", [])
            entry["properties"] = summary.get("properties", {})
            output.append(entry)

        return _truncate(output)
    except Exception as exc:
        return (
            f"mmr_search error: {exc}. "
            "This feature requires a local grafeo build with MMR support. "
            "Use vector_search as a fallback."
        )


@mcp.tool()
def vector_graph_search(
    label: str,
    property: str,
    query_vector: list[float],
    k: int = 5,
    expand_depth: int = 1,
    expand_edge_type: str | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Hybrid search: find similar nodes by vector, then expand their graph neighborhood.

    This is the most powerful search tool — it combines semantic similarity
    (vector search) with graph structure (neighbor expansion).  Use it when
    you want to find relevant nodes AND understand their context.

    Step 1: Vector search finds the top-k most similar nodes.
    Step 2: For each result, expands outward by expand_depth hops.

    Use this tool when: you need both semantic relevance AND graph context.
    Use vector_search when: you only need the similar nodes themselves.
    Use get_neighbors when: you already have a node and want to explore around it.

    Args:
        label: Node label to search (must have a vector index).
        property: Property holding the embedding vector.
        query_vector: The query embedding as a list of floats.
        k: Number of nearest seed nodes to return (default 5).
        expand_depth: How many hops to expand from each seed (default 1).
            Use 0 to skip expansion (equivalent to plain vector_search).
        expand_edge_type: Optional edge type filter.  If provided, only
            edges of this type are followed during expansion.

    Returns:
        JSON object with "seeds" (vector results) and "neighbors" (expanded
        context), truncated if the output is large.

    Example call:
        vector_graph_search("Article", "embedding", [0.1, ...], k=3,
                            expand_depth=2, expand_edge_type="CITES")
    """
    assert ctx is not None
    try:
        db = ctx.request_context.lifespan_context.db

        # --- Step 1: vector search -------------------------------------------
        vs_results = db.vector_search(label, property, query_vector, k)
        seeds: list[dict[str, Any]] = []
        seed_ids: list[int] = []
        for node_id, distance in vs_results:
            entry: dict[str, Any] = {
                "node_id": node_id,
                "distance": round(float(distance), 6),
            }
            summary = _node_summary(db, node_id)
            entry["labels"] = summary.get("labels", [])
            entry["properties"] = summary.get("properties", {})
            seeds.append(entry)
            seed_ids.append(node_id)

        # --- Step 2: graph expansion -----------------------------------------
        neighbors: list[dict[str, Any]] = []
        if expand_depth > 0 and seed_ids:
            seen: set[int] = set(seed_ids)
            frontier = list(seed_ids)

            for _hop in range(expand_depth):
                next_frontier: list[int] = []
                for nid in frontier:
                    # Build a GQL query for one-hop neighbors (GQL is always
                    # available, no feature flags needed).
                    edge_filter = f":{expand_edge_type}" if expand_edge_type else ""
                    gql = f"MATCH (a)-[r{edge_filter}]-(b) WHERE id(a) = {nid} RETURN id(b) AS nid"
                    try:
                        rows = db.execute(gql)
                        for row in rows:
                            vals = list(row.values()) if isinstance(row, dict) else [row]
                            neighbor_id = int(vals[0])
                            if neighbor_id not in seen:
                                seen.add(neighbor_id)
                                next_frontier.append(neighbor_id)
                                summary = _node_summary(db, neighbor_id)
                                neighbors.append(
                                    {
                                        **summary,
                                        "hop": _hop + 1,
                                        "seed_id": nid,
                                    }
                                )
                    except Exception:
                        # If the query fails for this node, skip and continue.
                        continue
                frontier = next_frontier
                if not frontier:
                    break

        payload: dict[str, Any] = {
            "seeds": seeds,
            "seed_count": len(seeds),
            "neighbors": neighbors,
            "neighbor_count": len(neighbors),
        }
        return _truncate(payload)
    except Exception as exc:
        return f"vector_graph_search error: {exc}"
