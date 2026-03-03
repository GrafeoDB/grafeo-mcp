# Changelog

All notable changes to grafeo-mcp are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-03-03

CRUD completion, batch import, full-text search, and read-only mode.

### Added

- **`update_node`**: update node properties with merge or replace semantics
- **`delete_node`**: delete a node with optional detach (removes connected edges)
- **`update_edge`**: update edge properties with merge or replace semantics
- **`delete_edge`**: delete an edge by ID
- **`batch_import`**: bulk-create nodes and edges from JSON arrays with `@index` cross-references (max 500 nodes, 1000 edges per batch)
- **`search_text`**: full-text keyword search over string properties (requires text index)
- **`create_text_index`**: create a full-text search index on a string property
- **Read-only mode**: set `GRAFEO_READ_ONLY=1` to disable all mutation tools; mutation tools remain visible but return a descriptive error guiding agents to read-only alternatives

### Changed

- **Tool count**: 16 to 22 (6 new tools)
- **`AppContext`** now carries a `read_only` field, set from the `GRAFEO_READ_ONLY` environment variable at startup
- 117 tests, 82% coverage

## [0.1.2] - 2026-03-01

Quality and correctness patch: shared helpers, dead code removal, and fixes for misleading output.

### Fixed

- **Vector search `similarity` field removed**: `vector_search`, `mmr_search`, and `vector_graph_search` no longer return a `similarity` field computed as `1.0 - distance`, which was only valid for cosine metric and produced wrong or negative values for euclidean/manhattan. The `distance` field (lower = more similar) is always correct regardless of metric
- **Vector index detection**: `graph://schema` resource no longer uses a hardcoded heuristic that only detected vector data in a property named `embedding`. Now directs agents to `graph_info` and `create_vector_index` instead of guessing
- **Connection summary truncation**: `graph://nodes/{id}` resource now warns when outgoing or incoming edge counts hit the internal LIMIT 100 cap, so agents know the totals may be incomplete

### Changed

- **Shared tool helpers**: extracted `_truncate` and `_node_summary` into `tools/_helpers.py`, eliminating duplication between `vector.py` and `algorithms.py`
- **Shared resource helpers**: unified `_format_value` into `resources/_helpers.py` with configurable thresholds, eliminating duplication between `schema.py` and `nodes.py`
- **Dead normalization entries removed**: `_CYPHER_TO_GQL` in `query.py` no longer contains the no-op `MERGE` and `DETACH DELETE` entries (both map to themselves in GQL)
- **Truncation message style**: replaced em-dash with colon in truncation output to match project style conventions

## [0.1.1] - 2026-02-11

Initial release.

### Added

- **14 MCP tools**: `execute_gql`, `create_node`, `create_edge`, `get_node`, `get_neighbors`, `search_nodes_by_label`, `graph_info`, `vector_search`, `mmr_search`, `create_vector_index`, `vector_graph_search`, `pagerank`, `dijkstra`, `louvain`, `betweenness_centrality`, `connected_components`
- **3 MCP resources**: `graph://schema`, `graph://stats`, `graph://nodes/{node_id}`
- **4 MCP prompts**: `explore_graph`, `knowledge_extraction`, `graph_analysis`, `similarity_search`
- Schema-first design: `graph_info` as the agent entry point
- Token-aware output: all list-returning tools have `limit` params and truncate large results
- Cypher-to-GQL auto-normalization in `execute_gql`
- Dual transport: stdio (default) and streamable-http for remote deployments
- 75 tests, 79% coverage

[0.1.3]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/GrafeoDB/grafeo-mcp/releases/tag/v0.1.1
