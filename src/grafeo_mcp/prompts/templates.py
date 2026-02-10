from __future__ import annotations

from grafeo_mcp.server import mcp


@mcp.prompt()
def explore_graph(focus_label: str = "") -> str:
    """Guide an AI agent through structured exploration of the knowledge graph.

    The agent will systematically discover the graph's schema, sample nodes,
    traverse relationships, and summarize patterns.
    """
    steps = (
        "You are exploring a GrafeoDB knowledge graph via MCP tools. Follow these "
        "steps in order, reporting what you find at each stage.\n"
        "\n"
        "## Step 1 — Understand the schema\n"
        "Call `graph_info` (no arguments). Inspect the response to learn:\n"
        "- Total node and edge counts\n"
        "- Available node labels (e.g. Person, Company, Document)\n"
        "- Relationship types (e.g. KNOWS, WORKS_AT)\n"
        "- Any vector indexes that exist\n"
        "Summarize the schema in a few sentences before continuing.\n"
        "\n"
        "## Step 2 — Sample nodes by label\n"
        "Pick 2-3 interesting labels from the schema and call "
        "`search_nodes_by_label` for each one.\n"
        "Example:\n"
        '  search_nodes_by_label(label="Person", limit=10)\n'
        '  search_nodes_by_label(label="Company", limit=10)\n'
        "Review the returned properties to understand what data each label carries.\n"
        "\n"
        "## Step 3 — Traverse relationships\n"
        "Pick a few interesting node IDs from Step 2 and explore their neighborhoods "
        "using `get_neighbors` — the primary graph traversal tool:\n"
        "  get_neighbors(node_id=<NODE_ID>)\n"
        '  get_neighbors(node_id=<NODE_ID>, direction="outgoing")\n'
        '  get_neighbors(node_id=<NODE_ID>, edge_type="KNOWS", limit=10)\n'
        "This reveals what each node connects to and through which relationships.\n"
        "\n"
        "## Step 4 — Run targeted pattern queries\n"
        "Based on what you learned, write 1-2 queries to explore specific "
        "patterns using `execute_gql`:\n"
        '  execute_gql(query="MATCH (a:Person)-[:KNOWS]->(b:Person) '
        'RETURN a.name, b.name LIMIT 20")\n'
        '  execute_gql(query="MATCH (p:Person)-[:WORKS_AT]->(c:Company) '
        'RETURN p.name, c.name LIMIT 20")\n'
        "Adapt these to the actual labels and relationship types in the graph.\n"
        "\n"
        "## Step 5 — Synthesize findings\n"
        "Produce a structured summary including:\n"
        "- Graph size and shape (nodes, edges, density)\n"
        "- Key entity types and their typical properties\n"
        "- Most common relationship patterns\n"
        "- Any notable clusters, hubs, or anomalies you noticed\n"
        "- Suggestions for further exploration or analysis"
    )
    if focus_label:
        return (
            f"{steps}\n\n"
            f"**Focus:** Prioritize your exploration on nodes with the label "
            f"`{focus_label}`. Start Step 2 by calling "
            f'`search_nodes_by_label(label="{focus_label}")` and use those nodes '
            f"as the starting points for traversal in Step 3."
        )
    return steps


@mcp.prompt()
def knowledge_extraction(text: str) -> str:
    """Guide an AI agent through extracting entities and relationships from text into the graph.

    The agent will analyze the text, create nodes for entities, create edges for
    relationships, and verify the resulting graph structure.
    """
    return (
        "You are building a knowledge graph from the text below. Follow these "
        "steps in order, tracking the node IDs you create.\n"
        "\n"
        "## Step 1 — Analyze the text\n"
        "Read the text carefully. Identify:\n"
        "- **Entities:** People, organizations, locations, products, concepts, "
        "events, dates, etc.\n"
        "- **Relationships:** How entities relate (e.g. WORKS_AT, FOUNDED, "
        "LOCATED_IN, KNOWS, PART_OF, OCCURRED_ON).\n"
        "List your extracted entities and relationships in a table before creating "
        "anything. Use specific, descriptive labels (e.g. `Person`, `Company`, "
        "`City`) rather than generic ones.\n"
        "\n"
        "## Step 2 — Create entity nodes\n"
        "For each entity, call `create_node` with appropriate labels and properties.\n"
        "Example:\n"
        '  create_node(labels=["Person"], properties={"name": "Alice Chen", '
        '"role": "CEO"})\n'
        '  create_node(labels=["Company"], properties={"name": "Acme Corp", '
        '"industry": "Technology"})\n'
        "Record every returned node ID — you will need them for edges. When the "
        "same entity appears multiple times in the text, create it only once.\n"
        "\n"
        "## Step 3 — Create relationship edges\n"
        "For each relationship you identified, call `create_edge` using the node "
        "IDs from Step 2.\n"
        "Example:\n"
        '  create_edge(source_id=0, target_id=1, edge_type="FOUNDED", '
        'properties={"year": 2019})\n'
        '  create_edge(source_id=0, target_id=2, edge_type="LIVES_IN")\n'
        "Use descriptive UPPER_SNAKE_CASE edge types. Add properties to edges "
        "when the text provides qualifying details (dates, roles, amounts).\n"
        "\n"
        "## Step 4 — Verify the graph\n"
        "Call `graph_info` to confirm the expected number of nodes and edges were "
        "created. Compare against your entity/relationship table from Step 1.\n"
        "\n"
        "## Step 5 — Verify connectivity\n"
        "Pick 2-3 key entities and call `get_neighbors` to verify their connections:\n"
        "  get_neighbors(node_id=<NODE_ID>)\n"
        "Confirm that the relationships match what you extracted from the text. "
        "If anything is missing, create the missing edges.\n"
        "\n"
        "## Step 6 — Summary\n"
        "Report what was created:\n"
        "- Total nodes and edges created\n"
        "- A brief description of the graph structure\n"
        "- Any ambiguities or entities you chose to skip, and why\n"
        "\n"
        "---\n"
        f"**Text to extract from:**\n\n{text}"
    )


@mcp.prompt()
def graph_analysis(top_k: int = 10) -> str:
    """Guide an AI agent through analytical exploration of the graph structure.

    The agent will run community detection, PageRank, and neighborhood traversals
    to produce a narrative about the graph's structure and important entities.
    """
    return (
        "You are performing structural analysis on a GrafeoDB knowledge graph. "
        "Follow these steps in order, building toward a comprehensive narrative.\n"
        "\n"
        "## Step 1 — Get the graph overview\n"
        "Call `graph_info` to understand the graph's size and schema. Report:\n"
        "- Total nodes and edges\n"
        "- Available labels and relationship types\n"
        "- Whether the graph is large enough for meaningful analysis\n"
        "If the graph has fewer than 3 nodes, stop and report that the graph is "
        "too small for structural analysis.\n"
        "\n"
        "## Step 2 — Detect communities\n"
        "Call `louvain` to find clusters using the Louvain modularity algorithm.\n"
        "Analyze the results:\n"
        "- How many communities were found?\n"
        "- What is the modularity score (higher = more distinct communities)?\n"
        "- What are the sizes of each community?\n"
        "- For each community, call `get_node` on a sample of node IDs to "
        "understand what kinds of entities are grouped together.\n"
        "Name each community based on the dominant entity types or themes you "
        "discover (e.g. 'Engineering Team', 'West Coast Offices').\n"
        "\n"
        "## Step 3 — Identify important nodes with PageRank\n"
        f"Call `pagerank(top_k={top_k})` to find the most influential nodes.\n"
        "For each top-ranked node:\n"
        "- Note its labels, properties, and PageRank score\n"
        "- Which community does it belong to (cross-reference with Step 2)?\n"
        "- Explain in plain language why this node might be important\n"
        "\n"
        "## Step 4 — Explore hub neighborhoods\n"
        "For the top 3 nodes from PageRank, explore their neighborhoods using "
        "`get_neighbors`:\n"
        "  get_neighbors(node_id=<NODE_ID>, limit=25)\n"
        "Identify:\n"
        "- How many connections each hub has\n"
        "- What types of nodes they connect to\n"
        "- Whether they bridge between different communities\n"
        "\n"
        "## Step 5 — Synthesize a narrative\n"
        "Combine your findings into a structured report:\n"
        "1. **Overview** — graph size, density, basic shape\n"
        "2. **Communities** — what groups exist and what defines them\n"
        "3. **Key entities** — who/what are the most important nodes and why\n"
        "4. **Structural insights** — are there bridge nodes connecting "
        "communities? Are some communities isolated? Is the graph dense or sparse?\n"
        "5. **Recommendations** — suggest follow-up queries or analyses "
        "(e.g. `dijkstra` between two hubs, `betweenness_centrality` to find "
        "bridge nodes, deeper exploration of a specific community)"
    )


@mcp.prompt()
def similarity_search(
    label: str = "",
    property: str = "embedding",
    description: str = "",
) -> str:
    """Guide an AI agent through vector-powered semantic search on the graph.

    The agent will perform similarity search, explore neighborhoods of results,
    and synthesize findings.
    """
    label_instruction = (
        f"Use the label `{label}` and property `{property}` for your searches."
        if label
        else (
            "First, call `graph_info` to discover which labels have vector indexes. "
            "Look for vector index information in the response to determine the correct "
            "`label` and `property` parameters for `vector_search`."
        )
    )

    query_instruction = (
        f"The user is looking for: **{description}**\n"
        "Generate an embedding for this description using your available embedding "
        "tools or API, then use it as the query vector."
        if description
        else (
            "Ask the user what they are searching for, or if they can provide an "
            "embedding vector directly. You need a query vector (list of floats) to "
            "perform the search."
        )
    )

    return (
        "You are performing semantic similarity search on a GrafeoDB knowledge "
        "graph that contains vector embeddings. Follow these steps.\n"
        "\n"
        "## Step 1 — Identify the vector index\n"
        f"{label_instruction}\n"
        "If no vector indexes exist, inform the user that they need to create one "
        "first using `create_vector_index` and populate nodes with embedding vectors "
        "before similarity search is possible.\n"
        "\n"
        "## Step 2 — Obtain a query vector\n"
        f"{query_instruction}\n"
        "The query vector must match the dimensionality of the index (e.g. 1536 for "
        "OpenAI text-embedding-3-small, 384 for MiniLM).\n"
        "\n"
        "## Step 3 — Run the similarity search\n"
        "Call `vector_search` with the query vector:\n"
        f'  vector_search(label="{label or "<LABEL>"}", '
        f'property="{property}", query_vector=[...], k=10)\n'
        "Review the results. Each result includes:\n"
        "- `node_id` — the matching node\n"
        "- `distance` — cosine distance (lower = more similar)\n"
        "- `similarity` — 1 - distance (higher = more similar)\n"
        "- `properties` — the node's stored properties\n"
        "\n"
        "Alternatively, use `vector_graph_search` to combine vector search with "
        "automatic neighborhood expansion — this returns similar nodes AND their "
        "graph context in a single call.\n"
        "\n"
        "## Step 4 — Explore context around results\n"
        "For the top 3-5 most similar results, explore their graph neighborhood "
        "using `get_neighbors`:\n"
        "  get_neighbors(node_id=<NODE_ID>)\n"
        "This reveals how each semantically similar node fits into the broader "
        "graph structure.\n"
        "\n"
        "## Step 5 — Compare and summarize\n"
        "Produce a summary that includes:\n"
        "- **Top matches** — list the most similar nodes with their similarity "
        "scores and key properties\n"
        "- **Themes** — what do the top results have in common?\n"
        "- **Graph context** — how are the results connected to each other and "
        "to the rest of the graph?\n"
        "- **Recommendations** — suggest related queries or nodes worth "
        "exploring further"
    )
