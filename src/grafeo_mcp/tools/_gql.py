"""Lightweight lexical scan of GQL query text.

This is not a parser. It walks the query once, skipping string literals,
backtick-quoted identifiers and comments the way the engine's GQL lexer does,
and reports what ``execute_gql`` needs to know before handing the text to the
engine:

* how many ``;``-separated statements the text holds (the engine runs one per
  call and rejects the rest),
* which ``$parameters`` it uses (so a missing value gets a precise error),
* which write keywords it contains (so read-only mode can refuse the query
  before it reaches the database),
* which labels, edge types and property keys it names (so a query that
  finds nothing can say which name does not exist in the graph).

The names are a best effort: ``(n:Label)``, ``[r:TYPE]``, ``WHERE n:Label``,
``n.key`` and ``{key: ...}`` inside a node or edge pattern are found;
``A|B`` and ``A&B`` label expressions count each name. A ``:Name`` outside a
pattern (``WHERE x:Name``) may be a label or an edge type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Clause keywords that write to the graph or its catalog. ``DETACH`` is always
# followed by ``DELETE`` but is listed so error messages name the clause the
# agent actually wrote.
WRITE_KEYWORDS = frozenset({"INSERT", "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "ALTER"})

# The engine's GQL lexer treats ``--`` followed by whitespace as a line comment
# (a bare ``--`` is an undirected edge) and ``/* ... */`` as a block comment.
_LINE_COMMENT_STARTS = ("-- ", "--\t", "--\n", "--\r")


@dataclass(slots=True)
class QueryScan:
    statements: int = 0
    parameters: set[str] = field(default_factory=set)
    write_keywords: list[str] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)
    edge_types: set[str] = field(default_factory=set)
    label_or_type: set[str] = field(default_factory=set)
    """Names after ``:`` outside a node or edge pattern: a label or an edge type."""
    property_keys: set[str] = field(default_factory=set)

    @property
    def writes(self) -> bool:
        return bool(self.write_keywords)


def _skip_quoted(text: str, start: int, quote: str) -> int:
    """Return the index just past the literal that opens at ``text[start]``.

    Strings end at the first unescaped quote (a backslash escapes the next
    character); backtick identifiers escape a backtick by doubling it. Both
    rules mirror the engine's lexer.
    """
    i = start + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if quote == "`":
            if ch == "`":
                if i + 1 < n and text[i + 1] == "`":
                    i += 2
                    continue
                return i + 1
        elif ch == "\\":
            i += 2
            continue
        elif ch == quote:
            return i + 1
        i += 1
    return n


def _word_end(text: str, start: int) -> int:
    i = start
    while i < len(text) and (text[i].isalnum() or text[i] == "_"):
        i += 1
    return i


def _next_significant(text: str, start: int) -> str:
    k = start
    while k < len(text) and text[k].isspace():
        k += 1
    return text[k] if k < len(text) else ""


# Bracket kinds on the scanner's stack.
_NODE, _EDGE, _CALL, _LIST, _MAP, _PATTERN_MAP = "node", "edge", "call", "list", "map", "pattern-map"

# Characters that continue a label expression (A|B, A&B, :A:B, !A, % wildcard).
_LABEL_JOINERS = frozenset("|&:!%")


def scan_query(text: str) -> QueryScan:
    """Scan *text*: statements, parameters, write keywords, and the names it uses."""
    scan = QueryScan()
    n = len(text)
    i = 0
    segment_has_content = False
    prev_significant = ""  # last character outside literals, comments and whitespace
    prev_word = ""  # the previous token, upper-cased, when it was a bare word
    prev_token = ""  # "word", "param" or "" for anything else
    last_word = ""
    property_dot = False  # the last "." followed a variable, so the next word is a property key
    stack: list[str] = []  # open brackets, by kind
    # Inside a label expression: "expect" right after ":" (or "|", "&"), "after"
    # right after a name. Names go to name_target.
    name_state: str | None = None
    name_target: set[str] = scan.label_or_type

    while i < n:
        ch = text[i]

        if ch in "'\"`":
            end = _skip_quoted(text, i, ch)
            if ch == "`" and name_state == "expect":
                name_target.add(text[i + 1 : end - 1].replace("``", "`"))
                name_state = "after"
            else:
                name_state = None
            i = end
            segment_has_content = True
            prev_significant = ch
            prev_word = ""
            prev_token = ""
            continue

        if ch == "-" and text.startswith(_LINE_COMMENT_STARTS, i):
            newline = text.find("\n", i)
            i = n if newline == -1 else newline + 1
            continue

        if ch == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue

        if ch == ";":
            if segment_has_content:
                scan.statements += 1
            segment_has_content = False
            prev_significant = ch
            prev_word = ""
            prev_token = ""
            stack.clear()
            name_state = None
            i += 1
            continue

        if ch.isspace():
            i += 1
            continue

        if ch == "$":
            end = _word_end(text, i + 1)
            if end > i + 1:
                scan.parameters.add(text[i + 1 : end])
            segment_has_content = True
            prev_significant = text[end - 1]
            prev_word = ""
            prev_token = "param"
            name_state = None
            i = end
            continue

        if ch.isalpha() or ch == "_":
            end = _word_end(text, i)
            word = text[i:end]
            next_significant = _next_significant(text, end)
            if name_state == "expect":
                name_target.add(word)
                name_state = "after"
            else:
                name_state = None
                if prev_significant == "." and property_dot and next_significant != "(":
                    scan.property_keys.add(word)
            # Property access (n.set), labels and edge types (:Set), map keys
            # ({set: 1}) and aliases (AS create) are not clause keywords.
            is_keyword_position = prev_significant not in {".", ":"} and next_significant != ":" and prev_word != "AS"
            upper = word.upper()
            if is_keyword_position and upper in WRITE_KEYWORDS and upper not in scan.write_keywords:
                scan.write_keywords.append(upper)
            segment_has_content = True
            prev_significant = word[-1]
            prev_word = upper
            prev_token = "word"
            last_word = word
            i = end
            continue

        if ch == ":" and text.startswith("::", i):  # a type annotation (x :: INT), not a label
            name_state = None
            i += 2
            prev_significant, prev_word, prev_token = ":", "", ""
            continue

        top = stack[-1] if stack else None
        if ch == ":":
            if name_state == "after":
                name_state = "expect"  # (n:A:B)
            elif top in (_MAP, _PATTERN_MAP):
                if top == _PATTERN_MAP and prev_token == "word":
                    scan.property_keys.add(last_word)
                name_state = None
            elif top == _CALL:
                name_state = None
            else:
                name_target = scan.labels if top == _NODE else scan.edge_types if top == _EDGE else scan.label_or_type
                name_state = "expect"
        elif ch in _LABEL_JOINERS and name_state is not None:
            name_state = "expect"  # A|B, A&B, !A, %
        else:
            name_state = None
            if ch == "(":
                after_word = i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")
                stack.append(_CALL if after_word else _NODE)
            elif ch == "[":
                stack.append(_EDGE if prev_significant in "-<" and prev_significant else _LIST)
            elif ch == "{":
                stack.append(_PATTERN_MAP if top in (_NODE, _EDGE) else _MAP)
            elif ch in ")]}" and stack:
                stack.pop()
            elif ch == ".":
                property_dot = prev_token == "word" and prev_significant != "."

        segment_has_content = True
        prev_significant = ch
        prev_word = ""
        prev_token = ""
        i += 1

    if segment_has_content:
        scan.statements += 1
    return scan
