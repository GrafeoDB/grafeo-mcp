<picture>
  <source media="(max-width: 556px) and (prefers-color-scheme: dark), (min-width: 768px) and (max-width: 844px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/GrafeoDB/grafeo-mcp/main/.github/readme/header-narrow-dark.svg">
  <source media="(max-width: 556px), (min-width: 768px) and (max-width: 844px)" srcset="https://raw.githubusercontent.com/GrafeoDB/grafeo-mcp/main/.github/readme/header-narrow-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/GrafeoDB/grafeo-mcp/main/.github/readme/header-dark.svg">
  <img alt="grafeo-mcp: An MCP server that gives agents a Grafeo database: queries, search and graph algorithms." src="https://raw.githubusercontent.com/GrafeoDB/grafeo-mcp/main/.github/readme/header-light.svg" width="100%">
</picture>

[![CI](https://github.com/GrafeoDB/grafeo-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/GrafeoDB/grafeo-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/GrafeoDB/grafeo-mcp/graph/badge.svg)](https://codecov.io/gh/GrafeoDB/grafeo-mcp)
[![PyPI](https://img.shields.io/pypi/v/grafeo-mcp.svg)](https://pypi.org/project/grafeo-mcp/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/GrafeoDB/grafeo-mcp/blob/main/LICENSE)

MCP server that exposes [GrafeoDB](https://grafeo.dev/), an embedded graph database, to AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

One install, zero infrastructure. The MCP server *is* the database.

grafeo-mcp is one of Grafeo's AI integrations; [grafeo.ai](https://grafeo.ai) is their front page.

## Features

- **25 tools**: graph CRUD, GQL queries, time-travel reads, batch import, full-text search, vector search, MMR, hybrid retrieval, PageRank, Dijkstra, Louvain and more
- **2 resources and 1 resource template**: `graph://schema` and `graph://stats`, and `graph://nodes/{node_id}` for any node
- **4 workflow prompts**: guide agents through exploration, knowledge extraction, graph analysis and similarity search
- **GQL with Cypher-style syntax**: `CREATE`, `MERGE` and `OPTIONAL MATCH` run as written, with query parameters and write counters
- **Schema-first**: the server's instructions tell agents to read the graph structure with `graph_info` before querying
- **Token-aware**: the 25 tools list in about 15 KB, results are compact JSON sent once, all tools have `limit` params, and large results are cut down to valid JSON
- **Agent-friendly errors**: every failure is one `Error: <tool>: ...` message, flagged `isError` over MCP, with a hint naming the next step where the message alone does not
- **Embedded**: no separate database server to manage

## Quickstart

```bash
# Install
uv tool install grafeo-mcp

# Or run it without installing
uvx grafeo-mcp
```

grafeo-mcp 0.3 needs Python 3.12 or later and grafeo 0.6, which installs with it. Coming from grafeo-mcp 0.2: your database is migrated to the grafeo 0.6 format on the first start, see [Upgrading from grafeo-mcp 0.2](#upgrading-from-grafeo-mcp-02-grafeo-05).

Set `GRAFEO_DB_PATH` to keep your data: without it the database lives in memory and is gone when the client stops the server. `grafeo-mcp --version` prints the grafeo-mcp and grafeo versions, `grafeo-mcp --help` the options.

The configurations below assume `uv tool install grafeo-mcp`. A client that does not see your shell's `PATH` (Claude Desktop often does not) may not find `grafeo-mcp`; use `"command": "uvx", "args": ["grafeo-mcp"]` instead, or the full path that `uv tool dir --bin` shows.

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

```bash
claude mcp add grafeo --scope project -e GRAFEO_DB_PATH=./graph.grafeo -- grafeo-mcp
```

or add to `.mcp.json` in your project root:

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

For clients that connect to a running server instead of starting one:

```bash
grafeo-mcp streamable-http                  # http://127.0.0.1:8000/mcp
grafeo-mcp streamable-http --port 9000      # another port
grafeo-mcp streamable-http --host 0.0.0.0   # listen on every interface
```

Point the client at `http://<host>:<port>/mcp`. All clients share one database. The server has no authentication: on any address other than `127.0.0.1`, `localhost` or `::1` anyone who reaches the port can read and change the database, and the server logs a warning saying so. Put it behind a proxy that authenticates, or set `GRAFEO_READ_ONLY=1`. The legacy `sse` transport takes the same options.

## Try it with the demo dataset

The Silicon Valley dataset from [grafeo.ai](https://grafeo.ai) holds Pied Piper's world: 64 nodes (people, companies, products, AIs) and 149 edges, with a MiniLM embedding (384 dimensions) and a cosine vector index for every label. Load it into a file:

```bash
uv run --with "grafeo-datasets[grafeo]" python -c "import grafeo; from grafeo_datasets import silicon_valley; db = grafeo.GrafeoDB('pied-piper.grafeo'); silicon_valley.load(db, vectors=True); db.close()"
```

Point the server at it, for example in Claude Code:

```bash
claude mcp add pied-piper -e GRAFEO_DB_PATH=./pied-piper.grafeo -- grafeo-mcp
```

Then ask. These are the calls an agent makes (node IDs as in a fresh load):

| Ask                                       | Call                                                                                                                                                  | Answer                                                                  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| How is Son of Anton related to Anton?     | `execute_gql`: `MATCH (s:AI {name: 'Son of Anton'})<-[:BUILT]-(p:Person)-[:BUILT]->(a:AI {name: 'Anton'}) RETURN p.name AS builder`                   | Bertram Gilfoyle built both                                             |
| Does Jian-Yang's fridge talk?             | `execute_gql`: `MATCH (f:AI {name: $name})<-[:OWNS]-(p:Person) RETURN f.talks AS talks, p.name AS owner` with `params={"name": "Jian-Yang's fridge"}` | `talks: true`, owned by Jian-Yang                                       |
| Who invested in Pied Piper?               | `execute_gql`: `MATCH (i)-[e:INVESTED_IN]->(:Company {name: 'Pied Piper'}) RETURN i.name AS investor, e.round AS round ORDER BY e.date`               | Erlich Bachman, Peter Gregory, Russ Hanneman (Series A), Raviga Capital |
| How does Son of Anton fix bugs?           | `execute_gql`: `MATCH (s:AI {name: 'Son of Anton'}) RETURN s.bug_fix_strategy AS fix, s.meat_ordered_for_lunch_lb AS meat_lb`                         | "delete the code", and it once ordered 4000 lb of meat                  |
| How many commas does Russ have?           | `execute_gql`: `MATCH (r:Person {name: 'Russ Hanneman'}) RETURN r.net_worth_commas AS commas, r.roi_stands_for AS roi`                                | 3, and ROI stands for "Radio on internet"                               |
| What is most like Jian-Yang's fridge?     | `vector_search(label="AI", property="embedding", like_node_id=30, k=2)`                                                                               | Anton (distance 0.574), Fiona (0.760)                                   |
| Who is the most central person?           | `pagerank(label="Person", top_k=1)`                                                                                                                   | Richard Hendricks                                                       |
| How is Richard connected to Son of Anton? | `dijkstra(source_id=51, target_id=58)`                                                                                                                | Richard Hendricks, Bertram Gilfoyle, Son of Anton                       |
| Jack Barker takes over Hooli              | `execute_gql`: `MATCH (j:Person {name: 'Jack Barker'}), (h:Company {name: 'Hooli'}) INSERT (j)-[:WORKS_AT {role: 'CEO'}]->(h)`                        | `counters.edges_created: 1`                                             |

`like_node_id` searches near a node's stored vector, so an agent without its own embedding model can still ask what is alike. When a query misses, the result says why: `MATCH (a:Ai) RETURN a.name` returns `"hint": "Not in the graph: label :Ai (did you mean :AI?)."`, and the Cypher form `WHERE (p)-[:BUILT]->(:AI)` gets a hint to write `WHERE EXISTS { (p)-[:BUILT]->(:AI) }`. Add `GRAFEO_READ_ONLY=1` to explore without changing the file.

## Environment Variables

| Variable                   | Description                                                                                                                       | Default                                       |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `GRAFEO_DB_PATH`           | Path to the database file (such as `graph.grafeo`); it is created if nothing exists there                                         | In-memory (lost when the server stops)        |
| `GRAFEO_READ_ONLY`         | `1`, `true`, `yes` or `on` disables every write (mutation tools and writing `execute_gql`)                                        | Off                                           |
| `GRAFEO_HISTORY_RETENTION` | How far back the database keeps history for `query_as_of` and `get_node_as_of`: `off`, `forever` or a number of seconds (above 0) | The stored setting (`off` for a new database) |

A database file stores its history retention, so the setting stays in effect on later starts without the variable. A read-only server keeps the setting stored in the existing database.

### Read-only mode

With `GRAFEO_READ_ONLY=1` the mutation tools stay visible but return an error, and `execute_gql` refuses queries with `INSERT`, `CREATE`, `MERGE`, `SET`, `REMOVE`, `DELETE`, `DROP` or `ALTER` and runs the rest in a transaction that is always rolled back. When `GRAFEO_DB_PATH` names an existing database, the server also opens it with grafeo's read-only mode: the engine itself rejects writes, several read-only servers can share the file while no process has it open for writing, and a grafeo 0.5.x database is read without migrating it.

## Storage and upgrading

- **One file per database.** With grafeo 0.6 a database is always a single file at `GRAFEO_DB_PATH`, whatever its name (`.grafeo` is the convention). While the server runs, the write-ahead log lives next to it in `<path>.wal/`; a clean shutdown folds it into the file. A path that names an existing directory stops the server with an error, unless the directory is a grafeo 0.5.x database (see below): name a file inside it instead, such as `graph.grafeo`.
- **One writer at a time.** A database open for writing is locked: no other process can open it, not even read-only (`GRAFEO-S004 Database locked`). Run one grafeo-mcp server per database. Several `GRAFEO_READ_ONLY=1` servers can share a file, but only while no process has it open for writing.
- **Backups.** Stop the server (or every process that has the database open for writing), then copy the database file. Keep the copy somewhere else than `<path>.pre-0.6`, which the migration below uses.
- **Pinning.** Until grafeo 1.0 a minor release may change the file format or the API, so grafeo-mcp pins the grafeo minor version it is tested with (currently `grafeo>=0.6.2,<0.7`). A weekly CI job runs the test suite against the newest grafeo in that range.

### Upgrading from grafeo-mcp 0.2 (grafeo 0.5)

grafeo-mcp 0.3 runs on grafeo 0.6, which writes a new file format. The first read-write open of a grafeo 0.5.x database migrates it in place:

1. Stop every process that uses the database: grafeo-mcp 0.2 servers and any script on grafeo 0.5.x.
2. Back it up (the file, or the whole directory for a WAL-directory database such as `graph.db/`), and make sure there is free disk space for one more copy of the database.
3. Upgrade: `uv tool upgrade grafeo-mcp` (or `uvx grafeo-mcp@latest`).
4. Start the server once without `GRAFEO_READ_ONLY`. It migrates the database and logs a warning naming the copy of the original it keeps:
   - a `.grafeo` file stays at its path in the new format; the original is kept, unchanged, as `graph.grafeo.pre-0.6` (with a WAL that still held changes as `graph.grafeo.pre-0.6.wal`);
   - a WAL directory (0.5.x made one for a path without the `.grafeo` extension, such as `graph.db`) becomes a single file at the same path, and the directory is kept as `graph.db.pre-0.6/`. grafeo 0.5.x reopened such a database without its vector, text and property indexes; create them again with `create_vector_index` and `create_text_index`.
5. Check the data (`graph_info`), then delete the `.pre-0.6` copy when you no longer need a way back.

After the migration grafeo 0.5.x can no longer open the database. To go back, restore the `.pre-0.6` copy and run grafeo-mcp 0.2 with grafeo 0.5 pinned: grafeo-mcp 0.2 alone installs grafeo 0.6, which would migrate the copy again.

```bash
uvx --from grafeo-mcp==0.2.0 --with "grafeo<0.6" grafeo-mcp
```

A read-only server reads a 0.5.x database without migrating it. grafeo 0.7 will not read 0.5.x databases, so open each one read-write with grafeo 0.6 before moving on.

### What else changed with grafeo 0.6

- **Exact decimals.** In GQL a number with a point (`1.5`, `0.1`) is an exact decimal: `0.1 + 0.2` is `0.3`, and `1.50` keeps its two digits. Tools return decimals as JSON numbers with their exact digits. Write `1.5e0` or `toFloat(x)` for a float.
- **Numeric errors.** Integer or decimal overflow and division by zero fail the query instead of returning null.
- **Sorting.** GQL `ORDER BY` puts nulls last, ascending and descending (`NULLS FIRST` changes it).
- **Writes and filters.** A `WHERE` or `FILTER` right after `INSERT`, `CREATE`, `MERGE` or `DELETE` is an error: filter before the write, or with `WITH ... WHERE` after it.
- **Limits.** A statement may nest 64 levels deep and a property value 128 levels.
- **Engine messages.** Error messages from grafeo start with its error code (`GRAFEO-V001: ...`) and some are worded differently; tools pass them on unchanged after `Error: <tool>:`.
- **`dijkstra` weights.** `dijkstra` reads exact decimal weights; a non-number, NaN, infinite or negative weight is an error.

## Tools

### Query

| Tool          | Description                                           |
| ------------- | ----------------------------------------------------- |
| `execute_gql` | Run one GQL query, with parameters and write counters |

### Time travel

Both tools read the committed state at `as_of`: seconds ago (`"300"`) or an ISO-8601 datetime with its offset (`"2026-11-09T10:00:00+00:00"`). They need history, so start the server with `GRAFEO_HISTORY_RETENTION=forever` (or a number of seconds). Both work in read-only mode.

| Tool             | Description                                                |
| ---------------- | ---------------------------------------------------------- |
| `query_as_of`    | Run one read-only GQL query as the database was at `as_of` |
| `get_node_as_of` | A node's labels and properties as they were at `as_of`     |

### Graph CRUD & Traversal

| Tool                    | Description                                           |
| ----------------------- | ----------------------------------------------------- |
| `create_node`           | Create a node with labels and properties              |
| `create_edge`           | Create a directed edge between two nodes              |
| `get_node`              | Retrieve a node by ID                                 |
| `update_node`           | Update properties on an existing node                 |
| `delete_node`           | Delete a node and its edges (detach defaults to true) |
| `update_edge`           | Update properties on an existing edge                 |
| `delete_edge`           | Delete an edge by ID                                  |
| `get_neighbors`         | Explore a node's neighborhood (1-hop)                 |
| `search_nodes_by_label` | Find nodes by label with pagination                   |
| `graph_info`            | Counts, labels, edge types, indexes                   |

### Batch Import

| Tool           | Description                                  |
| -------------- | -------------------------------------------- |
| `batch_import` | Bulk-create nodes and edges from JSON arrays |

### Full-Text Search

| Tool                | Description                                   |
| ------------------- | --------------------------------------------- |
| `create_text_index` | Create a full-text search index on a property |
| `search_text`       | Keyword search over indexed string properties |

### Vector Search

| Tool                  | Description                                                                   |
| --------------------- | ----------------------------------------------------------------------------- |
| `vector_search`       | k-NN similarity search (HNSW), from a query vector or a node (`like_node_id`) |
| `mmr_search`          | Diversity-aware search (Maximal Marginal Relevance)                           |
| `create_vector_index` | Create HNSW index on a label + property                                       |
| `vector_graph_search` | Hybrid: vector search + graph neighborhood expansion                          |

### Graph Algorithms

| Tool                     | Description                                                                                   |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `pagerank`               | Rank nodes by importance; `label` keeps one label                                             |
| `dijkstra`               | Shortest weighted path; ignores edge direction unless `direction` is `outgoing` or `incoming` |
| `louvain`                | Community detection (Louvain modularity)                                                      |
| `betweenness_centrality` | Find bridge/bottleneck nodes; `label` keeps one label                                         |
| `connected_components`   | Find disconnected subgraphs                                                                   |

## Resources

Clients list two resources and one resource template:

| URI                       | Kind     | Description                                            |
| ------------------------- | -------- | ------------------------------------------------------ |
| `graph://schema`          | resource | Labels with sample values, edge type patterns, indexes |
| `graph://stats`           | resource | Counts, memory and disk sizes, configuration           |
| `graph://nodes/{node_id}` | template | One node's details and a summary of its connections    |

## Prompts

| Prompt                 | Description                                       |
| ---------------------- | ------------------------------------------------- |
| `explore_graph`        | Guided exploration of the graph structure         |
| `knowledge_extraction` | Extract entities and relationships from text      |
| `graph_analysis`       | Structural analysis: communities, PageRank, hubs  |
| `similarity_search`    | Vector-powered semantic search with graph context |

## Which tool when?

| I want to...                         | Use this tool                           | Not this                          |
| ------------------------------------ | --------------------------------------- | --------------------------------- |
| Add a single node                    | `create_node`                           | `execute_gql`, `batch_import`     |
| Add a single edge                    | `create_edge`                           | `execute_gql`                     |
| Load many nodes and edges at once    | `batch_import`                          | `create_node` in a loop           |
| Look up a node by ID                 | `get_node`                              | `execute_gql`                     |
| Create or update a node by a key     | `execute_gql` with `MERGE` and `params` | `create_node`                     |
| Update a node's properties           | `update_node`                           | `execute_gql`                     |
| Delete a node                        | `delete_node`                           | `execute_gql`                     |
| Update an edge's properties          | `update_edge`                           | `execute_gql`                     |
| Delete an edge                       | `delete_edge`                           | `execute_gql`                     |
| Browse nodes of a type               | `search_nodes_by_label`                 | `execute_gql`                     |
| Explore one hop from a node          | `get_neighbors`                         | `execute_gql`                     |
| Run a complex or multi-hop query     | `execute_gql`                           | multiple `get_neighbors`          |
| See what the graph held earlier      | `query_as_of`                           | `execute_gql`                     |
| Read a node as it was earlier        | `get_node_as_of`                        | `get_node`                        |
| Search by keyword in text            | `search_text`                           | `execute_gql`                     |
| Find similar nodes by embedding      | `vector_search`                         | `execute_gql`                     |
| Find nodes like one you already have | `vector_search` with `like_node_id`     | `execute_gql`                     |
| Find similar nodes + graph context   | `vector_graph_search`                   | `vector_search` + `get_neighbors` |
| Find the most important nodes        | `pagerank`                              | `execute_gql`                     |
| Find shortest path between two nodes | `dijkstra`                              | `execute_gql`                     |
| Detect communities                   | `louvain`                               | `execute_gql`                     |
| Understand the graph before querying | `graph_info`                            | `search_nodes_by_label`           |

## Batch reference syntax

The `batch_import` tool lets edges reference nodes created in the same batch using `@N` notation, where `N` is the zero-based index into the `nodes` array:

```python
batch_import(
    nodes=[
        {"labels": ["Person"], "properties": {"name": "Dinesh Chugtai"}},  # @0
        {"labels": ["Person"], "properties": {"name": "Bertram Gilfoyle"}},  # @1
    ],
    edges=[
        {"source_ref": "@0", "target_ref": "@1", "edge_type": "RIVAL_OF"},
        {"source_ref": "@1", "target_ref": "@0", "edge_type": "RIVAL_OF"},  # the rivalry runs both ways
    ],
)
```

You can also mix batch references with existing node IDs: `{"source_ref": "@0", "target_ref": 42, ...}`.

A batch is all or nothing: it is checked completely before anything is written (labels, edge types, `@N` references, and that referenced node IDs exist), and if the engine rejects a node or edge partway (for example a `UNIQUE` constraint), everything the call created is removed again.

## Queries

`execute_gql` passes the query text to grafeo's GQL engine unchanged. The engine also accepts common Cypher syntax such as `CREATE`, `MERGE`, `OPTIONAL MATCH` and `DETACH DELETE`, so agents trained on Cypher work out of the box.

- **One statement per call.** Text with several statements separated by `;` is refused before it runs (a trailing `;` is fine). Chain clauses instead (`INSERT ... INSERT ...`, `MATCH ... INSERT ...`) or send separate calls.
- **Parameters.** Pass values in `params` and reference them as `$name`, e.g. query `MERGE (p:Person {name: $name}) SET p += $props RETURN id(p)` with `params={"name": "Jared Dunn", "props": {"born_as": "Donald Dunn"}}`. A parameter the query uses but `params` lacks is reported by name.
- **Write counters.** Results of writing queries include `counters` (nodes, edges, properties and labels created, deleted, set or removed), and engine warnings come back as `warnings`.
- **Path patterns in WHERE.** GQL tests a path with `EXISTS`: `WHERE p.age > 30 AND EXISTS { (p)-[:WORKS_AT]->(:Company) }`, or the pattern goes into `MATCH`. The Cypher form `WHERE (p)-[:WORKS_AT]->(...)` is a syntax error, and its hint says so.
- **Deleting edges.** `DELETE` takes variables: `MATCH (b)-[w:WORKS_AT]->(c) DELETE w`. A pattern after `DELETE` is a syntax error whose hint shows this form.
- **Names that do not exist.** A reading query that finds no rows, or returns a column that is null in every row, gets a `hint` naming the labels, edge types or properties it uses that are not in the graph, with the closest existing name: `Not in the graph: label :Persn (did you mean :Person?).` A query whose names all exist gets no hint, and a query that works costs no extra lookup.
- **Embeddings.** Store vectors through a parameter (`INSERT (:Doc {emb: $emb})`) or `vector([...])`: grafeo stores a plain list literal as a list, which vector indexes skip. `create_node`, `batch_import` and `update_node` store lists of floats as vectors.
- **Numbers.** A number with a point is an exact decimal and comes back as a JSON number with its digits (`1.50`); write `1.5e0` for a float. Overflow and division by zero fail the query, and `ORDER BY` puts nulls last. See [What else changed with grafeo 0.6](#what-else-changed-with-grafeo-06).

## Schema overview

`graph_info` is the first call of a session, so it is kept small:

```json
{"nodes": 5, "edges": 5,
 "labels": [{"name": "Person", "count": 3, "properties": {"age": "INT64", "name": "STRING"}}],
 "edge_types": [{"name": "WORKS_AT", "count": 3, "properties": {"since": "INT64"}, "endpoints": ["Person->Company"]}],
 "indexes": {"vector": [{"label": "Doc", "property": "emb", "items": 2}], "text": [], "property": []},
 "database": {"path": "graph.grafeo", "read_only": false},
 "engine": "grafeo 0.6.3"}
```

A property seen with several types lists them as `"INT64|STRING"`. The `graph://schema` resource adds sample values, and `graph://stats` memory and disk sizes.

## Errors

Every tool returns a string. A failure is a single message of the form `Error: <tool>: <what went wrong>. Hint: <what to try next>`, with the engine's own message included unchanged; over MCP it is returned with `isError: true`. Arguments of the wrong type and unknown tool names get the same form. The hint is left out where the message already says the fix, as in `Error: execute_gql: limit must be at least 1, got -1.`; for a failed query it depends on the engine's code: syntax (`GRAFEO-Q001`), names and types (`GRAFEO-Q002`) or a value at run time (`GRAFEO-Q006`, such as division by zero). Successful results are JSON, except the confirmation sentences of `delete_node`, `delete_edge`, `create_vector_index` and `create_text_index`.

## Output size

Results that would exceed about 8,000 characters are cut down to valid JSON: entries are dropped from the end of the largest lists, long strings end with `... [N chars]`, and the result gets `truncated: true`, an `omitted` map (path to number of entries dropped) and a `note`. A tool that normally returns a JSON array (`vector_search`, `mmr_search`, `search_text`) then returns `{"results": [...], "truncated": true, ...}`. Embeddings (lists of more than 32 numbers) show as `<vector: 384 dims>` wherever a node or edge appears; a query that returns the property itself (`RETURN n.embedding`) gets the numbers. `execute_gql` is bounded by its `limit` instead.

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

- **[grafeo-memory](https://github.com/GrafeoDB/grafeo-memory)** includes a built-in MCP server (`grafeo-memory-mcp`) that wraps the high-level memory API: extract, reconcile, search, summarize. If you need AI memory management rather than raw graph access, use `uv add "grafeo-memory[mcp]"`.

## License

Apache-2.0
