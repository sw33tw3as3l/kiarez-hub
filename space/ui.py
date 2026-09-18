"""Curses primitives shared by the views: colors, chrome, the field editor."""

from __future__ import annotations

import curses
import sys
import termios
from dataclasses import dataclass

from .model import EFFORTS, EFFORT_LABELS

# Color pair ids. The palette echoes the old Material You ember theme:
# ember for "doing"/accents, green for done, dim grey for idle.
C_DIM, C_ACCENT, C_DONE, C_DOING, C_SEL, C_WARN, C_HEAD = range(1, 8)


def disable_flow_control() -> None:
    """Stop the tty eating Ctrl-S as XOFF, which would freeze the display.

    Without this the save key never reaches the program: the terminal
    treats Ctrl-S as "pause output" and Ctrl-Q as "resume".
    """
    try:
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~(termios.IXON | termios.IXOFF)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (termios.error, ValueError, OSError):
        pass          # not a real tty (piped input, test harness) — nothing to do


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)
    curses.init_pair(C_ACCENT, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_DONE, curses.COLOR_GREEN, -1)
    curses.init_pair(C_DOING, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_SEL, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(C_WARN, curses.COLOR_RED, -1)
    curses.init_pair(C_HEAD, curses.COLOR_CYAN, -1)


def attr(pair: int, bold: bool = False) -> int:
    a = curses.color_pair(pair)
    return a | curses.A_BOLD if bold else a


def put(win, y: int, x: int, text: str, a: int = 0, width: int | None = None) -> None:
    """Bounds-safe write — curses raises if you touch the last cell."""
    h, w = win.getmaxyx()
    if not (0 <= y < h) or x >= w:
        return
    room = (w - x - 1) if width is None else min(width, w - x - 1)
    if room <= 0:
        return
    try:
        win.addnstr(y, x, text, room, a)
    except curses.error:
        pass


def hline(win, y: int, x: int, width: int, a: int = 0) -> None:
    put(win, y, x, "─" * max(0, width), a)


def ellipsis(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ")
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def wrap(text: str, width: int) -> list[str]:
    words, lines, cur = (text or "").split(), [], ""
    for word in words:
        if len(cur) + len(word) + (1 if cur else 0) <= width:
            cur += (" " if cur else "") + word
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


# --- the field editor -------------------------------------------------------

@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"          # text | choice | date
    required: bool = False
    choices: list[tuple[str, str]] | None = None   # (value, label)
    value: str = ""
    hint: str = ""

    @property
    def display(self) -> str:
        if self.kind == "choice":
            table = dict(self.choices or [])
            return table.get(self.value, "— none —" if not self.value else self.value)
        return self.value or ""


def effort_field(value: str = "") -> Field:
    return Field("effort", "Effort", "choice", required=True,
                 choices=list(EFFORTS), value=value,
                 hint="← → to pick; half-day or bigger can't go on the day board")


class FormCancelled(Exception):
    pass


def run_form(stdscr, title: str, fields: list[Field], validate=None) -> dict | None:
    """Full-screen field editor. Returns {key: value}, or None if cancelled.

    `validate` takes the value dict and returns a list of problems; the form
    refuses to save while any remain.
    """
    idx, problems, editing = 0, [], False
    cursor = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        put(stdscr, 0, 2, title, attr(C_HEAD, True))
        hline(stdscr, 1, 2, w - 4, attr(C_DIM))

        y = 3
        for i, f in enumerate(fields):
            selected = i == idx
            label = f.label + (" *" if f.required else "")
            put(stdscr, y, 2, label, attr(C_ACCENT if selected else C_DIM, selected))
            box_a = attr(C_SEL) if (selected and editing) else attr(
                C_DIM, selected)
            shown = f.display or ("…" if f.kind == "text" else "")
            put(stdscr, y, 22, ellipsis(shown, w - 26).ljust(min(w - 26, 56)), box_a)
            if selected and f.hint:
                put(stdscr, y + 1, 22, f.hint, attr(C_DIM))
                y += 1
            y += 2

        if problems:
            put(stdscr, h - 4 - len(problems), 2, "Can't save yet:", attr(C_WARN, True))
            for i, p in enumerate(problems):
                put(stdscr, h - 3 - len(problems) + i, 4, "• " + p, attr(C_WARN))

        keys = ("type to edit · ←/→ change · Enter next · Ctrl-S or F2 save · Esc cancel"
                if not editing else
                "editing — Enter/Tab to confirm · Esc to stop editing")
        put(stdscr, h - 2, 2, keys, attr(C_DIM))
        f = fields[idx]
        if editing and f.kind == "text":
            curses.curs_set(1)
            stdscr.move(3 + idx * 2, min(22 + cursor, w - 2))
        else:
            curses.curs_set(0)
        stdscr.refresh()

        ch = stdscr.getch()

        if ch == 27:                                   # Esc
            if editing:
                editing = False
                continue
            # A stray escape sequence shouldn't silently bin a filled-in form.
            if any(f.value for f in fields) and not confirm(
                    stdscr, "discard this form?"):
                continue
            return None
        if ch in (19, curses.KEY_F2):                  # Ctrl-S / F2
            values = {f.key: f.value for f in fields}
            problems = validate(values) if validate else []
            if not problems:
                return values
            continue
        if ch == curses.KEY_RESIZE:
            continue

        if editing and f.kind == "text":
            if ch in (curses.KEY_ENTER, 10, 13, 9):
                editing = False
                idx = min(idx + 1, len(fields) - 1)
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if cursor:
                    f.value = f.value[: cursor - 1] + f.value[cursor:]
                    cursor -= 1
            elif ch == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif ch == curses.KEY_RIGHT:
                cursor = min(len(f.value), cursor + 1)
            elif ch == curses.KEY_DC:
                f.value = f.value[:cursor] + f.value[cursor + 1:]
            elif 32 <= ch < 127:
                f.value = f.value[:cursor] + chr(ch) + f.value[cursor:]
                cursor += 1
            continue

        if ch in (curses.KEY_DOWN, 9):
            idx = (idx + 1) % len(fields)
        elif ch == curses.KEY_UP:
            idx = (idx - 1) % len(fields)
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT) and f.kind == "choice":
            opts = [v for v, _ in (f.choices or [])]
            if opts:
                step = 1 if ch == curses.KEY_RIGHT else -1
                here = opts.index(f.value) if f.value in opts else -step % len(opts)
                f.value = opts[(here + step) % len(opts)]
        elif ch in (curses.KEY_ENTER, 10, 13):
            if f.kind == "text":
                editing, cursor = True, len(f.value)
            else:
                idx = min(idx + 1, len(fields) - 1)
        elif 32 <= ch < 127 and f.kind == "text":
            f.value += chr(ch)
            editing, cursor = True, len(f.value)


def confirm(stdscr, question: str) -> bool:
    h, w = stdscr.getmaxyx()
    put(stdscr, h - 1, 2, f"{question} [y/N]".ljust(w - 4), attr(C_WARN, True))
    stdscr.refresh()
    return stdscr.getch() in (ord("y"), ord("Y"))
