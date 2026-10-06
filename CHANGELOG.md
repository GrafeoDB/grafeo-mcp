# Changelog

All notable changes to grafeo-mcp are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Aligned with grafeo 0.5.44 and prepared for grafeo 0.6.0. Fixes a server crash, the read-only bypass in `execute_gql`, query injection, resources that could not be read over MCP and truncated output that was not valid JSON, and makes every tool report errors the same way.

### Fixed

- **A wrong-size query vector stopped the server**: `vector_search`, `mmr_search` and `vector_graph_search` with a query vector of another dimension than the index made grafeo's HNSW index panic, and the panic (a `BaseException`) escaped every handler and closed the MCP connection. The tools now check the vector size first, and every tool turns an engine panic into an error result
- **`execute_gql` ignored read-only mode**: with `GRAFEO_READ_ONLY=1` it still ran writes. It now refuses queries with write clauses and runs the rest in a transaction that is always rolled back; an existing `.grafeo` file is also opened with grafeo's read-only mode, so the engine rejects writes too
- **`execute_gql` rewrote every `CREATE`**: the regex that turned Cypher `CREATE` into `INSERT` also changed string literals (`WHERE n.kind = 'CREATE'`) and broke statements such as `CREATE GRAPH`. It is removed: grafeo's GQL accepts `CREATE` as written
- **Query injection through `edge_type`**: `get_neighbors`, `vector_graph_search` and `graph://schema` pasted edge types into the query text, so a crafted value could change the query (even in read-only mode). Edge types, node IDs and limits are now query parameters
- **Resources could not be read over MCP**: `graph://schema` and `graph://stats` were registered as templates without parameters, which the MCP SDK never matches, and every read of `graph://nodes/{node_id}` failed because the SDK rebuilds a typed context argument without its request. All three work now
- **`graph://nodes/{id}` showed every node as isolated, and `graph://schema` showed `(?)-[:TYPE]->(?)` for every edge type**: both read query rows by position, but rows are dicts keyed by column, and the error was swallowed
- **Truncated results were not valid JSON**: output over the 8,000-character budget was cut mid-text. It is now cut by entries (and long strings shortened), stays valid JSON and carries `truncated`, `omitted` and `note`
- **`batch_import` left partial batches behind**: nodes were created before the edges were checked. The whole batch is now checked first, and if the engine rejects a node or edge partway, the nodes and edges the call created are removed again
- **`get_neighbors` with an unknown `direction`** returned both directions without a word; it is now an error
- **`dijkstra` with a missing node** reported "no path"; it now names the node that does not exist
- **`pagerank` accepted a damping factor outside 0 to 1** and returned meaningless negative scores
- **`similarity_search` prompt** described a `similarity` field that results no longer have, and sent agents to `graph_info` for vector indexes it did not list

### Changed

- **Requires grafeo >=0.5.44,<0.7** (tested against 0.5.44). grafeo 0.5.44 refuses edges to missing nodes, deleting a node that still has edges and property writes to missing nodes or edges; `create_edge` checks both endpoints first and names a missing one (it used to create dangling edges)
- **One error format for every tool**: a failure is a single string, `Error: <tool>: <problem>. Hint: <next step>`, with the engine's message unchanged, and the MCP result has `isError: true`. Messages used to start with `Failed to ...`, `<tool> error: ...` or `GQL query failed: ...` and were never flagged as errors
- **`delete_node` with `detach=True`** deletes the node and its edges in one `DETACH DELETE` statement
- **`vector_graph_search`** reports a failing expansion query instead of skipping it
- **Arguments out of range** (negative IDs, `limit`, `k` or `top_k` below 1, `lambda_mult` outside 0 to 1) are errors that name the argument
- **Tool annotations**: every tool declares `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`, so clients can tell reading tools from writing ones
- **Storage**: README and example configs use single-file `.grafeo` paths. The server logs a warning when `GRAFEO_DB_PATH` is a WAL-directory database (grafeo 0.5.x reopens those without their vector, text and property indexes), and a database that cannot be opened (for example locked by another process) stops the server with a message naming `GRAFEO_DB_PATH`
- **README**: documents `GRAFEO_READ_ONLY`, the grafeo 0.6 file-format migration, the version pin, the error format and output budget; tool descriptions no longer claim that `MERGE` and `OPTIONAL MATCH` are unsupported
- **Development dependencies** moved from the deprecated `[tool.uv] dev-dependencies` to `[dependency-groups]` (`uv sync` installs them as before)

### Added

- **`execute_gql` `params`**: optional query parameters, referenced as `$name`. A parameter the query uses but `params` lacks is reported by name before anything runs
- **`execute_gql` write counters**: results of writing queries include `counters` (nodes, edges, properties and labels created, deleted, set or removed)
- **`execute_gql` checks for one statement per call**: text with several `;`-separated statements is refused with a hint before it runs
- **`graph_info`**: `indexes` (vector and text indexes with their item counts, property indexes), `engine` (grafeo version and compiled-in features) and `server` (`read_only`)
- **`graph://schema`** lists vector and text indexes
- **Engine contract tests** (`tests/test_grafeo_contract.py`): every grafeo behavior the tools rely on, so an engine release that changes one fails with a message naming it
- **Tests** for the MCP protocol end to end (tool listing, annotations, error flags, resources, prompts, an engine panic), file-backed databases (restart, read-only opens, locked files), the error path of every tool, output truncation and the query scanner: 174 to 463 tests, coverage 82% to 96%
- **CI**: a weekly `Latest grafeo` workflow (also started by hand) runs the suite against the newest grafeo in the supported range, pre-releases included

## [0.2.0] - 2026-04-12

Aligned with grafeo 0.5.37. Test coverage, error handling and documentation improvements.

### Added

- **Error handling tests**: malformed GQL, dangling edges, duplicate nodes, missing node updates/deletes, invalid direction parameter
- **Edge case tests**: vector search without index, algorithms on empty graph, dijkstra on disconnected graph, large result truncation
- **Batch atomicity test**: documented that `batch_import` is not atomic; valid entries persist on partial failure
- **Read-only exhaustive test**: parametrized over all 9 mutation tools for consistent error format
- **Cypher normalization tests**: MERGE, MATCH, OPTIONAL MATCH, WITH clause coverage
- **Resource mutation tests**: schema, stats, node resources verified after mutations
- **Prompt rendering tests**: all 4 prompts verified with no unresolved placeholders

### Fixed

- Test assertions in `test_tools_query.py` used `or` instead of `and`, making them always pass
- Node ID assertion in dijkstra test matched single characters instead of actual IDs
- Prompt placeholder check now detects both `{{double}}` and `{single}` brace patterns

### Changed

- Requires grafeo >=0.5 (tested against 0.5.37)
- README: tool count corrected from 16 to 23, added 7 missing tools to tables
- README: added "Which tool when?" decision matrix
- README: documented `@N` batch reference syntax
- README: documented Cypher normalization scope
- 174 tests passing, 82% coverage

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

[Unreleased]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/GrafeoDB/grafeo-mcp/releases/tag/v0.1.1
