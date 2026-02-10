from __future__ import annotations

import grafeo
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from grafeo_mcp.server import AppContext, mcp

SAMPLE_LIMIT = 3


def _format_value(v: object) -> str:
    """Format a property value for display, truncating long strings."""
    if isinstance(v, str):
        if len(v) > 60:
            return f'"{v[:57]}..."'
        return f'"{v}"'
    if isinstance(v, list):
        if len(v) > 5:
            return f"[{', '.join(str(x) for x in v[:5])}, ...] ({len(v)} items)"
        return str(v)
    return str(v)


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
        try:
            samples = db.get_nodes_by_label(name, limit=SAMPLE_LIMIT)
        except Exception:
            samples = []

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
                lines.append(f"    .{key}: {_format_value(val)}")
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

        # Query a few edges of this type to discover source->target label patterns
        patterns: list[str] = []
        try:
            result = db.execute(f"MATCH (a)-[r:{name}]->(b) RETURN labels(a), labels(b) LIMIT 5")
            seen: set[str] = set()
            for row in result:
                src_labels = row[0] if row[0] else ["?"]
                tgt_labels = row[1] if row[1] else ["?"]
                src_str = ":".join(str(lb) for lb in src_labels)
                tgt_str = ":".join(str(lb) for lb in tgt_labels)
                pattern = f"(:{src_str})-[:{name}]->(:{tgt_str})"
                if pattern not in seen:
                    seen.add(pattern)
                    patterns.append(pattern)
        except Exception:
            pass

        lines.append(f"  :{name} ({count} edges)")
        if patterns:
            for p in patterns:
                lines.append(f"    {p}")
        else:
            lines.append(f"    (?)-[:{name}]->(?)")

    return "\n".join(lines) + "\n"


def _build_index_details(db: grafeo.GrafeoDB, schema: dict) -> str:
    """Build the property and vector index sections."""
    lines: list[str] = []

    # Property indexes: check each known property key
    property_keys = schema.get("property_keys", [])
    indexed: list[str] = []
    for key in property_keys:
        try:
            if db.has_property_index(key):
                indexed.append(key)
        except Exception:
            pass

    lines.append("Property indexes:")
    if indexed:
        for key in sorted(indexed):
            lines.append(f"  .{key} (btree)")
    else:
        lines.append("  (none)")

    # Vector indexes: query info if available
    lines.append("")
    lines.append("Vector indexes:")
    try:
        result = db.execute("MATCH (n) WHERE n.embedding IS NOT NULL RETURN labels(n), 'embedding' LIMIT 1")
        # If the query returns results, there might be vector data, but we can't
        # enumerate indexes directly. We'll note what we can find from schema.
        has_vector = False
        for _row in result:
            has_vector = True
            break
        if not has_vector:
            lines.append("  (none detected)")
    except Exception:
        lines.append("  (none detected)")

    return "\n".join(lines) + "\n"


@mcp.resource("graph://schema")
def graph_schema(ctx: Context[ServerSession, AppContext]) -> str:
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


@mcp.resource("graph://stats")
def graph_stats(ctx: Context[ServerSession, AppContext]) -> str:
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
