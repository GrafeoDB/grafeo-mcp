[![CI](https://github.com/GrafeoDB/grafeo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/GrafeoDB/grafeo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/GrafeoDB/grafeo-mcp/graph/badge.svg)](https://codecov.io/gh/GrafeoDB/grafeo-mcp)
[![PyPI](https://img.shields.io/pypi/v/grafeo-mcp.svg)](https://pypi.org/project/grafeo-mcp/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

# grafeo-mcp

MCP server that exposes [GrafeoDB](https://grafeo.dev/) - an embedded graph database - to AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

One install, zero infrastructure. The MCP server *is* the database.

## Features

- **23 tools** - graph CRUD, GQL queries, batch import, full-text search, vector search, MMR, hybrid retrieval, PageRank, Dijkstra, Louvain and more
- **3 resources** - `graph://schema`, `graph://stats`, `graph://nodes/{id}`
- **4 workflow prompts** - guide agents through exploration, knowledge extraction, graph analysis and similarity search
- **GQL with Cypher-style syntax** - `CREATE`, `MERGE` and `OPTIONAL MATCH` run as written, with query parameters and write counters
- **Schema-first** - agents discover the graph structure before querying
- **Token-aware** - all tools have `limit` params and cut large results down to valid JSON
- **Agent-friendly errors** - every failure is one `Error: <tool>: ...` message with a hint, flagged `isError` over MCP
- **Embedded** - no separate database server to manage

## Quickstart

```bash
# Install
uv tool install grafeo-mcp

# Or run it without installing
uvx grafeo-mcp
```

grafeo-mcp needs grafeo 0.5.44 or later (below 0.7); see [Storage and upgrading](#storage-and-upgrading).

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "grafeo": {
      "command": "grafeo-mcp",
      "env": {
        "GRAFEO_DB_PATH": "/path/to/your/graph.grafeo"
      }
    }
  }
}
```

### Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "grafeo": {
      "command": "grafeo-mcp",
      "env": {
        "GRAFEO_DB_PATH": "./graph.grafeo"
      }
    }
  }
}
```

### VS Code / Copilot

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "grafeo": {
      "command": "grafeo-mcp",
      "env": {
        "GRAFEO_DB_PATH": "${workspaceFolder}/graph.grafeo"
      }
    }
  }
}
```

### HTTP transport

For remote or multi-client setups:

```bash
grafeo-mcp streamable-http
```

## Environment Variables

| Variable           | Description                                                                                | Default   |
| ------------------ | ------------------------------------------------------------------------------------------ | --------- |
| `GRAFEO_DB_PATH`   | Path to the database. Use a `.grafeo` file; it is created if it doesn't exist              | In-memory |
| `GRAFEO_READ_ONLY` | `1`, `true`, `yes` or `on` disables every write (mutation tools and writing `execute_gql`) | Off       |

### Read-only mode

With `GRAFEO_READ_ONLY=1` the mutation tools stay visible but return an error, and `execute_gql` refuses queries with `INSERT`, `CREATE`, `MERGE`, `SET`, `REMOVE`, `DELETE`, `DROP` or `ALTER` and runs the rest in a transaction that is always rolled back. When `GRAFEO_DB_PATH` names an existing `.grafeo` file, the server also opens it with grafeo's read-only mode: the engine itself rejects writes, several read-only servers can share the file, and grafeo 0.6 reads a 0.5.x file without migrating it.

## Storage and upgrading

- **Use a single-file `.grafeo` path.** Any other path (such as `graph.db`) creates a WAL-directory database. grafeo 0.5.x reopens a directory database without its vector, text and property indexes, so `vector_search` and `search_text` fail after a restart until the index is created again; the server logs a warning for such paths. The single file is grafeo's recommended format, and WAL-directory storage is deprecated as of grafeo 0.6.
- **One writer at a time.** A database file can be open for writing by one process. Run one grafeo-mcp server per file, or use read-only mode for extra readers.
- **Upgrading to grafeo 0.6.** grafeo 0.6.0 writes a new file format. The first read-write open of a 0.5.x `.grafeo` file migrates it in place and keeps the old file next to it as `graph.grafeo.pre-0.6` (and its WAL as `graph.grafeo.pre-0.6.wal`). Before the first start on 0.6, stop every 0.5.x process that uses the file and make sure there is free disk space for a copy of the database. After the migration grafeo 0.5.x can no longer open the file; to go back, see [Upgrading from 0.5](https://grafeo.dev/user-guide/persistence/persistent/#upgrading-from-05). A read-only server does not migrate the file. grafeo 0.7 will not read 0.5.x files, so open each database read-write with 0.6 once before moving on.
- **Pinning.** Until grafeo 1.0 a minor release may change the file format or the API, so grafeo-mcp pins the grafeo minor versions it is tested with (currently `grafeo>=0.5.44,<0.7`). A weekly CI job runs the test suite against the newest grafeo in that range, pre-releases included.

## Tools

### Query

| Tool          | Description                                            |
| ------------- | ------------------------------------------------------ |
| `execute_gql` | Run one GQL query, with parameters and write counters  |

### Graph CRUD & Traversal

| Tool                    | Description                                |
| ----------------------- | ------------------------------------------ |
| `create_node`           | Create a node with labels and properties   |
| `create_edge`           | Create a directed edge between two nodes   |
| `get_node`              | Retrieve a node by ID                      |
| `update_node`           | Update properties on an existing node      |
| `delete_node`           | Delete a node (with optional detach)       |
| `update_edge`           | Update properties on an existing edge      |
| `delete_edge`           | Delete an edge by ID                       |
| `get_neighbors`         | Explore a node's neighborhood (1-hop)      |
| `search_nodes_by_label` | Find nodes by label with pagination        |
| `graph_info`            | Schema, stats, indexes and engine features |

### Batch Import

| Tool           | Description                                       |
| -------------- | ------------------------------------------------- |
| `batch_import` | Bulk-create nodes and edges from JSON arrays      |

### Full-Text Search

| Tool                | Description                                     |
| ------------------- | ----------------------------------------------- |
| `create_text_index` | Create a full-text search index on a property   |
| `search_text`       | Keyword search over indexed string properties   |

### Vector Search

| Tool                  | Description                                          |
| --------------------- | ---------------------------------------------------- |
| `vector_search`       | k-NN similarity search (HNSW)                        |
| `mmr_search`          | Diversity-aware search (Maximal Marginal Relevance)  |
| `create_vector_index` | Create HNSW index on a label + property              |
| `vector_graph_search` | Hybrid: vector search + graph neighborhood expansion |

### Graph Algorithms

| Tool                     | Description                               |
| ------------------------ | ----------------------------------------- |
| `pagerank`               | Rank nodes by importance                  |
| `dijkstra`               | Shortest weighted path between two nodes  |
| `louvain`                | Community detection (Louvain modularity)  |
| `betweenness_centrality` | Find bridge/bottleneck nodes              |
| `connected_components`   | Find disconnected subgraphs               |

## Resources

| URI                       | Description                                 |
| ------------------------- | ------------------------------------------- |
| `graph://schema`          | Rich schema: labels, properties, edge types |
| `graph://stats`           | Counts, memory, disk, config info           |
| `graph://nodes/{node_id}` | Node details + connection summary           |

## Prompts

| Prompt                 | Description                                       |
| ---------------------- | ------------------------------------------------- |
| `explore_graph`        | Guided exploration of the graph structure         |
| `knowledge_extraction` | Extract entities and relationships from text      |
| `graph_analysis`       | Structural analysis: communities, PageRank, hubs  |
| `similarity_search`    | Vector-powered semantic search with graph context |

## Which tool when?

| I want to...                          | Use this tool             | Not this                 |
| ------------------------------------- | ------------------------- | ------------------------ |
| Add a single node                     | `create_node`             | `execute_gql`, `batch_import` |
| Add a single edge                     | `create_edge`             | `execute_gql`            |
| Load many nodes and edges at once     | `batch_import`            | `create_node` in a loop  |
| Look up a node by ID                  | `get_node`                | `execute_gql`            |
| Create or update a node by a key      | `execute_gql` with `MERGE` and `params` | `create_node` |
| Update a node's properties            | `update_node`             | `execute_gql`            |
| Delete a node                         | `delete_node`             | `execute_gql`            |
| Update an edge's properties           | `update_edge`             | `execute_gql`            |
| Delete an edge                        | `delete_edge`             | `execute_gql`            |
| Browse nodes of a type                | `search_nodes_by_label`   | `execute_gql`            |
| Explore one hop from a node           | `get_neighbors`           | `execute_gql`            |
| Run a complex or multi-hop query      | `execute_gql`             | multiple `get_neighbors` |
| Search by keyword in text             | `search_text`             | `execute_gql`            |
| Find similar nodes by embedding       | `vector_search`           | `execute_gql`            |
| Find similar nodes + graph context    | `vector_graph_search`     | `vector_search` + `get_neighbors` |
| Find the most important nodes         | `pagerank`                | `execute_gql`            |
| Find shortest path between two nodes  | `dijkstra`                | `execute_gql`            |
| Detect communities                    | `louvain`                 | `execute_gql`            |
| Understand the graph before querying  | `graph_info`              | `search_nodes_by_label`  |

## Batch reference syntax

The `batch_import` tool lets edges reference nodes created in the same batch using `@N` notation, where `N` is the zero-based index into the `nodes` array:

```python
batch_import(
    nodes=[
        {"labels": ["Person"], "properties": {"name": "Alice"}},  # @0
        {"labels": ["Person"], "properties": {"name": "Bob"}},    # @1
    ],
    edges=[
        {"source_ref": "@0", "target_ref": "@1", "edge_type": "KNOWS"},
    ],
)
```

You can also mix batch references with existing node IDs: `{"source_ref": "@0", "target_ref": 42, ...}`.

A batch is all or nothing: it is checked completely before anything is written (labels, edge types, `@N` references, and that referenced node IDs exist), and if the engine rejects a node or edge partway (for example a `UNIQUE` constraint), everything the call created is removed again.

## Queries

`execute_gql` passes the query text to grafeo's GQL engine unchanged. The engine also accepts common Cypher syntax such as `CREATE`, `MERGE`, `OPTIONAL MATCH` and `DETACH DELETE`, so agents trained on Cypher work out of the box.

- **One statement per call.** Text with several statements separated by `;` is refused before it runs (a trailing `;` is fine). Chain clauses instead (`INSERT ... INSERT ...`, `MATCH ... INSERT ...`) or send separate calls.
- **Parameters.** Pass values in `params` and reference them as `$name`, e.g. query `MERGE (p:Person {name: $name}) SET p += $props RETURN id(p)` with `params={"name": "Ada", "props": {"born": 1815}}`. A parameter the query uses but `params` lacks is reported by name.
- **Write counters.** Results of writing queries include `counters` (nodes, edges, properties and labels created, deleted, set or removed).
- **Embeddings.** Store vectors through a parameter (`INSERT (:Doc {emb: $emb})`) or `vector([...])`: grafeo 0.5.44 stores a plain list literal as a list, which vector indexes skip. `create_node`, `batch_import` and `update_node` store lists of floats as vectors.

## Errors

Every tool returns a string. A failure is a single message of the form `Error: <tool>: <what went wrong>. Hint: <what to try next>`, with the engine's own message included unchanged; over MCP it is returned with `isError: true`. Successful results are JSON, except the confirmation sentences of `delete_node`, `delete_edge`, `create_vector_index` and `create_text_index`.

## Output size

Results that would exceed about 8,000 characters are cut down to valid JSON: entries are dropped from the end of the largest lists, long strings end with `... [N chars]`, and the result gets `truncated: true`, an `omitted` map (path to number of entries dropped) and a `note`. A tool that normally returns a JSON array (`vector_search`, `mmr_search`, `search_text`) then returns `{"results": [...], "truncated": true, ...}`. Embedding properties longer than 32 values are left out of node summaries. `execute_gql`, `search_nodes_by_label` and `get_neighbors` are bounded by their `limit` instead.

## Development

```bash
git clone https://github.com/GrafeoDB/grafeo-mcp
cd grafeo-mcp
uv sync
uv run pytest          # Run tests
uv run ruff check .    # Lint
uv run ruff format .   # Format
uv run ty check        # Type check
```

`tests/test_grafeo_contract.py` pins every grafeo behavior the tools rely on, so a grafeo release that changes one fails with a message naming it. To try the newest grafeo release (pre-releases included):

```bash
uv sync --upgrade-package grafeo --prerelease allow
uv run --no-sync pytest
```

## See Also

- **[grafeo-memory](https://github.com/GrafeoDB/grafeo-memory)** includes a built-in MCP server (`grafeo-memory-mcp`) that wraps the high-level memory API: extract, reconcile, search, summarize. If you need AI memory management rather than raw graph access, use `uv add grafeo-memory[mcp]`.

## License

Apache-2.0
