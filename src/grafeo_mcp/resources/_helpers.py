from __future__ import annotations


def _format_value(v: object, *, str_limit: int = 80, list_limit: int = 8, list_preview: int = 4) -> str:
    """Format a property value for display, truncating long strings and vectors.

    Args:
        v: The value to format.
        str_limit: Maximum string length before truncation (default 80).
        list_limit: List length threshold that triggers truncation (default 8).
        list_preview: Number of list items to show in the preview (default 4).
    """
    if isinstance(v, str):
        if len(v) > str_limit:
            return f'"{v[: str_limit - 3]}..."'
        return f'"{v}"'
    if isinstance(v, list):
        if len(v) > list_limit:
            preview = ", ".join(str(x) for x in v[:list_preview])
            return f"[{preview}, ...] ({len(v)} items)"
        return str(v)
    return str(v)
