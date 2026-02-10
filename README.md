# grafeo-mcp

MCP (Model Context Protocol) server for the [Grafeo](https://github.com/GrafeoDB/grafeo) graph database.

Exposes Grafeo as a set of MCP tools so that AI agents and assistants can query, traverse, and mutate graph data over stdio or HTTP.

## Status

Work in progress.

## Features (planned)

- 12 tools across query, graph, vector, and algorithm modules
- GQL, Cypher, and Gremlin query execution
- Node/edge CRUD and label-based search
- Vector similarity search and HNSW index creation
- Graph algorithms: PageRank, shortest path, community detection
- stdio and streamable-HTTP transports

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management

## License

Apache-2.0 &mdash; see [LICENSE](LICENSE) for details.
