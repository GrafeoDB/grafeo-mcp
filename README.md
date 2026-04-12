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
- **GQL with Cypher auto-normalization** - agents trained on Cypher syntax work out of the box
- **Schema-first** - agents discover the graph structure before querying
- **Token-aware** - all tools have `limit` params and truncate large results
- **Embedded** - no separate database server to manage

## Quickstart

```bash
# Install
uv tool install grafeo-mcp

# Or with pip
pip install grafeo-mcp
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "grafeo": {
      "command": "grafeo-mcp",
      "env": {
        "GRAFEO_DB_PATH": "/path/to/your/graph.db"
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
        "GRAFEO_DB_PATH": "./graph.db"
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
        "GRAFEO_DB_PATH": "${workspaceFolder}/graph.db"
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

| Variable         | Description                                               | Default   |
| ---------------- | --------------------------------------------------------- | --------- |
| `GRAFEO_DB_PATH` | Path to the database file. Creates it if it doesn't exist | In-memory |

## Tools

### Query

| Tool          | Description                                            |
| ------------- | ------------------------------------------------------ |
| `execute_gql` | Run GQL queries (Cypher syntax auto-normalized to GQL) |

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
| `graph_info`            | Schema, stats, labels, edge types, indexes |

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

## Cypher normalization

The `execute_gql` tool automatically normalizes common Cypher syntax to GQL so agents trained on Cypher work out of the box. Currently the following transformations are applied:

| Cypher keyword | GQL equivalent |
| -------------- | -------------- |
| `CREATE`       | `INSERT`       |

Keywords that are shared between Cypher and GQL (such as `MATCH`, `RETURN`, `WHERE`, `WITH`, `LIMIT`, `DETACH DELETE`) pass through unchanged. Cypher-only keywords like `MERGE` or `OPTIONAL MATCH` are **not** supported and will produce a clear error message from the query engine.

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

## See Also

- **[grafeo-memory](https://github.com/GrafeoDB/grafeo-memory)** includes a built-in MCP server (`grafeo-memory-mcp`) that wraps the high-level memory API — extract, reconcile, search, summarize. If you need AI memory management rather than raw graph access, use `uv add grafeo-memory[mcp]`.

## License

Apache-2.0
