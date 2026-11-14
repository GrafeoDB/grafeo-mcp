from __future__ import annotations

import functools
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from mcp.types import CallToolResult, TextContent, ToolAnnotations

from grafeo_mcp.server import mcp

# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------
#
# Every tool returns a plain string. A failure is a single message that starts
# with ``Error: `` followed by the tool name, what went wrong (the engine's own
# message where there is one, unchanged) and, where useful, a ``Hint:`` naming
# the tool or step to try next. Over MCP the same text is sent as a tool result
# with ``isError: true``, so clients can tell failures from data without
# parsing the text. Successful results are JSON, except the short confirmation
# sentences of delete_node, delete_edge, create_vector_index and
# create_text_index.

ERROR_PREFIX = "Error: "


def tool_error(tool: str, problem: str, hint: str | None = None) -> str:
    """Build the error string for *tool*: ``Error: <tool>: <problem>. Hint: <hint>``."""
    problem = problem.strip() or "unknown error"
    multiline = "\n" in problem
    if not multiline and not problem.endswith((".", "!", "?")):
        problem += "."
    text = f"{ERROR_PREFIX}{tool}: {problem}"
    if hint:
        text += ("\n" if multiline else " ") + f"Hint: {hint}"
    return text


def is_error(result: str) -> bool:
    return result.startswith(ERROR_PREFIX)


def _is_engine_panic(exc: BaseException) -> bool:
    """True for ``pyo3_runtime.PanicException``: a Rust panic inside the engine.

    PyO3 derives it from ``BaseException``, so ``except Exception`` does not
    catch it and, uncaught, it takes the whole MCP server down.
    """
    return type(exc).__name__ == "PanicException"


_POINT_HINT = (
    'a number is seconds ago ("300" = 5 minutes ago), or an ISO-8601 datetime with its offset '
    '("2026-11-09T10:00:00+00:00").'
)

_NO_HISTORY_HINT = (
    "the database keeps no history for time-travel reads: start the server with "
    "GRAFEO_HISTORY_RETENTION=forever (or a number of seconds) to enable them."
)


def parse_time_point(as_of: str) -> timedelta | datetime:
    """Parse an ``as_of`` point: seconds ago as a number, or an aware ISO-8601 datetime."""
    text = as_of.strip()
    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds <= 0:
            raise ValueError("seconds ago must be positive")
        return timedelta(seconds=seconds)
    point = datetime.fromisoformat(text)
    if point.tzinfo is None or point.utcoffset() is None:
        raise ValueError("the datetime needs its UTC offset, e.g. 2026-11-09T10:00:00+00:00")
    return point


def describe_exception(exc: BaseException) -> str:
    """The engine's message for *exc*, or the exception type when it has none."""
    text = str(exc).strip()
    if _is_engine_panic(exc):
        return f"the grafeo engine panicked ({text}); this is an engine bug, please report it"
    return text or type(exc).__name__


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def guard(fn: Callable[..., str]) -> Callable[..., str]:
    """Wrap a tool so any exception it lets escape becomes an error string.

    Engine panics are caught too (they are ``BaseException`` subclasses);
    ``KeyboardInterrupt``, ``SystemExit`` and cancellation still propagate.
    """

    name = getattr(fn, "__name__", "tool")

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return tool_error(name, describe_exception(exc))
        except BaseException as exc:
            if not _is_engine_panic(exc):
                raise
            return tool_error(name, describe_exception(exc))

    return guarded


def grafeo_tool(
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: bool = False,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Register a function as an MCP tool with the grafeo-mcp error contract.

    The decorated function is returned wrapped in :func:`guard`, so direct
    callers always get a string. The registered MCP tool additionally reports
    error strings with ``isError: true``.

    Args:
        read_only: The tool never changes the database (MCP ``readOnlyHint``).
        destructive: The tool may overwrite or delete data (``destructiveHint``).
        idempotent: Repeating the call with the same arguments has no further
            effect (``idempotentHint``).
    """
    annotations = ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=None if read_only else destructive,
        idempotent_hint=None if read_only else idempotent,
        open_world_hint=False,
    )

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        guarded = guard(fn)

        @functools.wraps(fn)
        def mcp_entry(*args: Any, **kwargs: Any) -> str | CallToolResult:
            result = guarded(*args, **kwargs)
            if is_error(result):
                return CallToolResult(
                    content=[TextContent(type="text", text=result)],
                    structured_content={"result": result},
                    is_error=True,
                )
            return result

        mcp.tool(annotations=annotations)(mcp_entry)
        return guarded

    return decorator


# ---------------------------------------------------------------------------
# Read-only mode and argument checks
# ---------------------------------------------------------------------------


def _read_only_guard(ctx: Any, tool: str = "this tool") -> str | None:
    """Return an error string if the server is in read-only mode, else None."""
    if ctx.request_context.lifespan_context.read_only:
        return tool_error(
            tool,
            "the server is in read-only mode (GRAFEO_READ_ONLY=1), so mutation tools are disabled",
            "use read-only tools such as get_node, get_neighbors, search_nodes_by_label, "
            "graph_info or execute_gql with a MATCH ... RETURN query.",
        )
    return None


def check_range(tool: str, **values: tuple[int | float | None, int | float]) -> str | None:
    """Return an error string for the first ``name=(value, minimum)`` below its minimum."""
    for name, (value, minimum) in values.items():
        if value is not None and value < minimum:
            return tool_error(tool, f"{name} must be at least {minimum}, got {value}")
    return None


# ---------------------------------------------------------------------------
# Output size
# ---------------------------------------------------------------------------

_MAX_RESULT_CHARS = 8_000
"""Soft ceiling for serialised tool output, so the LLM context window is not
spent on thousands of rows or embedding values."""

_STRING_LIMITS = (1_000, 200, 60)


# grafeo 0.6 returns exact decimals (a GQL number with a point, such as 1.50,
# or a DECIMAL property) as ``decimal.Decimal``. The json module cannot write a
# Decimal as a number, so the encoder writes a marked string and to_json turns
# it back into a bare JSON number with the decimal's own digits: 1.50 stays
# 1.50 and 0.1 + 0.2 is 0.3, not a string and not a rounded float.
_DECIMAL_MARK = f"\x00grafeo-mcp-decimal-{uuid.uuid4().hex}:"
_DECIMAL_TOKEN = re.compile('"' + re.escape(json.dumps(_DECIMAL_MARK)[1:-1]) + r'([-+0-9.eE]+)"')


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal) and value.is_finite():
        return f"{_DECIMAL_MARK}{value}"
    return str(value)


def to_json(payload: Any, *, compact: bool = False) -> str:
    """Serialise a tool result to JSON.

    Decimals become JSON numbers that keep their digits; other values JSON
    cannot hold (dates, times, durations) become their text.
    """
    separators = (",", ":") if compact else None
    text = json.dumps(payload, default=_json_default, separators=separators)
    return _DECIMAL_TOKEN.sub(r"\1", text)


def _dumps(payload: Any) -> str:
    return to_json(payload, compact=True)


_META_KEYS = frozenset({"truncated", "omitted", "note"})


def _entries(container: list[Any] | dict[str, Any]) -> list[Any]:
    return list(container) if isinstance(container, dict) else list(range(len(container)))


def _entry_chars(container: list[Any] | dict[str, Any], key: Any) -> int:
    size = len(_dumps(container[key])) + 1  # the value plus its comma
    if isinstance(container, dict):
        size += len(_dumps(str(key))) + 1  # the key and its colon
    return size


def _largest_container(node: dict[str, Any] | list[Any], skip: frozenset[str] = frozenset()) -> Any | None:
    """Key of the largest non-empty list or dict directly inside *node*, if any."""
    best_key, best_size = None, -1
    for key in _entries(node):
        if key in skip:
            continue
        child = node[key]
        if isinstance(child, list | dict) and child:
            size = len(_dumps(child))
            if size > best_size:
                best_key, best_size = key, size
    return best_key


def _shrink(
    container: list[Any] | dict[str, Any], path: str, overflow: int, omitted: dict[str, int], limit: int
) -> int:
    """Drop entries from the end of *container* until about *overflow* characters are gone.

    An entry larger than half the budget is not dropped whole: in a list the
    first such entry is kept and cut inside (one huge community or path), and
    in an object the cut moves into its largest member (a record keeps its
    keys; a long string is left to the string pass). Returns the number of
    characters removed, as an estimate.
    """
    keys = _entries(container)
    if not keys:
        return 0
    if isinstance(container, dict):
        largest = max(keys, key=lambda key: _entry_chars(container, key))
        if _entry_chars(container, largest) > limit // 2:
            child = container[largest]
            if isinstance(child, list | dict):
                return _shrink(child, f"{path}.{largest}", overflow, omitted, limit)
            return 0
        keep_at_least = 0
    else:
        keep_at_least = 1 if _entry_chars(container, keys[0]) > limit // 2 else 0

    removed = 0
    count = len(keys)
    while count > keep_at_least and removed < overflow:
        count -= 1
        removed += _entry_chars(container, keys[count])
    if count < len(keys):
        if isinstance(container, list):
            del container[count:]
        else:
            for key in keys[count:]:
                del container[key]
        omitted[path] = omitted.get(path, 0) + len(keys) - count
    if removed < overflow and keep_at_least and isinstance(first := container[keys[0]], list | dict):
        removed += _shrink(first, f"{path}.{keys[0]}", overflow - removed, omitted, limit)
    return removed


def _shorten_strings(node: Any, max_len: int) -> Any:
    if isinstance(node, str) and len(node) > max_len:
        return node[:max_len] + f"... [{len(node)} chars]"
    if isinstance(node, list):
        return [_shorten_strings(item, max_len) for item in node]
    if isinstance(node, dict):
        return {key: _shorten_strings(value, max_len) for key, value in node.items()}
    return node


def _truncate(payload: Any, *, limit: int = _MAX_RESULT_CHARS) -> str:
    """Serialise *payload* to compact JSON that stays valid JSON within *limit* chars.

    When the payload is too large, entries are cut from the end of its largest
    lists and objects, then long strings are shortened. The result is an object
    with ``truncated: true``, ``omitted`` (path to the number of entries
    dropped) and a ``note``; a list payload is wrapped as
    ``{"results": [...], "truncated": true, ...}``.
    """
    text = _dumps(payload)
    if len(text) <= limit:
        return text

    original_chars = len(text)
    # parse_float=Decimal keeps every number's digits through the round trip.
    parsed = json.loads(text, parse_float=Decimal)
    work: dict[str, Any] = parsed if isinstance(payload, dict) else {"results": parsed}
    omitted: dict[str, int] = {}
    work["truncated"] = True
    work["omitted"] = omitted
    work["note"] = (
        f"Output exceeded {limit} characters ({original_chars} in full) and was cut: 'omitted' counts the "
        "entries dropped from the end of each list or object, and shortened strings end with '... [N chars]'. "
        "Ask for fewer results (lower limit, k or top_k) or a narrower query."
    )

    for _ in range(50):
        overflow = len(_dumps(work)) - limit
        if overflow <= 0:
            break
        key = _largest_container(work, skip=_META_KEYS)
        if key is None or _shrink(work[key], key, overflow, omitted, limit) == 0:
            break

    content = {key: value for key, value in work.items() if key not in _META_KEYS}
    for max_len in _STRING_LIMITS:
        if len(_dumps(work)) <= limit:
            break
        for key, value in content.items():
            work[key] = _shorten_strings(value, max_len)

    if len(_dumps(work)) <= limit:
        return _dumps(work)
    return _dumps(
        {
            "truncated": True,
            "note": f"Output of {original_chars} characters does not fit in {limit}. Ask for fewer results.",
        }
    )


# ---------------------------------------------------------------------------
# Shared summaries
# ---------------------------------------------------------------------------


def _node_summary(db: Any, node_id: int) -> dict[str, Any]:
    """Fetch a node and return a lightweight dict (id + labels + properties)."""
    node = db.get_node(node_id)
    if node is None:
        return {"node_id": node_id, "error": "node not found"}
    props = node.properties()
    # Drop large vector/embedding properties from the summary so we don't
    # blow up the output with thousands of floats.
    props = {k: v for k, v in props.items() if not (isinstance(v, list) and len(v) > 32)}
    return {"node_id": node_id, "labels": node.labels, "properties": props}


def _split_index_name(name: str) -> tuple[str, str]:
    label, _, prop = name.partition(":")
    return label, prop


def index_overview(db: Any, property_keys: list[str] | None = None) -> dict[str, Any]:
    """Vector, text and property indexes the database holds.

    Vector and text indexes come from ``memory_usage()`` (the Python API has no
    listing call for them); property indexes are probed per known property key.
    """
    overview: dict[str, Any] = {"vector": [], "text": [], "property": []}
    indexes = (db.memory_usage() or {}).get("indexes") or {}
    for kind, key in (("vector", "vector_indexes"), ("text", "text_indexes")):
        for entry in indexes.get(key) or []:
            label, prop = _split_index_name(str(entry.get("name", "")))
            overview[kind].append({"label": label, "property": prop, "items": entry.get("item_count")})
    keys = property_keys if property_keys is not None else list(db.schema().get("property_keys", []))
    overview["property"] = sorted(key for key in keys if db.has_property_index(key))
    return overview
