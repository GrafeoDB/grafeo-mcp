from __future__ import annotations

import grafeo
from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession

from grafeo_mcp.resources._helpers import _format_value
from grafeo_mcp.server import AppContext, AppContextView, current_app, mcp
from grafeo_mcp.tools._helpers import index_overview

SAMPLE_LIMIT = 3

_EDGE_PATTERN_QUERY = "MATCH (a)-[r]->(b) WHERE type(r) = $edge_type RETURN labels(a) AS src, labels(b) AS dst LIMIT 5"


def _build_label_details(db: grafeo.GrafeoDB, schema: dict) -> str:
    """Build the node labels section with property keys and sample values."""
    labels = schema.get("labels", [])
    if not labels:
        return "  (none)\n"

    lines: list[str] = []
    for label_info in labels:
        name = label_info["name"]
        count = label_info["count"]
        lines.append(f"  :{name} ({count} nodes)")

        # Sample a few nodes to discover property keys and example values
        samples = db.get_nodes_by_label(name, limit=SAMPLE_LIMIT)

        if not samples:
            lines.append("    (no properties found)")
            continue

        # Collect property keys across samples with example values
        prop_examples: dict[str, object] = {}
        for _nid, props in samples:
            for key, val in props.items():
                if key not in prop_examples:
                    prop_examples[key] = val

        if prop_examples:
            for key, val in sorted(prop_examples.items()):
                lines.append(f"    .{key}: {_format_value(val, str_limit=60, list_limit=5, list_preview=5)}")
        else:
            lines.append("    (no properties found)")

    return "\n".join(lines) + "\n"


def _build_edge_details(db: grafeo.GrafeoDB, schema: dict) -> str:
    """Build the edge types section with source->target label patterns."""
    edge_types = schema.get("edge_types", [])
    if not edge_types:
        return "  (none)\n"

    lines: list[str] = []
    for et in edge_types:
        name = et["name"]
        count = et["count"]

        # Sample a few edges of this type to discover source->target label
        # patterns. Rows are dicts keyed by column alias, and the edge type is
        # passed as a parameter, never pasted into the query text.
        patterns: list[str] = []
        seen: set[str] = set()
        for row in db.execute(_EDGE_PATTERN_QUERY, {"edge_type": name}):
            src_str = ":".join(str(lb) for lb in row["src"]) if row["src"] else "?"
            tgt_str = ":".join(str(lb) for lb in row["dst"]) if row["dst"] else "?"
            pattern = f"(:{src_str})-[:{name}]->(:{tgt_str})"
            if pattern not in seen:
                seen.add(pattern)
                patterns.append(pattern)

        lines.append(f"  :{name} ({count} edges)")
        if patterns:
            for p in patterns:
                lines.append(f"    {p}")
        else:
            lines.append(f"    (?)-[:{name}]->(?)")

    return "\n".join(lines) + "\n"


def _build_index_details(db: grafeo.GrafeoDB, schema: dict) -> str:
    """Build the property, vector and text index sections."""
    overview = index_overview(db, list(schema.get("property_keys", [])))
    lines: list[str] = ["Property indexes:"]
    lines.extend(f"  .{key}" for key in overview["property"])
    if not overview["property"]:
        lines.append("  (none)")

    for title, kind, tool in (("Vector", "vector", "create_vector_index"), ("Text", "text", "create_text_index")):
        lines.append("")
        lines.append(f"{title} indexes:")
        entries = overview[kind]
        lines.extend(f"  :{entry['label']}.{entry['property']} ({entry['items']} indexed)" for entry in entries)
        if not entries:
            lines.append(f"  (none: create one with {tool})")

    return "\n".join(lines) + "\n"


def graph_schema(ctx: Context[AppContext, ServerSession] | AppContextView) -> str:
    """Rich schema overview of the graph: node labels with properties, edge type patterns,
    indexes, and counts. Designed for AI agents to understand the graph structure before
    querying."""
    db = ctx.request_context.lifespan_context.db
    schema = db.schema()
    detailed = db.detailed_stats()

    parts: list[str] = []

    # Header with counts
    parts.append("=== Graph Schema ===")
    parts.append("")
    parts.append(
        f"Totals: {detailed['node_count']} nodes, {detailed['edge_count']} edges, "
        f"{detailed['label_count']} labels, {detailed['edge_type_count']} edge types"
    )

    # Node labels with property keys and samples
    parts.append("")
    parts.append("--- Node Labels ---")
    parts.append(_build_label_details(db, schema))

    # Edge types with source->target patterns
    parts.append("--- Edge Types ---")
    parts.append(_build_edge_details(db, schema))

    # Indexes
    parts.append("--- Indexes ---")
    parts.append(_build_index_details(db, schema))

    # Property keys summary
    property_keys = schema.get("property_keys", [])
    parts.append("--- All Property Keys ---")
    if property_keys:
        parts.append("  " + ", ".join(sorted(property_keys)))
    else:
        parts.append("  (none)")
    parts.append("")

    return "\n".join(parts)


def graph_stats(ctx: Context[AppContext, ServerSession] | AppContextView) -> str:
    """Performance-oriented database statistics: counts, indexes, storage size, and
    operational info. Use graph://schema for structural overview."""
    db = ctx.request_context.lifespan_context.db
    detailed = db.detailed_stats()
    info = db.info()

    parts: list[str] = []

    parts.append("=== Database Statistics ===")
    parts.append("")

    # Counts
    parts.append("Counts:")
    parts.append(f"  Nodes: {detailed['node_count']}")
    parts.append(f"  Edges: {detailed['edge_count']}")
    parts.append(f"  Labels: {detailed['label_count']}")
    parts.append(f"  Edge types: {detailed['edge_type_count']}")
    parts.append(f"  Property keys: {detailed['property_key_count']}")
    parts.append(f"  Indexes: {detailed['index_count']}")

    # Storage
    parts.append("")
    parts.append("Storage:")
    memory_bytes = detailed.get("memory_bytes") or 0
    disk_bytes = detailed.get("disk_bytes") or 0
    memory_mb = memory_bytes / (1024 * 1024)
    disk_mb = disk_bytes / (1024 * 1024)
    parts.append(f"  Memory: {memory_mb:.2f} MB ({memory_bytes} bytes)")
    parts.append(f"  Disk: {disk_mb:.2f} MB ({disk_bytes} bytes)")

    # Operational info
    parts.append("")
    parts.append("Configuration:")
    parts.append(f"  Mode: {info.get('mode', 'unknown')}")
    parts.append(f"  Persistent: {info.get('is_persistent', False)}")
    path = info.get("path")
    parts.append(f"  Path: {path if path else '(in-memory)'}")
    parts.append(f"  WAL enabled: {info.get('wal_enabled', False)}")
    parts.append(f"  Version: {info.get('version', 'unknown')}")
    parts.append("")

    return "\n".join(parts)


# FastMCP turns a resource function with any parameter (even only the context)
# mcp 2.x does not inject Context into static resources (no URI template
# variables), so they read the app context held by the lifespan instead.


@mcp.resource("graph://schema", name="graph_schema", description=graph_schema.__doc__, mime_type="text/plain")
def _graph_schema_resource() -> str:
    return graph_schema(current_app())


@mcp.resource("graph://stats", name="graph_stats", description=graph_stats.__doc__, mime_type="text/plain")
def _graph_stats_resource() -> str:
    return graph_stats(current_app())
