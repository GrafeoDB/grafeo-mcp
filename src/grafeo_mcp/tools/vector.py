from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession
from pydantic import Field

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._helpers import (
    Ef,
    LikeNodeId,
    QueryVector,
    VectorProperty,
    _node_summary,
    _read_only_guard,
    _truncate,
    check_range,
    describe_exception,
    grafeo_tool,
    tool_error,
)

_INDEX_HINT = (
    "graph_info lists the existing vector indexes under indexes.vector (create one with create_vector_index); "
    "the query vector needs as many dimensions as the index, so embed it with the model that made the stored vectors."
)


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


def _query_vector(
    db: Any, tool: str, property: str, query_vector: list[float] | None, like_node_id: int | None
) -> tuple[list[float] | None, str | None]:
    """The vector to search with, from query_vector or from the stored vector of like_node_id; or an error."""
    if (query_vector is None) == (like_node_id is None):
        return None, tool_error(
            tool,
            "pass query_vector or like_node_id, not both" if query_vector is not None else "nothing to search with",
            "pass query_vector (an embedding made with the index's model) or like_node_id (a node whose stored "
            "vector to search near, such as one found with execute_gql).",
        )
    if like_node_id is None:
        return query_vector, None
    node = db.get_node(like_node_id)
    if node is None:
        return None, tool_error(
            tool, f"node {like_node_id} not found", "find node IDs with execute_gql or search_text."
        )
    vector = node.properties().get(property)
    numbers = isinstance(vector, list) and vector and all(isinstance(x, int | float) for x in vector)
    if not numbers:
        return None, tool_error(
            tool,
            f"node {like_node_id} has no vector in {property!r}",
            "pick a node of the indexed label (graph_info lists the vector indexes), or pass query_vector.",
        )
    return [float(x) for x in vector], None


def _without(results: list[tuple[int, float]], node_id: int | None, k: int) -> list[tuple[int, float]]:
    """The first k results, leaving out node_id (the node a like_node_id search starts from)."""
    return [hit for hit in results if hit[0] != node_id][:k]


@grafeo_tool(read_only=True)
def vector_search(
    label: str,
    property: VectorProperty,
    query_vector: QueryVector = None,
    k: Annotated[int, Field(description="Number of results.")] = 10,
    ef: Ef = None,
    like_node_id: LikeNodeId = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Find the k nodes nearest to query_vector, or to node like_node_id, in a vector index.

    Without an embedding model, use like_node_id ("what is most like this node?"). Nearest first.
    """
    assert ctx is not None
    if err := check_range("vector_search", k=(k, 1), ef=(ef, 1)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db
        vector, err = _query_vector(db, "vector_search", property, query_vector, like_node_id)
        if err:
            return err
        extra = 1 if like_node_id is not None else 0
        results = db.vector_search(label, property, vector, k + extra, ef)
        return _truncate(_hits(db, _without(results, like_node_id, k)))
    except Exception as exc:
        return tool_error("vector_search", describe_exception(exc), _INDEX_HINT)


@grafeo_tool(read_only=False, idempotent=True)
def create_vector_index(
    label: str,
    property: VectorProperty,
    dimensions: Annotated[
        int | None, Field(description="Vector size (1536, 384, ...); needed when no node has a vector yet.")
    ] = None,
    metric: Annotated[str, Field(description='"cosine", "euclidean", "dot_product" or "manhattan".')] = "cosine",
    m: Annotated[int | None, Field(description="HNSW links per node (engine default 16).")] = None,
    ef_construction: Annotated[int | None, Field(description="HNSW build width (engine default 128).")] = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Create an HNSW vector index on a label and property, for vector_search, mmr_search and vector_graph_search.

    Existing and later vectors are indexed; a list literal in execute_gql text is stored as a list, not a vector.
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
        parts = [metric]
        if dimensions is not None:
            parts.insert(0, f"{dimensions} dimensions")
        if m is not None:
            parts.append(f"m={m}")
        if ef_construction is not None:
            parts.append(f"ef_construction={ef_construction}")
        return f"Vector index created on :{label}.{property} ({', '.join(parts)})."
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
    property: VectorProperty,
    query_vector: QueryVector = None,
    k: Annotated[int, Field(description="Number of results.")] = 10,
    fetch_k: Annotated[int | None, Field(description="Candidates to choose from (default 4 * k).")] = None,
    lambda_mult: Annotated[
        float | None, Field(description="0 = most diverse, 1 = most relevant (default 0.5).")
    ] = None,
    ef: Ef = None,
    like_node_id: LikeNodeId = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Like vector_search, but diverse: Maximal Marginal Relevance skips near-duplicates (good RAG context).

    Results come in selection order.
    """
    assert ctx is not None
    if err := check_range("mmr_search", k=(k, 1), fetch_k=(fetch_k, 1), ef=(ef, 1)):
        return err
    if lambda_mult is not None and not 0.0 <= lambda_mult <= 1.0:
        return tool_error("mmr_search", f"lambda_mult must be between 0.0 and 1.0, got {lambda_mult}")
    try:
        db = ctx.request_context.lifespan_context.db
        vector, err = _query_vector(db, "mmr_search", property, query_vector, like_node_id)
        if err:
            return err
        extra = 1 if like_node_id is not None else 0
        results = db.mmr_search(label, property, vector, k + extra, fetch_k, lambda_mult, ef)
        return _truncate(_hits(db, _without(results, like_node_id, k)))
    except Exception as exc:
        return tool_error("mmr_search", describe_exception(exc), _INDEX_HINT)


@grafeo_tool(read_only=True)
def vector_graph_search(
    label: str,
    property: VectorProperty,
    query_vector: QueryVector = None,
    k: Annotated[int, Field(description="Number of seed nodes.")] = 5,
    expand_depth: Annotated[int, Field(description="Hops to expand from each seed; 0 for none.")] = 1,
    expand_edge_type: Annotated[str | None, Field(description="Follow only this edge type.")] = None,
    like_node_id: LikeNodeId = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Vector search, then the graph around each hit, in both edge directions.

    Returns seeds (as vector_search) and neighbors, each with its hop count and the node it was reached from.
    """
    assert ctx is not None
    if err := check_range("vector_graph_search", k=(k, 1), expand_depth=(expand_depth, 0)):
        return err
    try:
        db = ctx.request_context.lifespan_context.db

        # --- Step 1: vector search -------------------------------------------
        vector, err = _query_vector(db, "vector_graph_search", property, query_vector, like_node_id)
        if err:
            return err
        extra = 1 if like_node_id is not None else 0
        seeds = _hits(db, _without(db.vector_search(label, property, vector, k + extra), like_node_id, k))
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
