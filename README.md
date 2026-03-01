[![CI](https://github.com/GrafeoDB/grafeo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/GrafeoDB/grafeo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/GrafeoDB/grafeo-mcp/graph/badge.svg)](https://codecov.io/gh/GrafeoDB/grafeo-mcp)
[![PyPI](https://img.shields.io/pypi/v/grafeo-mcp.svg)](https://pypi.org/project/grafeo-mcp/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

# grafeo-mcp

MCP server that exposes [GrafeoDB](https://grafeo.dev/) - an embedded graph database - to AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

One install, zero infrastructure. The MCP server *is* the database.

## Features

- **16 tools** - graph CRUD, GQL queries, vector search, MMR, hybrid retrieval, PageRank, Dijkstra, Louvain and more
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
| `get_neighbors`         | Explore a node's neighborhood (1-hop)      |
| `search_nodes_by_label` | Find nodes by label with pagination        |
| `graph_info`            | Schema, stats, labels, edge types, indexes |

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
