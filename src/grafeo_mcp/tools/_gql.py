"""Lightweight lexical scan of GQL query text.

This is not a parser. It walks the query once, skipping string literals,
backtick-quoted identifiers and comments the way the engine's GQL lexer does,
and reports what ``execute_gql`` needs to know before handing the text to the
engine:

* how many ``;``-separated statements the text holds (the engine runs one per
  call and rejects the rest),
* which ``$parameters`` it uses (so a missing value gets a precise error),
* which write keywords it contains (so read-only mode can refuse the query
  before it reaches the database).
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


def scan_query(text: str) -> QueryScan:
    """Scan *text* and return its statement count, parameters and write keywords."""
    scan = QueryScan()
    n = len(text)
    i = 0
    segment_has_content = False
    prev_significant = ""  # last character outside literals, comments and whitespace
    prev_word = ""  # the previous token, upper-cased, when it was a bare word

    while i < n:
        ch = text[i]

        if ch in "'\"`":
            i = _skip_quoted(text, i, ch)
            segment_has_content = True
            prev_significant = ch
            prev_word = ""
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
            i = end
            continue

        if ch.isalpha() or ch == "_":
            end = _word_end(text, i)
            word = text[i:end]
            k = end
            while k < n and text[k].isspace():
                k += 1
            next_significant = text[k] if k < n else ""
            # Property access (n.set), labels and edge types (:Set), map keys
            # ({set: 1}) and aliases (AS create) are not clause keywords.
            is_keyword_position = prev_significant not in {".", ":"} and next_significant != ":" and prev_word != "AS"
            upper = word.upper()
            if is_keyword_position and upper in WRITE_KEYWORDS and upper not in scan.write_keywords:
                scan.write_keywords.append(upper)
            segment_has_content = True
            prev_significant = word[-1]
            prev_word = upper
            i = end
            continue

        segment_has_content = True
        prev_significant = ch
        prev_word = ""
        i += 1

    if segment_has_content:
        scan.statements += 1
    return scan
