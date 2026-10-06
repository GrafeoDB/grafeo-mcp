from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import (
    _node_summary,
    _read_only_guard,
    _truncate,
    check_range,
    describe_exception,
    first_vector_length,
    grafeo_tool,
    tool_error,
)

_INDEX_HINT = (
    "graph_info lists the existing vector indexes under indexes.vector; create one with create_vector_index "
    "(a WAL-directory database loses its vector indexes on restart with grafeo 0.5.x, so create it again)."
)


def _query_vector_error(tool: str, db: Any, label: str, prop: str, query_vector: list[float]) -> str | None:
    """Reject an empty query vector, or one whose length differs from the stored vectors.

    A dimension mismatch makes the grafeo 0.5.x HNSW index panic, so it is
    checked before the search reaches the engine.
    """
    if not query_vector:
        return tool_error(tool, "query_vector is empty", "pass the query embedding as a list of floats.")
    expected = first_vector_length(db, label, prop)
    if expected is not None and expected != len(query_vector):
        return tool_error(
            tool,
            f"query_vector has {len(query_vector)} dimensions but the :{label}.{prop} vectors have {expected}",
            "embed the query with the same model that produced the stored vectors.",
        )
    return None


def _hits(db: Any, results: list[tuple[int, float]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for node_id, distance in results:
        summary = _node_summary(db, node_id)
        output.append(
            {
                "node_id": node_id,
                "distance": round(float(distance), 6),
                "labels": summary.get("labels", []),
                "properties": summary.get("properties", {}),
            }
        )
    return output


@grafeo_tool(read_only=True)
def vector_search(
    label: str,
    property: str,
    query_vector: list[float],
    k: int = 10,
    ef: int | None = None,
    ctx: Context[ServerSession, AppContext] | None = None,
) -> str:
    """Find the k nearest nodes by vector similarity (HNSW index).

    Use this tool when: you have an embedding vector and want to find
    semantically similar nodes. Requires a vector index created via
    create_vector_index on the same label + property (graph_info lists them).
    Do NOT use this for: keyword or property search (use search_text,
    search_nodes_by_label or execute_gql).

    Args:
        label: Node label to search within (e.g. "Document").
        property: Property that holds the embedding vector (e.g. "embedding").
        query_vector: The query embedding as a list of floats. It must have
            the same number of dimensions as the indexed vectors.
        k: Number of nearest neighbors to return (default 10).
        ef: HNSW search beam width. Higher values improve recall at the cost
            of speed. Leave as None to use the index default.

    Returns:
        JSON array of {node_id, distance, labels, properties} sorted by
        distance ascending (lower = more similar; the scale depends on the
        index metric). Embedding properties longer than 32 values are left
        out of properties.

    Example call:
        vector_search("Document", "embedding", [0.12, -0.34, ...], k=5)
    """
    assert ctx is not None
    if err := check_range("vector_search", k=(k, 1), ef=(ef, 1)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        if err := _query_vector_error("vector_search", db, label, property, query_vector):
            return err
        return _truncate(_hits(db, db.vector_search(label, property, query_vector, k, ef)))
    except Exception as exc:
        return tool_error("vector_search", describe_exception(exc), _INDEX_HINT)


@grafeo_tool(read_only=False, idempotent=True)
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

    Call this once before using vector_search, mmr_search or
    vector_graph_search on a label + property pair. Nodes that already have
    vectors in the property are indexed immediately; nodes created or updated
    later are indexed as they are written. Vectors written by create_node,
    batch_import, update_node or execute_gql with a $parameter (or
    vector([...])) are indexed; a list literal in execute_gql text is not.

    Use this tool when: graph_info shows no vector index for the label and
    property you want to search.
    Do NOT use for: keyword search (use create_text_index).

    Args:
        label: Node label to index (e.g. "Document").
        property: Property containing embedding vectors (e.g. "embedding").
        dimensions: Vector dimensionality (e.g. 1536 for OpenAI, 384 for
            MiniLM). If None the engine infers it from existing vectors, so
            it is required when no node has a vector yet.
        metric: Distance metric: "cosine" (default), "euclidean",
            "dot_product", or "manhattan".
        m: HNSW links per node (default 16 inside the engine). Higher
            values give better recall but use more memory.
        ef_construction: HNSW construction beam width (default 128 inside the
            engine). Higher values build a higher-quality index but take
            longer.

    Returns:
        A confirmation sentence on success, or an error.

    Example call:
        create_vector_index("Document", "embedding", 1536, "cosine", m=32,
                            ef_construction=200)
    """
    assert ctx is not None
    if ro := _read_only_guard(ctx, "create_vector_index"):
        return ro
    if err := check_range(
        "create_vector_index", dimensions=(dimensions, 1), m=(m, 1), ef_construction=(ef_construction, 1)
    ):
        return err
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
        return tool_error(
            "create_vector_index",
            describe_exception(exc),
            "pass dimensions when no node has a vector yet; metric is one of cosine, euclidean, "
            "dot_product, manhattan.",
        )


@grafeo_tool(read_only=True)
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
    of the same paragraph. Requires a vector index (create_vector_index).

    Use this tool when: you need diverse vector search results for RAG or
    when vector_search returns too many near-duplicates.
    Use vector_search when: you want the absolute closest matches regardless
    of diversity.

    Args:
        label: Node label to search within (e.g. "Document").
        property: Property that holds the embedding vector (e.g. "embedding").
        query_vector: The query embedding as a list of floats, with the same
            number of dimensions as the indexed vectors.
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
    if err := check_range("mmr_search", k=(k, 1), fetch_k=(fetch_k, 1), ef=(ef, 1)):
        return err
    if lambda_mult is not None and not 0.0 <= lambda_mult <= 1.0:
        return tool_error("mmr_search", f"lambda_mult must be between 0.0 and 1.0, got {lambda_mult}")
    try:
        db = ctx.request_context.lifespan_context.db
        if err := _query_vector_error("mmr_search", db, label, property, query_vector):
            return err
        results = db.mmr_search(label, property, query_vector, k, fetch_k, lambda_mult, ef)
        return _truncate(_hits(db, results))
    except Exception as exc:
        return tool_error("mmr_search", describe_exception(exc), _INDEX_HINT)


@grafeo_tool(read_only=True)
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

    This combines semantic similarity (vector search) with graph structure
    (neighbor expansion). Use it when you want to find relevant nodes AND
    understand their context.

    Step 1: Vector search finds the top-k most similar nodes.
    Step 2: For each result, expands outward by expand_depth hops, following
    edges in both directions.

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
        expand_edge_type: Optional edge type filter. If provided, only
            edges of this type are followed during expansion.

    Returns:
        JSON object with "seeds" (vector results) and "neighbors" (expanded
        context, each with the hop count and the node it was reached from),
        truncated if the output is large.

    Example call:
        vector_graph_search("Article", "embedding", [0.1, ...], k=3,
                            expand_depth=2, expand_edge_type="CITES")
    """
    assert ctx is not None
    if err := check_range("vector_graph_search", k=(k, 1), expand_depth=(expand_depth, 0)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        if err := _query_vector_error("vector_graph_search", db, label, property, query_vector):
            return err

        # --- Step 1: vector search -------------------------------------------
        seeds = _hits(db, db.vector_search(label, property, query_vector, k))
        seed_ids = [seed["node_id"] for seed in seeds]

        # --- Step 2: graph expansion -----------------------------------------
        params: dict[str, Any] = {}
        type_filter = ""
        if expand_edge_type:
            type_filter = " AND type(r) = $edge_type"
            params["edge_type"] = expand_edge_type
        hop_query = f"MATCH (a)-[r]-(b) WHERE id(a) = $id{type_filter} RETURN DISTINCT id(b) AS nid"

        neighbors: list[dict[str, Any]] = []
        seen: set[int] = set(seed_ids)
        frontier = list(seed_ids)
        for hop in range(1, expand_depth + 1):
            next_frontier: list[int] = []
            for source_id in frontier:
                for row in db.execute(hop_query, {**params, "id": source_id}):
                    neighbor_id = int(row["nid"])
                    if neighbor_id in seen:
                        continue
                    seen.add(neighbor_id)
                    next_frontier.append(neighbor_id)
                    neighbors.append({**_node_summary(db, neighbor_id), "hop": hop, "seed_id": source_id})
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
        return tool_error("vector_graph_search", describe_exception(exc), _INDEX_HINT)
