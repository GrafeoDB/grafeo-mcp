from __future__ import annotations

import difflib
import itertools
import re
from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.server.session import ServerSession
from pydantic import Field

from grafeo_mcp.server import AppContext
from grafeo_mcp.tools._gql import QueryScan, scan_query
from grafeo_mcp.tools._helpers import (
    _NO_HISTORY_HINT,
    _POINT_HINT,
    AsOf,
    check_range,
    compact_graph_values,
    describe_exception,
    grafeo_tool,
    parse_time_point,
    to_json,
    tool_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_RESULT_ROWS = 100  # default cap before truncation

_QUERY_HINT = "check the query syntax, and call graph_info to see the labels, edge types and property keys that exist."

_HINTS_BY_CODE = {
    # A statement that does not parse.
    "GRAFEO-Q001": _QUERY_HINT,
    # Parsed, but names or types do not fit (an undefined variable, a wrong-kind argument).
    "GRAFEO-Q002": "fix what the message points at; graph_info lists the labels, edge types and property keys.",
    # Valid, but a value broke it while running (division by zero, overflow, a string plus a number).
    "GRAFEO-Q006": "the query is valid but a value broke it while running: filter those rows out first, or guard "
    "the expression with CASE WHEN ... THEN ... ELSE ... END.",
}


_PATTERN_IN_WHERE_HINT = (
    "a path pattern in WHERE needs EXISTS: WHERE EXISTS { (p)-[:WORKS_AT]->(:Company) } "
    "(or WHERE NOT EXISTS { ... }), or move the pattern into MATCH: MATCH (p)-[:WORKS_AT]->(c:Company)."
)

_ERROR_POSITION = re.compile(r"--> query:(\d+):(\d+)")
_CLAUSE_WORD = re.compile(
    r"\b(OPTIONAL\s+MATCH|MATCH|WHERE|FILTER|RETURN|WITH|INSERT|CREATE|MERGE|SET|ORDER|UNWIND)\b", re.I
)
_EXISTS_OPEN = re.compile(r"\bEXISTS\s*\{[^}]*$", re.I)


def _error_offset(message: str, query: str) -> int | None:
    """The character offset in *query* that a syntax error points at (``--> query:LINE:COLUMN``)."""
    found = _ERROR_POSITION.search(message)
    if not found:
        return None
    line, column = int(found.group(1)), int(found.group(2))
    lines = query.split("\n")
    if not 1 <= line <= len(lines):
        return None
    return sum(len(text) + 1 for text in lines[: line - 1]) + column - 1


def _is_pattern_in_where(message: str, query: str) -> bool:
    """True when a syntax error sits on the edge of a path pattern written straight into WHERE.

    Cypher lets ``WHERE (p)-[:R]->(x)`` test for a path; GQL needs ``EXISTS { ... }``. The engine then
    reports "Expected ..." at the ``[``, ``-`` or ``<`` right after the node ``(p)``.
    """
    offset = _error_offset(message, query)
    if offset is None or not 0 < offset <= len(query):
        return False
    before, at = query[:offset], query[offset : offset + 1]
    # The caret sits on the edge right after the node: on "-", "<" or "[" after "(p)", or inside "(p)-[".
    on_edge = (bool(at) and at in "-<[" and re.search(r"\)\s*$", before)) or re.search(r"\)\s*<?-+>?\s*\[?\s*$", before)
    if not on_edge:
        return False
    clauses = _CLAUSE_WORD.findall(before)
    return bool(clauses) and clauses[-1].upper() in ("WHERE", "FILTER") and not _EXISTS_OPEN.search(before)


_PATTERN_IN_DELETE_HINT = (
    "DELETE takes variables, not patterns: bind the edge in MATCH, as in MATCH (b)-[w:WORKS_AT]->(c), "
    "then DELETE w (DETACH DELETE b removes a node with its edges)."
)

_DELETE_WORD = re.compile(r"\bDELETE\b", re.I)


def _is_pattern_in_delete(message: str, query: str) -> bool:
    """True when a syntax error sits on a path pattern written after DELETE (``DELETE (b)-[:R]->(c)``).

    The engine reports it at the edge (``[``, ``->``) after the first element, which DELETE took as its
    whole argument.
    """
    offset = _error_offset(message, query)
    if offset is None or not 0 < offset <= len(query):
        return False
    before = query[:offset]
    clauses = list(_CLAUSE_WORD.finditer(before))
    deletes = list(_DELETE_WORD.finditer(before))
    if not deletes or (clauses and clauses[-1].start() > deletes[-1].start()):
        return False  # the error is not inside the DELETE clause
    argument = query[deletes[-1].end() : offset + 2]
    return bool(re.search(r"[-\[<>]", argument))


def _query_hint(exc: BaseException, query: str = "") -> str:
    """The hint for a failed query, by the engine's error code and, for syntax, where it points."""
    message = str(exc)
    code = message.split(":", 1)[0].strip()
    if code == "GRAFEO-Q001" and query:
        if _is_pattern_in_where(message, query):
            return _PATTERN_IN_WHERE_HINT
        if _is_pattern_in_delete(message, query):
            return _PATTERN_IN_DELETE_HINT
    return _HINTS_BY_CODE.get(code, _QUERY_HINT)


def _results_payload(result: Any, *, limit: int, include_counters: bool = False) -> dict[str, Any]:
    """Convert a QueryResult into a JSON-ready dict, keeping at most *limit* rows.

    Holds ``columns``, ``rows`` and ``total_rows``, a ``truncated`` flag and
    ``note`` when rows were left out, ``counters`` when the query wrote
    anything (or *include_counters* is set), the engine's ``warnings`` when
    there are any and ``execution_time_ms`` when the engine reports it.
    """
    total = len(result)
    # Embeddings inside node and edge maps become placeholders; RETURN n.embedding still returns the vector.
    rows = compact_graph_values(list(itertools.islice(iter(result), limit)))

    payload: dict[str, Any] = {
        "columns": list(result.columns),
        "rows": rows,
        "total_rows": total,
    }

    if total > limit:
        payload["truncated"] = True
        payload["note"] = f"Showing first {limit} of {total} results. Use LIMIT in your query for more control."

    counters = dict(getattr(result, "counters", None) or {})
    if include_counters or any(counters.values()):
        payload["counters"] = counters

    warnings = [f"{w.code}: {w.message}" for w in getattr(result, "warnings", None) or []]
    if warnings:
        payload["warnings"] = warnings

    if result.execution_time_ms is not None:
        payload["execution_time_ms"] = round(result.execution_time_ms, 2)

    return payload


def _format_results(result: Any, *, limit: int, include_counters: bool = False) -> str:
    return to_json(_results_payload(result, limit=limit, include_counters=include_counters))


_LIST_NAMES_UP_TO = 8  # a missing name without a close match lists the existing ones up to this many


def _missing(kind: str, name: str, existing: set[str], prefix: str) -> str:
    """``label :Persn (did you mean :Person?)``, or the existing names when there are few."""
    by_case = [e for e in existing if e.lower() == name.lower()]
    close = by_case or difflib.get_close_matches(name, existing, n=1, cutoff=0.6)
    if close:
        return f"{kind} {prefix}{name} (did you mean {prefix}{close[0]}?)"
    if existing and len(existing) <= _LIST_NAMES_UP_TO:
        return f"{kind} {prefix}{name} (there are: {', '.join(prefix + e for e in sorted(existing))})"
    return f"{kind} {prefix}{name}"


def _names_hint(db: Any, scan: QueryScan, rows: list[dict[str, Any]], total: int) -> str | None:
    """Say which names of a reading query do not exist, when it found nothing or only nulls.

    Runs only for an empty result, or one where some column is null in every
    returned row (``RETURN n.nmae``), so a query that works costs nothing extra.
    """
    null_column = bool(rows) and any(all(row.get(col) is None for row in rows) for col in rows[0])
    if total and not null_column:
        return None
    if total == 0 and db.node_count == 0:
        return "The graph has no nodes yet."
    schema = db.schema()
    labels = {entry["name"] for entry in schema.get("labels", [])}
    types = {entry["name"] for entry in schema.get("edge_types", [])}
    keys = set(schema.get("property_keys", []))

    problems: list[str] = []
    if total == 0:
        problems += [_missing("label", name, labels, ":") for name in sorted(scan.labels - labels)]
        problems += [_missing("edge type", name, types, ":") for name in sorted(scan.edge_types - types)]
        either = labels | types
        problems += [_missing("label", name, either, ":") for name in sorted(scan.label_or_type - either)]
    problems += [_missing("property", name, keys, "") for name in sorted(scan.property_keys - keys)]
    if not problems:
        return None
    return "Not in the graph: " + "; ".join(problems) + "."


def _run_read_only(db: Any, query: str, params: dict[str, Any] | None) -> tuple[Any, bool]:
    """Run *query* in a transaction that is always rolled back.

    Returns the result and whether the query wrote anything (by its counters).
    This backs up the keyword check in read-only mode: whatever the query
    changes in the graph is undone.
    """
    tx = db.begin_transaction()
    try:
        result = tx.execute(query, params)
    finally:
        tx.rollback()
    wrote = any((getattr(result, "counters", None) or {}).values())
    return result, wrote


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@grafeo_tool(read_only=False, destructive=True)
def execute_gql(
    query: Annotated[str, Field(description="One GQL statement.")],
    limit: Annotated[int, Field(description="Most rows to return; LIMIT in the query also works.")] = _MAX_RESULT_ROWS,
    params: Annotated[
        dict[str, Any] | None, Field(description='Values for $name in the query: {"name": "Ada"}.')
    ] = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Run one GQL statement: multi-hop patterns, filters, aggregations, MERGE upserts, label changes.

    Cypher syntax (CREATE, MERGE, OPTIONAL MATCH, DETACH DELETE) runs as written. Rules:
    - One statement per call; chain clauses instead (MATCH ... INSERT ...).
    - Put values in params as $name, not in the text. Embeddings too: a list literal is stored as a list,
      which vector indexes skip.
    - 1.5 is an exact decimal (0.1 + 0.2 = 0.3); 1.5e0 is a float. Overflow and division by zero fail.
    - No WHERE right after INSERT, CREATE, MERGE or DELETE: filter before the write, or WITH ... WHERE after it.
    - A path pattern in WHERE needs EXISTS: WHERE EXISTS { (p)-[:WORKS_AT]->(:Company) }, not WHERE (p)-->(..).
    - DELETE takes variables: MATCH (b)-[w:WORKS_AT]->(c) DELETE w, not DELETE (b)-[:WORKS_AT]->(c).
    - ORDER BY puts nulls last.

    Returns {columns, rows, total_rows}; a node in a row is a map with _id, _labels and its properties, an edge
    has _id, _type, _source, _target. Writes add counters. A read that finds nothing, or only nulls, gets a hint
    naming the labels, edge types or properties that do not exist.

    Example: MERGE (p:Person {name: $name}) SET p += $props RETURN id(p) AS id
    with params={"name": "Ada", "props": {"born": 1815}}
    """
    assert ctx is not None
    if err := check_range("execute_gql", limit=(limit, 1)):
        return err

    scan = scan_query(query)
    if scan.statements == 0:
        return tool_error(
            "execute_gql", "the query is empty", "send one GQL statement, e.g. MATCH (n) RETURN n LIMIT 10."
        )
    if scan.statements > 1:
        return tool_error(
            "execute_gql",
            f"the query holds {scan.statements} statements separated by ';', but execute_gql runs one per call",
            "send each statement in its own execute_gql call, or chain the clauses in one statement "
            "(INSERT ... INSERT ..., MATCH ... INSERT ...).",
        )
    missing = sorted(scan.parameters - set(params or {}))
    if missing:
        names = ", ".join(f"${name}" for name in missing)
        return tool_error(
            "execute_gql",
            f"the query uses {names}, but params does not supply {'it' if len(missing) == 1 else 'them'}",
            'pass every parameter in params, e.g. params={"' + missing[0] + '": ...}.',
        )

    app = ctx.request_context.lifespan_context
    if app.read_only and scan.writes:
        return tool_error(
            "execute_gql",
            "the server is in read-only mode (GRAFEO_READ_ONLY=1) and the query contains "
            + ", ".join(scan.write_keywords),
            "only reading queries (MATCH ... RETURN, SHOW, CALL of read-only procedures) run in read-only mode.",
        )

    try:
        if app.read_only:
            result, wrote = _run_read_only(app.db, query, params)
            if wrote:
                return tool_error(
                    "execute_gql",
                    "the server is in read-only mode (GRAFEO_READ_ONLY=1) and the query tried to write; "
                    "its changes were rolled back",
                    "only reading queries run in read-only mode.",
                )
        else:
            result = app.db.execute(query, params)
        payload = _results_payload(result, limit=limit, include_counters=scan.writes)
        if not scan.writes and (hint := _names_hint(app.db, scan, payload["rows"], payload["total_rows"])):
            payload["hint"] = hint
        return to_json(payload)
    except Exception as exc:
        return tool_error("execute_gql", f"query failed: {describe_exception(exc)}", _query_hint(exc, query))


@grafeo_tool(read_only=True)
def query_as_of(
    query: Annotated[str, Field(description="One reading GQL statement.")],
    as_of: AsOf,
    limit: Annotated[int, Field(description="Most rows to return.")] = _MAX_RESULT_ROWS,
    params: Annotated[dict[str, Any] | None, Field(description="Values for $name in the query.")] = None,
    ctx: Context[AppContext, ServerSession] | None = None,
) -> str:
    """Run one reading GQL statement against the graph as it was at as_of (time travel).

    Needs a server that keeps history (GRAFEO_HISTORY_RETENTION). Same rules and result as execute_gql.
    Example: query_as_of("MATCH (p:Person) RETURN p.name, p.age", "3600")
    """
    assert ctx is not None
    if err := check_range("query_as_of", limit=(limit, 1)):
        return err

    scan = scan_query(query)
    if scan.statements == 0:
        return tool_error(
            "query_as_of", "the query is empty", "send one GQL statement, e.g. MATCH (n) RETURN n LIMIT 10."
        )
    if scan.statements > 1:
        return tool_error(
            "query_as_of",
            f"the query holds {scan.statements} statements separated by ';', but one runs per call",
            "send each statement in its own query_as_of call.",
        )
    if scan.writes:
        return tool_error(
            "query_as_of",
            "the query writes (" + ", ".join(scan.write_keywords) + "), but a time-travel read cannot write",
            "run writes with execute_gql against the current state.",
        )
    missing = sorted(scan.parameters - set(params or {}))
    if missing:
        names = ", ".join(f"${name}" for name in missing)
        return tool_error(
            "query_as_of",
            f"the query uses {names}, but params does not supply {'it' if len(missing) == 1 else 'them'}",
            'pass every parameter in params, e.g. params={"' + missing[0] + '": ...}.',
        )
    try:
        point = parse_time_point(as_of)
    except ValueError as exc:
        return tool_error("query_as_of", f"as_of={as_of!r} is not a point in time: {exc}", _POINT_HINT)

    db = ctx.request_context.lifespan_context.db
    try:
        result = db.execute_as_of(query, point, params)
        return _format_results(result, limit=limit)
    except Exception as exc:
        hint = _query_hint(exc, query)
        if "history" in str(exc).lower():
            hint = _NO_HISTORY_HINT
        return tool_error("query_as_of", f"query failed: {describe_exception(exc)}", hint)
