"""The look: a neon palette on the terminal's own dark ground.

kitty reports can_change_color(), so the exact hex values below are written
into colour slots rather than approximated from the 256-cube. Where that is
not available (a plain tty, a stripped TERM) each colour falls back to its
nearest standard ANSI colour and everything still reads.
"""

from __future__ import annotations

import curses
import os

# --- the palette ------------------------------------------------------------
# Edgerunners: acid yellow carries everything, magenta is motion, cyan is
# structure, and the red is the one that costs you something. Almost all of
# the screen is slate on near-black, because that yellow only reads as neon
# when there is very little else competing with it.

HEX = {
    "yellow":  "#fcee0a",     # the signature — chrome, carets, selection
    "magenta": "#ff2bd6",     # in motion
    "cyan":    "#00f0ff",     # structure
    "mint":    "#00ffa3",     # shipped
    "red":     "#ff003c",     # what it cost
    "amber":   "#ff9f1c",
    "violet":  "#9a4dff",
    "ghost":   "#e8e4f0",
    "slate":   "#5c5470",
    "deep":    "#14121c",
    "ink":     "#08070c",
}

FALLBACK = {
    "yellow": curses.COLOR_YELLOW, "magenta": curses.COLOR_MAGENTA,
    "cyan": curses.COLOR_CYAN, "mint": curses.COLOR_GREEN,
    "red": curses.COLOR_RED, "amber": curses.COLOR_YELLOW,
    "violet": curses.COLOR_MAGENTA, "ghost": curses.COLOR_WHITE,
    "slate": curses.COLOR_WHITE, "deep": curses.COLOR_BLACK,
    "ink": curses.COLOR_BLACK,
}

FIRST_SLOT = 24          # leave the 16 ANSI colours and a little room alone
_slots: dict[str, int] = {}

# --- pair ids, in the order they get registered -----------------------------
(C_DIM, C_ACCENT, C_DONE, C_DOING, C_SEL, C_WARN, C_HEAD,
 C_NEON, C_FRAME, C_GHOST, C_SEL_ALT, C_VIOLET, C_DEEP) = range(1, 14)

PAIRS = [
    (C_DIM,     "slate",   None),
    (C_ACCENT,  "yellow",  None),     # the signature colour does the pointing
    (C_DONE,    "mint",    None),
    (C_DOING,   "magenta", None),     # work in motion runs hot
    (C_SEL,     "ink",     "yellow"),
    (C_WARN,    "red",     None),
    (C_HEAD,    "cyan",    None),
    (C_NEON,    "yellow",  None),
    (C_FRAME,   "violet",  None),
    (C_GHOST,   "ghost",   None),
    (C_SEL_ALT, "ink",     "magenta"),
    (C_VIOLET,  "violet",  None),
    (C_DEEP,    "ghost",   "deep"),
]


def _rgb1000(hex_code: str) -> tuple[int, int, int]:
    """#rrggbb to curses' 0-1000 scale."""
    h = hex_code.lstrip("#")
    return tuple(round(int(h[i:i + 2], 16) * 1000 / 255) for i in (0, 2, 4))


def slot(name: str) -> int:
    return _slots.get(name, FALLBACK[name])


def init() -> None:
    """Register the palette. Safe to call once a screen exists."""
    curses.start_color()
    curses.use_default_colors()

    if curses.can_change_color() and curses.COLORS >= FIRST_SLOT + len(HEX):
        for i, (name, hex_code) in enumerate(HEX.items()):
            index = FIRST_SLOT + i
            try:
                curses.init_color(index, *_rgb1000(hex_code))
                _slots[name] = index
            except curses.error:
                pass                      # keep the ANSI fallback for this one

    for pair, fg, bg in PAIRS:
        try:
            curses.init_pair(pair, slot(fg), slot(bg) if bg else -1)
        except curses.error:
            pass


def fx_enabled() -> bool:
    """Animations can be switched off — SPACE_NO_FX=1."""
    return os.environ.get("SPACE_NO_FX", "") not in ("1", "true", "yes")
