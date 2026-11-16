# Changelog

All notable changes to grafeo-mcp, an MCP server that gives agents a Grafeo database.

## [0.3.0] - 2026-11-16

grafeo 0.6 release: runs on grafeo 0.6 and the mcp 2.x SDK, adds time-travel reads, lists its tools in half the bytes, and fixes a server crash, a read-only bypass and query injection. Before upgrading: a grafeo 0.5.x database is migrated to grafeo 0.6's single-file format on the first read-write start (the original is kept as `<path>.pre-0.6`), query results follow grafeo 0.6, and `graph_info` returns a new, smaller shape; see "Upgrading from grafeo-mcp 0.2" in the README. A database that grafeo 0.5 must keep opening stays on grafeo-mcp 0.2 with grafeo pinned below 0.6 (`uvx --from grafeo-mcp==0.2.0 --with "grafeo<0.6" grafeo-mcp`), since 0.2 alone now installs grafeo 0.6.

### Added

- **Time-travel reads**: `query_as_of` runs one reading GQL statement as the database was at `as_of` (seconds ago, or an ISO-8601 datetime with its offset), and `get_node_as_of` returns a node as it was then. Both need history: start the server with `GRAFEO_HISTORY_RETENTION=forever` or a number of seconds, which the database file then keeps.
- **`execute_gql` takes `params`**: values are referenced as `$name`. A parameter the query uses but `params` lacks is reported by name before anything runs.
- **`execute_gql` names what does not exist**: a reading query that finds no rows, or returns a column that is null in every row, gets a `hint` such as `Not in the graph: label :Persn (did you mean :Person?).` A query whose labels, edge types and properties all exist gets none.
- **`execute_gql` reports writes and warnings**: writing queries return `counters` (nodes, edges, properties and labels created, deleted, set or removed), and the engine's warnings come back as `warnings`.
- **`pagerank` and `betweenness_centrality` take `label`**: `pagerank(label="Person")` returns only people, ranked by scores computed over the whole graph. An unknown label is an error that points to `graph_info`.
- **Path patterns in `WHERE` and `DELETE` get specific hints**: the Cypher form `WHERE (p)-[:WORKS_AT]->(c)` gets the `EXISTS { ... }` and `MATCH` forms, and `DELETE (b)-[:WORKS_AT]->(c)` gets "bind the edge in `MATCH`, then `DELETE w`", instead of a general syntax check. Both rules are in `execute_gql`'s description.
- **Vector search from a node**: `vector_search`, `mmr_search` and `vector_graph_search` take `like_node_id` instead of a `query_vector` and search near that node's stored vector, leaving the node itself out. An agent without the index's embedding model can still ask what is most like a node.
- **Server instructions and version**: the server sends MCP `instructions` (start with `graph_info`, which tool for which job, how errors read) and reports its version in `serverInfo`.
- **`--host`, `--port`, `--version` and `--help`**: `grafeo-mcp streamable-http --port 9000` serves on another port (the default stays `127.0.0.1:8000`), and `grafeo-mcp --version` prints the grafeo-mcp and grafeo versions. An address other than loopback logs a warning that the server has no authentication.
- **Startup warnings**: without `GRAFEO_DB_PATH` the server logs that the database is in memory and lost when it stops. After migrating a grafeo 0.5.x database it logs the `.pre-0.6` copy it kept.
- **`graph://schema` lists indexes**: vector and text indexes, with the number of items in each.
- **Microsoft Agent Framework**: the framework's `MCPStdioTool` runs grafeo-mcp over stdio, and a `FoundryChatClient` agent can use its tools.
- **Python 3.15**: the package is tested on, and lists, Python 3.12 to 3.15.

### Changed

The first seven entries change what an existing setup sees on upgrade.

- **A grafeo 0.5.x database is migrated on the first read-write start**: grafeo 0.6 converts it in place and keeps the original as `<path>.pre-0.6`; afterwards grafeo 0.5.x cannot open it. Stop every grafeo-mcp 0.2 server and grafeo 0.5.x script that uses it and back it up first; a read-only server (`GRAFEO_READ_ONLY=1`) reads it without migrating.
- **`GRAFEO_DB_PATH` is always one file**: any path is stored as a single file, with its WAL in `<path>.wal/` while the server runs, and a 0.5.x WAL directory becomes a file at the same path (the directory is kept as `<path>.pre-0.6/`). A path that is a directory and not a 0.5.x database stops the server with a message to name a file instead.
- **Query results follow grafeo 0.6**: `1.5` is an exact decimal and comes back as a JSON number with its digits (`1.50`), overflow and division by zero fail instead of returning null, and `ORDER BY` puts nulls last. A `WHERE` right after `INSERT`, `CREATE`, `MERGE` or `DELETE` is an error.
- **`graph_info` has a new, smaller shape**: `nodes`, `edges`, `labels` and `edge_types` (each with its count and `{property: type}`, edge types also with their `endpoints`), `indexes`, `database` (`path`, `read_only`) and `engine`. The `info`, `schema`, `stats` and `server` sections are gone (`graph://stats` keeps memory and disk sizes), and a small graph's overview is 605 instead of 1,695 bytes.
- **One error format for every tool**: a failure, a wrong argument type and an unknown tool name included, is `Error: <tool>: <problem>. Hint: <next step>` with the engine's message unchanged, and the MCP result has `isError: true`. Messages used to start with `Failed to ...`, `<tool> error: ...` or `GQL query failed: ...` (or, for a wrong argument, a pydantic validation error) and were not flagged as errors.
- **An unknown command-line argument is an error**: `grafeo-mcp http` used to start a stdio server that waited silently for input; it now prints usage and exits with status 2.
- **`dijkstra` ignores edge direction by default**: a new `direction` argument is `both` (the default), `outgoing` (the 0.2 behaviour) or `incoming`, and the result names it. A call that relied on direction now passes `direction="outgoing"`; a directed search without a path hints at `direction="both"`.
- **The tool listing is half the size**: descriptions are short, argument documentation moved into each tool's input schema, and generated schema titles are left out. Measured as the `tools/list` result over stdio, 0.3.0 lists its 25 tools in 15,212 bytes, where 0.2.0 listed 23 in 31,800.
- **Embeddings show as a placeholder**: wherever a node or edge appears (`get_node`, `get_neighbors`, `search_nodes_by_label`, search and algorithm results, nodes in `execute_gql` rows, `graph://schema`), a list of more than 32 numbers is `<vector: 384 dims>`; `RETURN n.embedding` still returns the numbers. On the Silicon Valley demo dataset `get_node` is 275 instead of 8,297 characters and `search_nodes_by_label("AI")` 1,118 instead of 33,253.
- **`get_neighbors` and `search_nodes_by_label` keep to the output budget**: a result over about 8,000 characters is cut down to valid JSON, as for the other tools.
- **Results are sent once**: tools no longer declare an output schema, so a result is no longer repeated as `structuredContent`, and JSON has no spaces after `,` and `:`. A one-row `execute_gql` result is 228 instead of 439 bytes.
- **A failed query's hint follows the engine's error code**: syntax (`GRAFEO-Q001`), names and types (`GRAFEO-Q002`) or a value at run time such as division by zero (`GRAFEO-Q006`), instead of always suggesting a syntax check.
- **`create_vector_index` confirms in a sentence**: `Vector index created on :Doc.emb (384 dimensions, cosine).`, like `create_text_index`; it was `HNSW index created on :Doc.emb, 384d, cosine`.
- **`create_edge` checks both endpoints**: an edge to a missing node is refused with the missing node named; it used to create a dangling edge.
- **Arguments out of range are errors**: negative IDs, a `limit`, `k` or `top_k` below 1 and a `lambda_mult` outside 0 to 1 are refused with the argument named.
- **Tool annotations**: every tool declares `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`, so clients can tell reading tools from writing ones.
- **Read-only mode opens any existing database read-only in the engine**: before, only a `.grafeo` file was.
- **`delete_node` detaches in one step**: with `detach=True` the node and its edges are deleted in one `DETACH DELETE`.
- **`dijkstra` reads exact decimal weights**: a weight written in GQL as `2.5` counts as 2.5. A non-number, NaN, infinite or negative weight is an error.
- **`vector_graph_search` reports a failing expansion**: it used to skip it.
- **A database that cannot be opened names `GRAFEO_DB_PATH`**: for example one locked by another process stops the server with a message naming the path.

### Fixed

- **Startup problems print one line**: a bad `GRAFEO_HISTORY_RETENTION`, a `GRAFEO_DB_PATH` that is a directory, a database another process holds and an HTTP port in use each print `grafeo-mcp: error: ...` and exit with status 1 before the server starts. They printed a nested traceback of about 60 lines, and the client saw only a closed connection.
- **A wrong-size query vector no longer stops the server**: with grafeo 0.5 it made the HNSW index panic and closed the MCP connection. grafeo 0.6 refuses it with an error naming both sizes, and every tool turns an engine panic into an error result.
- **`execute_gql` runs `CREATE` as written**: a rewrite of `CREATE` into `INSERT` also changed string literals (`WHERE n.kind = 'CREATE'`) and broke `CREATE GRAPH`.
- **Resources can be read over MCP**: reading `graph://schema`, `graph://stats` or `graph://nodes/{node_id}` failed with the MCP SDK.
- **`graph://nodes/{id}` shows connections and `graph://schema` shows edge endpoints**: they showed every node as isolated and every edge type as `(?)-[:TYPE]->(?)`.
- **Truncated results are valid JSON**: output over 8,000 characters was cut mid-text. Entries are now dropped from the end and long strings shortened, and the result carries `truncated`, `omitted` and `note`.
- **`batch_import` is all or nothing**: it left partial batches behind. The whole batch is now checked before anything is written, and what the call created is removed when the engine rejects a node or edge partway.
- **`get_neighbors` refuses an unknown `direction`**: it returned both directions without a word.
- **`dijkstra` names a missing node**: it reported "no path".
- **`pagerank` refuses a damping factor outside 0 to 1**: it returned negative scores.
- **The `similarity_search` prompt matches the results**: it described a `similarity` field that results no longer have.

### Security

- **`execute_gql` honours read-only mode**: with `GRAFEO_READ_ONLY=1` it still ran writes. It now refuses write clauses and runs the rest in a transaction that is always rolled back, and an existing database is opened read-only in the engine as well.
- **No query injection through `edge_type`**: `get_neighbors`, `vector_graph_search` and `graph://schema` pasted edge types into the query text, so a crafted value could change the query, even in read-only mode. Edge types, node IDs and limits are now query parameters.

### Dependencies

- **grafeo 0.6.3** (requires `>=0.6.2,<0.7`; was `>=0.5`): tested against 0.6.2 and 0.6.3. grafeo-mcp 0.3 and 0.2 cannot share a database.
- **mcp 2.3** (requires `>=2.2,<3`, also for the `cli` extra; was `>=1.26,<2`): `grafeo_mcp.mcp` is an mcp 2.x `MCPServer` (mcp 2.x has no `FastMCP`).

## [0.2.0] - 2026-04-12

Test and documentation release: aligned with grafeo 0.5.37, with more tests, better error handling and documentation.

### Added

- **Error handling tests**: malformed GQL, dangling edges, duplicate nodes, missing node updates/deletes, invalid direction parameter.
- **Edge case tests**: vector search without index, algorithms on empty graph, dijkstra on disconnected graph, large result truncation.
- **Batch atomicity test**: documented that `batch_import` is not atomic; valid entries persist on partial failure.
- **Read-only exhaustive test**: parametrized over all 9 mutation tools for consistent error format.
- **Cypher normalization tests**: MERGE, MATCH, OPTIONAL MATCH, WITH clause coverage.
- **Resource mutation tests**: schema, stats, node resources verified after mutations.
- **Prompt rendering tests**: all 4 prompts verified with no unresolved placeholders.

### Changed

- Requires grafeo >=0.5 (tested against 0.5.37).
- README: tool count corrected from 16 to 23, added 7 missing tools to tables.
- README: added "Which tool when?" decision matrix.
- README: documented `@N` batch reference syntax.
- README: documented Cypher normalization scope.
- 174 tests passing, 82% coverage.

### Fixed

- Test assertions in `test_tools_query.py` used `or` instead of `and`, making them always pass.
- Node ID assertion in dijkstra test matched single characters instead of actual IDs.
- Prompt placeholder check now detects both `{{double}}` and `{single}` brace patterns.

## [0.1.3] - 2026-03-03

Feature release: CRUD completion, batch import, full-text search and read-only mode.

### Added

- **`update_node`**: update node properties with merge or replace semantics.
- **`delete_node`**: delete a node with optional detach (removes connected edges).
- **`update_edge`**: update edge properties with merge or replace semantics.
- **`delete_edge`**: delete an edge by ID.
- **`batch_import`**: bulk-create nodes and edges from JSON arrays with `@index` cross-references (max 500 nodes, 1000 edges per batch).
- **`search_text`**: full-text keyword search over string properties (requires text index).
- **`create_text_index`**: create a full-text search index on a string property.
- **Read-only mode**: set `GRAFEO_READ_ONLY=1` to disable all mutation tools; mutation tools remain visible but return a descriptive error guiding agents to read-only alternatives.

### Changed

- **Tool count**: 16 to 22 (6 new tools).
- **`AppContext`** now carries a `read_only` field, set from the `GRAFEO_READ_ONLY` environment variable at startup.
- 117 tests, 82% coverage.

## [0.1.2] - 2026-03-01

Quality and correctness release: shared helpers, dead code removal, and fixes for misleading output.

### Fixed

- **Vector search `similarity` field removed**: `vector_search`, `mmr_search`, and `vector_graph_search` no longer return a `similarity` field computed as `1.0 - distance`, which was only valid for cosine metric and produced wrong or negative values for euclidean/manhattan. The `distance` field (lower = more similar) is always correct regardless of metric.
- **Vector index detection**: `graph://schema` resource no longer uses a hardcoded heuristic that only detected vector data in a property named `embedding`. Now directs agents to `graph_info` and `create_vector_index` instead of guessing.
- **Connection summary truncation**: `graph://nodes/{id}` resource now warns when outgoing or incoming edge counts hit the internal LIMIT 100 cap, so agents know the totals may be incomplete.

### Changed

- **Shared tool helpers**: extracted `_truncate` and `_node_summary` into `tools/_helpers.py`, eliminating duplication between `vector.py` and `algorithms.py`.
- **Shared resource helpers**: unified `_format_value` into `resources/_helpers.py` with configurable thresholds, eliminating duplication between `schema.py` and `nodes.py`.
- **Dead normalization entries removed**: `_CYPHER_TO_GQL` in `query.py` no longer contains the no-op `MERGE` and `DETACH DELETE` entries (both map to themselves in GQL).
- **Truncation message style**: replaced em-dash with colon in truncation output to match project style conventions.

## [0.1.1] - 2026-02-11

Initial release: tools, resources and prompts over stdio and streamable HTTP.

### Added

- **14 MCP tools**: `execute_gql`, `create_node`, `create_edge`, `get_node`, `get_neighbors`, `search_nodes_by_label`, `graph_info`, `vector_search`, `mmr_search`, `create_vector_index`, `vector_graph_search`, `pagerank`, `dijkstra`, `louvain`, `betweenness_centrality`, `connected_components`.
- **3 MCP resources**: `graph://schema`, `graph://stats`, `graph://nodes/{node_id}`.
- **4 MCP prompts**: `explore_graph`, `knowledge_extraction`, `graph_analysis`, `similarity_search`.
- Schema-first design: `graph_info` as the agent entry point.
- Token-aware output: all list-returning tools have `limit` params and truncate large results.
- Cypher-to-GQL auto-normalization in `execute_gql`.
- Dual transport: stdio (default) and streamable-http for remote deployments.
- 75 tests, 79% coverage.

---

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[0.3.0]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/GrafeoDB/grafeo-mcp/releases/tag/v0.1.1
