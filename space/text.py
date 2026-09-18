"""Measuring text in terminal columns.

A codepoint is not a column. CJK and most emoji take two, combining marks and
zero-width joiners take none, and `len()` counts all three as one — which is
how a Persian or Chinese title ends up bleeding into the next board column.
Everything that lays out text goes through here, including the CLI, which is
why this module deliberately imports nothing.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

@lru_cache(maxsize=4096)
def char_cols(ch: str) -> int:
    """How many terminal columns one character occupies."""
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def cols(text: str) -> int:
    """Display width of a string, in terminal columns."""
    return sum(char_cols(ch) for ch in text)


def fit(text: str, width: int) -> str:
    """Truncate to a column width, never splitting a wide character."""
    if width <= 0:
        return ""
    out, used = [], 0
    for ch in text:
        w = char_cols(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


def pad(text: str, width: int) -> str:
    """Pad to a column width — str.ljust counts codepoints, which is wrong."""
    return text + " " * max(0, width - cols(text))


def ellipsis(text: str, width: int) -> str:
    """Trim to `width` COLUMNS, marking the cut."""
    text = (text or "").replace("\n", " ")
    if width <= 0:
        return ""
    if cols(text) <= width:
        return text
    return fit(text, max(0, width - 1)) + "…"


def wrap(text: str, width: int) -> list[str]:
    words, lines, cur = (text or "").split(), [], ""
    for word in words:
        if cols(cur) + cols(word) + (1 if cur else 0) <= width:
            cur += (" " if cur else "") + word
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


