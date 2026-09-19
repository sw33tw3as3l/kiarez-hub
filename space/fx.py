"""Motion and texture. Every effect here is short, skippable, and optional.

An effect that delays you is a bug — nothing in this file blocks for more
than a few hundred milliseconds, every animation aborts on a keypress, and
SPACE_NO_FX=1 turns the lot off.
"""

from __future__ import annotations

import curses
import random
import time

from .theme import (
    C_ACCENT, C_DIM, C_DOING, C_FRAME, C_GHOST, C_HEAD, C_NEON, C_VIOLET,
    fx_enabled,
)

BLOCKS = " ▏▎▍▌▋▊▉█"          # eighths, for sub-character bar precision
GLITCH = "▓▒░█▄▀▌▐■◼◤◢╱╲#%&@$"
SCAN = "─━"
HAZARD = "╱"                   # the diagonal stripe, for when it matters

BANNER = [
    "╦╔═╦╔═╗╦═╗╔═╗╔═╗   ╔═╗╔═╗╔═╗╔═╗╔═╗",
    "╠╩╗║╠═╣╠╦╝║╣ ╔═╝   ╚═╗╠═╝╠═╣║  ║╣ ",
    "╩ ╩╩╩ ╩╩╚═╚═╝╚═╝   ╚═╝╩  ╩ ╩╚═╝╚═╝",
]


def bar(value: float, peak: float, width: int) -> str:
    """A bar with eighth-character resolution, so small values still show."""
    if peak <= 0 or value <= 0:
        return ""
    cells = max(0.0, min(1.0, value / peak)) * width
    full = int(cells)
    rest = cells - full
    out = "█" * full
    if full < width and rest > 0.05:
        out += BLOCKS[max(1, round(rest * 8))]
    return out


def sparkline(values: list[float], height_chars: str = "▁▂▃▄▅▆▇█") -> str:
    if not values:
        return ""
    peak = max(values) or 1
    return "".join(height_chars[min(len(height_chars) - 1,
                                    int(v / peak * (len(height_chars) - 1)))]
                   for v in values)


def caret(phase: float) -> str:
    """A caret that breathes rather than blinks — blinking is louder."""
    return "▮▮▯▯"[int(phase * 4) % 4]


def glitched(text: str, amount: float) -> str:
    """Corrupt a proportion of the characters, for one frame of a boot effect."""
    if amount <= 0:
        return text
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch != " " and random.random() < amount:
            chars[i] = random.choice(GLITCH)
    return "".join(chars)


def _abort(stdscr) -> bool:
    """True if the user pressed something — every effect yields to input."""
    stdscr.nodelay(True)
    try:
        return stdscr.getch() != -1
    finally:
        stdscr.nodelay(False)


def hazard(width: int, phase: int = 0) -> str:
    """A run of diagonal stripes, offset by phase so it can appear to travel."""
    return "".join(HAZARD if (i + phase) % 3 else " " for i in range(max(0, width)))


def boot(stdscr, subtitle: str = "") -> None:
    """The title resolving out of noise, split into its colour channels.

    The channels pull apart and settle — the chromatic tear everything in
    this world is drawn with. Roughly half a second, and any key skips it.
    """
    if not fx_enabled():
        return
    from .ui import put                     # imported late: ui imports fx

    h, w = stdscr.getmaxyx()
    if h < 12 or w < 46:
        return
    top = max(1, h // 2 - 4)
    left = max(2, (w - len(BANNER[0])) // 2)

    for step in range(11):
        amount = max(0.0, 0.8 - step * 0.09)
        split = max(0, 3 - step // 3)       # the channels converge as it settles
        stdscr.erase()
        for i, line in enumerate(BANNER):
            noisy = glitched(line, amount)
            if split:
                put(stdscr, top + i, max(0, left - split), noisy,
                    curses.color_pair(C_DOING))          # magenta channel
                put(stdscr, top + i, left + split, noisy,
                    curses.color_pair(C_HEAD))           # cyan channel
            put(stdscr, top + i, left, noisy,
                curses.color_pair(C_NEON) | curses.A_BOLD)
        width = min(w - 8, len(BANNER[0]))
        put(stdscr, top + len(BANNER), left,
            hazard(width, step) if step % 2 else SCAN[1] * width,
            curses.color_pair(C_ACCENT if step % 2 else C_FRAME))
        if step > 5 and subtitle:
            put(stdscr, top + len(BANNER) + 2, left,
                glitched(subtitle, amount), curses.color_pair(C_DIM))
        stdscr.refresh()
        if _abort(stdscr):
            return
        curses.napms(40)


def sweep(stdscr, y: int, x: int, text: str, base: int, hot: int,
          width: int | None = None) -> None:
    """A light wave running once across a line — used when something lands."""
    if not fx_enabled() or not text:
        return
    from .ui import put

    span = width or len(text)
    for head in range(-3, span + 4, 2):
        for i, ch in enumerate(text[:span]):
            near = abs(i - head)
            attr = hot if near <= 1 else (
                hot | curses.A_DIM if near <= 3 else base)
            put(stdscr, y, x + i, ch, attr)
        stdscr.refresh()
        if _abort(stdscr):
            break
        curses.napms(12)
    put(stdscr, y, x, text[:span], base)


def type_out(stdscr, y: int, x: int, text: str, attr: int, per_char: int = 8) -> None:
    """Print a line as if it were being typed. Used sparingly — on answers."""
    if not fx_enabled():
        from .ui import put
        put(stdscr, y, x, text, attr)
        return
    from .ui import put
    for i in range(1, len(text) + 1):
        put(stdscr, y, x, text[:i], attr)
        put(stdscr, y, x + i, "▮", curses.color_pair(C_NEON))
        stdscr.refresh()
        if _abort(stdscr):
            break
        curses.napms(per_char)
    put(stdscr, y, x, text + " ", attr)


class Pulse:
    """A slow oscillator the UI can read for anything that should breathe."""

    def __init__(self, period: float = 1.4):
        self.period = period
        self.start = time.monotonic()

    @property
    def phase(self) -> float:
        return ((time.monotonic() - self.start) % self.period) / self.period

    def on(self, duty: float = 0.5) -> bool:
        return self.phase < duty
