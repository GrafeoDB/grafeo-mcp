# Changelog

All notable changes to grafeo-mcp, an MCP server that gives agents a Grafeo database.

## [0.3.0] - 2026-11-14

grafeo 0.6 release: runs on grafeo 0.6.2 and the mcp 2.x SDK, adds time-travel reads, and fixes a server crash, the read-only bypass in `execute_gql`, query injection, resources that could not be read over MCP and truncated output that was not valid JSON. Before upgrading: a grafeo 0.5.x database moves to grafeo 0.6's single-file format on the first read-write start (the original is kept as `<path>.pre-0.6`), and query results follow grafeo 0.6 (exact decimals come back as JSON numbers); see "Upgrading from grafeo-mcp 0.2" in the README. A database that grafeo 0.5 must keep opening stays on grafeo-mcp 0.2.

### Added

- **Time-travel reads**: new read-only tools `query_as_of` (one GQL statement as the database was at a point in time) and `get_node_as_of` (a node's old labels and properties). `as_of` is seconds ago ("300") or an ISO-8601 datetime with its offset. Start the server with `GRAFEO_HISTORY_RETENTION=forever` (or a number of seconds) so the database keeps the history these reads need; a database file stores the setting. Both tools work in read-only mode.
- **`execute_gql` `params`**: optional query parameters, referenced as `$name`. A parameter the query uses but `params` lacks is reported by name before anything runs.
- **`execute_gql` write counters**: results of writing queries include `counters` (nodes, edges, properties and labels created, deleted, set or removed).
- **`execute_gql` checks for one statement per call**: text with several `;`-separated statements is refused with a hint before it runs.
- **`graph_info`**: `indexes` (vector and text indexes with their item counts, property indexes), `engine` (grafeo version and compiled-in features) and `server` (`read_only`).
- **`graph://schema`** lists vector and text indexes.
- **Exact decimals as JSON numbers**: every tool writes a grafeo 0.6 decimal as a JSON number with its exact digits (`1.50`, `0.3`), also inside nodes, lists and maps and through output truncation; written as text, as other values JSON cannot hold, it would have been the string `"1.50"`.
- **Migration notice**: when the server migrates a grafeo 0.5.x database it logs a warning naming the `.pre-0.6` copy it keeps.
- **Microsoft Agent Framework / Foundry**: `tests/test_agent_framework_mcp.py` runs the framework's `MCPStdioTool` against this server over stdio (CRUD via `execute_gql`, time travel via `query_as_of`) and wires a `FoundryChatClient` agent with the grafeo-mcp tools. The framework needs mcp>=2.2, which this repo's own pin satisfies, so the tests run in the development environment (`uv run pytest`).
- **Engine contract tests** (`tests/test_grafeo_contract.py`): every grafeo behavior the tools rely on, so an engine release that changes one fails with a message naming it.
- **Engine contract tests for grafeo 0.6.2's type rules**: they pin the rules the tools rely on and surface: a string never equals a number, wrong-kind operands raise (reported through the tools' error contract), procedure arguments are validated, and a weighted algorithm refuses a non-number weight.
- **Tests** for the MCP protocol end to end (tool listing, annotations, error flags, resources, prompts, an engine panic), file-backed databases (restart, read-only opens, locked files), the error path of every tool, output truncation and the query scanner, and for grafeo 0.6: decimals in tool output, single-file storage, and the migration of databases written by grafeo 0.5.44 (`tests/fixtures/grafeo-0.5.44`, a `.grafeo` file and a WAL directory, read-write and read-only, directly and through the server): 174 to 536 tests, coverage 82% to 96%.
- **CI**: a weekly `Latest grafeo` workflow (also started by hand) runs the suite against the newest grafeo in the supported range, pre-releases included.
- **Python 3.15**: tested on Python 3.15; CI runs the tests on 3.12 to 3.15 and the package lists 3.12 to 3.15 in its classifiers.

### Changed

The first three entries change what an existing setup sees on upgrade.

- **A grafeo 0.5.x database is migrated on the first read-write start**: grafeo 0.6 converts it in place and keeps the original, unchanged, as `<path>.pre-0.6` (a leftover WAL as `<path>.pre-0.6.wal`); the server logs a warning naming that copy. Stop every grafeo-mcp 0.2 server and grafeo 0.5.x script that uses the database first, back it up and leave free disk space for one copy; after the migration grafeo 0.5.x cannot open it. A read-only server (`GRAFEO_READ_ONLY=1`) reads a 0.5.x database without migrating it.
- **`GRAFEO_DB_PATH` is always a single file**: grafeo 0.6 stores any path, whatever its extension, as one file, with its WAL in `<path>.wal/` while the server runs. A 0.5.x WAL-directory database (0.5.x made one for a path without `.grafeo`, such as `graph.db`) becomes a file at the same path, and the directory is kept as `<path>.pre-0.6/`. A path that is an existing directory and not a 0.5.x database, an empty one included, now stops the server with a message to name a file instead (grafeo 0.5.x created a database in it). The warning about WAL-directory paths is gone.
- **Query results follow grafeo 0.6** (described in `execute_gql`'s tool description): a GQL number with a point is an exact decimal (`0.1 + 0.2` is `0.3`, `1.50` keeps its scale; `1.5e0` is a float), integer or decimal overflow and division by zero fail the query instead of returning null, `ORDER BY` puts nulls last in both directions, a `WHERE` or `FILTER` right after `INSERT`, `CREATE`, `MERGE` or `DELETE` is an error, and statements nest at most 64 levels deep (values 128).
- **Edges to missing nodes**: grafeo (since 0.5.44) refuses edges to missing nodes, deleting a node that still has edges and property writes to missing nodes or edges; `create_edge` checks both endpoints first and names a missing one (it used to create dangling edges).
- **Engine messages**: grafeo 0.6 starts its error messages with the error code (`GRAFEO-V001: ...`) and words some of them differently; tools pass them on unchanged after `Error: <tool>:`.
- **Read-only mode opens any existing database read-only in the engine**: with grafeo 0.6 every database is a file, so the engine's read-only open no longer depends on the `.grafeo` extension.
- **The vector tools no longer compare the query vector with a stored vector first**: that check worked around the grafeo 0.5 panic and sampled at most 20 nodes, so it could miss; grafeo 0.6 checks the size against the index itself.
- **`dijkstra` reads exact decimal weights**: on grafeo 0.6.2 an edge weight written in GQL as `2.5` counts as 2.5, so `weight_property` may hold integers, floats or decimals. A non-number, NaN, infinite or negative weight is an error.
- **One error format for every tool**: a failure is a single string, `Error: <tool>: <problem>. Hint: <next step>`, with the engine's message unchanged, and the MCP result has `isError: true`. Messages used to start with `Failed to ...`, `<tool> error: ...` or `GQL query failed: ...` and were never flagged as errors.
- **`delete_node` with `detach=True`** deletes the node and its edges in one `DETACH DELETE` statement.
- **`vector_graph_search`** reports a failing expansion query instead of skipping it.
- **Arguments out of range** (negative IDs, `limit`, `k` or `top_k` below 1, `lambda_mult` outside 0 to 1) are errors that name the argument.
- **Tool annotations**: every tool declares `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`, so clients can tell reading tools from writing ones.
- **Storage**: README and example configs use `.grafeo` file paths, and a database that cannot be opened (for example locked by another process) stops the server with a message naming `GRAFEO_DB_PATH`.
- **README**: documents `GRAFEO_READ_ONLY`, the upgrade from grafeo-mcp 0.2 (migration, backups, the `.pre-0.6` copy), what grafeo 0.6 changes for queries, the version pin, the error format and output budget; tool descriptions no longer claim that `MERGE` and `OPTIONAL MATCH` are unsupported.
- **CI**: GitHub Actions updated (`actions/checkout` v7, `astral-sh/setup-uv` v10.3.0, `codecov/codecov-action` v7, `actions/upload-artifact` v7, `actions/download-artifact` v8), and the ruff pre-commit hook to v0.17.1.

### Fixed

- **A wrong-size query vector stopped the server**: `vector_search`, `mmr_search` and `vector_graph_search` with a query vector of another dimension than the index made grafeo 0.5's HNSW index panic, and the panic (a `BaseException`) escaped every handler and closed the MCP connection. grafeo 0.6 refuses such a vector (and an empty or non-finite one) with an error naming both sizes, which the tools return, and every tool turns any engine panic into an error result.
- **`execute_gql` ignored read-only mode**: with `GRAFEO_READ_ONLY=1` it still ran writes. It now refuses queries with write clauses and runs the rest in a transaction that is always rolled back; an existing database is also opened with grafeo's read-only mode, so the engine rejects writes too.
- **`execute_gql` rewrote every `CREATE`**: the regex that turned Cypher `CREATE` into `INSERT` also changed string literals (`WHERE n.kind = 'CREATE'`) and broke statements such as `CREATE GRAPH`. It is removed: grafeo's GQL accepts `CREATE` as written.
- **Query injection through `edge_type`**: `get_neighbors`, `vector_graph_search` and `graph://schema` pasted edge types into the query text, so a crafted value could change the query (even in read-only mode). Edge types, node IDs and limits are now query parameters.
- **Resources could not be read over MCP**: `graph://schema` and `graph://stats` were registered as templates without parameters, which the MCP SDK never matches, and every read of `graph://nodes/{node_id}` failed because the SDK rebuilds a typed context argument without its request. All three work now.
- **`graph://nodes/{id}` showed every node as isolated, and `graph://schema` showed `(?)-[:TYPE]->(?)` for every edge type**: both read query rows by position, but rows are dicts keyed by column, and the error was swallowed.
- **Truncated results were not valid JSON**: output over the 8,000-character budget was cut mid-text. It is now cut by entries (and long strings shortened), stays valid JSON and carries `truncated`, `omitted` and `note`.
- **`batch_import` left partial batches behind**: nodes were created before the edges were checked. The whole batch is now checked first, and if the engine rejects a node or edge partway, the nodes and edges the call created are removed again.
- **`get_neighbors` with an unknown `direction`** returned both directions without a word; it is now an error.
- **`dijkstra` with a missing node** reported "no path"; it now names the node that does not exist.
- **`pagerank` accepted a damping factor outside 0 to 1** and returned meaningless negative scores.
- **`similarity_search` prompt** described a `similarity` field that results no longer have, and sent agents to `graph_info` for vector indexes it did not list.

### Dependencies

- **grafeo 0.6.2** (requires `>=0.6.2,<0.7`; was `>=0.5`): tested against 0.6.2. grafeo 0.6 writes a new file format, so grafeo-mcp 0.3 and grafeo-mcp 0.2 (grafeo 0.5) cannot share a database.
- **mcp 2.3** (requires `>=2.2,<3`, also for the `cli` extra; was `>=1.26,<2`): the server is an mcp 2.x `MCPServer` (mcp 2.x has no FastMCP), so code that imports `grafeo_mcp.mcp` gets an `MCPServer`.
- **Locked versions**: locked to their latest compatible releases (among them mcp 2.3, pydantic 2.14, starlette 1.10 and uvicorn 0.54; for development ruff 0.17, ty 0.0.104, pytest 9.2 and prek 0.5); minimums raised only for grafeo and mcp. Development dependencies moved from the deprecated `[tool.uv] dev-dependencies` to `[dependency-groups]` (`uv sync` installs them as before) and add `agent-framework-core`, `agent-framework-foundry` and `tenacity` for the Agent Framework tests.

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

---

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[0.3.0]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/GrafeoDB/grafeo-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/GrafeoDB/grafeo-mcp/releases/tag/v0.1.1
