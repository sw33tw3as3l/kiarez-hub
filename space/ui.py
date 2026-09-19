"""Curses primitives shared by the views: colors, chrome, the field editor."""

from __future__ import annotations

import curses
import sys
import termios
from dataclasses import dataclass

from . import fx
from .model import ESTIMATES, KINDS, duration_key, parse_duration
from .text import cols, ellipsis, fit, pad, wrap          # noqa: F401
from .theme import (                                        # noqa: F401
    C_ACCENT, C_DEEP, C_DIM, C_DOING, C_DONE, C_FRAME, C_GHOST, C_HEAD,
    C_NEON, C_SEL, C_SEL_ALT, C_VIOLET, C_WARN,
)
from .theme import init as init_theme


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
    init_theme()


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
    # addnstr's limit is counted in BYTES, `room` is screen columns, and a
    # character may be worth two columns. Trim by column here and hand
    # addnstr the resulting byte length.
    text = fit(text, room)
    try:
        win.addnstr(y, x, text, len(text.encode("utf-8")), a)
    except curses.error:
        pass


def frame(win, top: int, left: int, height: int, width: int,
          title: str = "", color: int = C_FRAME, accent: int = C_NEON) -> None:
    """A neon box. Corners are cut, because square corners look like a form."""
    a = attr(color)
    put(win, top, left, "╭" + "─" * (width - 2) + "╮", a)
    for y in range(top + 1, top + height - 1):
        put(win, y, left, "│", a)
        put(win, y, left + width - 1, "│", a)
    put(win, top + height - 1, left, "╰" + "─" * (width - 2) + "╯", a)
    if title:
        put(win, top, left + 3, f"┤ {title} ├", attr(accent, True))


def shade(win, top: int, left: int, height: int, width: int) -> None:
    """Blank the area a panel is about to occupy, so the board doesn't show."""
    for y in range(top, top + height):
        put(win, y, left, " " * width, attr(C_DIM))


def hline(win, y: int, x: int, width: int, a: int = 0) -> None:
    put(win, y, x, "─" * max(0, width), a)


# --- the field editor -------------------------------------------------------

@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"          # text | choice | date
    required: bool = False
    choices: list[tuple[str, str]] | None = None   # (value, label)
    value: str = ""
    hint: str | object = ""          # str, or a callable taking the value
    typed: str = ""                  # duration fields: what is being typed

    @property
    def hint_text(self) -> str:
        """Hints may be callables, so a choice can speak about the option
        you are standing on rather than about the field in general."""
        return self.hint(self.value) if callable(self.hint) else (self.hint or "")

    @property
    def display(self) -> str:
        if self.kind in ("choice", "duration"):
            table = dict(self.choices or [])
            return table.get(self.value, "— none —" if not self.value else self.value)
        return self.value or ""


def estimate_field(value: str = "", hint=None) -> Field:
    """Chips for the usual sizes, and free typing for everything else.

    A fixed scale is a guess about how your work divides up. Picking is fast
    for the common case; typing "1h45" covers the rest without making you go
    and edit a list first.
    """
    return Field("estimate", "Estimate", "duration", required=True,
                 choices=[(k, label) for k, label, _ in ESTIMATES], value=value,
                 hint=hint or
                 "← → to pick, or just type a length: 45m, 1h30, 2d")


def kind_field(value: str = "") -> Field:
    return Field("kind", "Kind", "choice", required=True, choices=list(KINDS),
                 value=value,
                 hint="Ship = someone else could notice it · Support = only helps you ship later")


class FormCancelled(Exception):
    pass


def run_form(stdscr, title: str, fields: list[Field], validate=None) -> dict | None:
    """Full-screen field editor. Returns {key: value}, or None if cancelled.

    `validate` takes the value dict and returns a list of problems; the form
    refuses to save while any remain.
    """
    idx, problems, editing = 0, [], False
    cursor = 0

    def settle(field) -> None:
        """Commit a typed length. Called before moving on and before saving,
        so what is on the screen is what gets written — typing 1h45 and
        tabbing away used to leave the field empty while still showing it."""
        if field.kind != "duration" or not field.typed:
            return
        minutes = parse_duration(field.typed)
        if minutes:
            field.value = duration_key(minutes)
        field.typed = ""

    pulse = fx.Pulse(0.9)
    stdscr.timeout(90)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        width = min(w - 4, 96)
        left = max(1, (w - width) // 2)
        rows = sum(2 + bool(i == idx and fld.hint_text)
                   for i, fld in enumerate(fields))
        height = min(h - 1, rows + 6 + (len(problems) + 1 if problems else 0))
        top = max(0, (h - height) // 2)

        shade(stdscr, top, left, height, width)
        frame(stdscr, top, left, height, width, title)

        y = top + 2
        label_x, value_x = left + 3, left + 22
        for i, field in enumerate(fields):
            selected = i == idx
            marker = "▸" if selected else " "
            label = field.label + (" *" if field.required else "")
            put(stdscr, y, label_x - 2, marker, attr(C_NEON, True))
            put(stdscr, y, label_x, label,
                attr(C_ACCENT if selected else C_DIM, selected))

            room = width - (value_x - left) - 4
            if field.kind == "duration" and field.typed:
                minutes = parse_duration(field.typed)
                reading = (f"{field.typed}▮   → {duration_key(minutes)}"
                           if minutes else f"{field.typed}▮   (keep going)")
                put(stdscr, y, value_x, pad(ellipsis(reading, room), room),
                    attr(C_NEON if minutes else C_DIM, bool(minutes)))
            elif field.kind in ("choice", "duration") and field.choices:
                # Every option on the row, the current one lit. Far clearer
                # than a single value you have to arrow through blind.
                x = value_x
                for val, text in field.choices:
                    chip = f" {ellipsis(text, 22)} "
                    if x - left + len(chip) > width - 3:
                        put(stdscr, y, x, "…", attr(C_DIM))
                        break
                    on = val == field.value
                    put(stdscr, y, x, chip,
                        attr(C_SEL if on and selected else
                             (C_NEON if on else C_DIM), on))
                    x += len(chip) + 1
            else:
                text = field.value or ""
                box = attr(C_GHOST) if not (selected and editing) else attr(C_DEEP)
                put(stdscr, y, value_x, pad(ellipsis(text, room), room), box)
                if selected and editing:
                    put(stdscr, y, value_x + min(cursor, room),
                        fx.caret(pulse.phase), attr(C_NEON, True))
                elif selected and not text:
                    put(stdscr, y, value_x, "enter to type", attr(C_DIM))

            hint = field.hint_text if selected else ""
            if hint:
                put(stdscr, y + 1, value_x, ellipsis(hint, room), attr(C_VIOLET))
                y += 1
            y += 2

        if problems:
            put(stdscr, y, label_x, "can't save yet", attr(C_WARN, True))
            for i, p in enumerate(problems):
                put(stdscr, y + 1 + i, label_x + 2, "· " + p, attr(C_WARN))

        keys = ("↑↓ move · ←→ choose · enter edit · ctrl-s save · esc cancel"
                if not editing else "typing — enter confirms · esc stops")
        put(stdscr, top + height - 2, label_x, keys, attr(C_DIM))

        missing = [fld.label.lower() for fld in fields
                   if fld.required and not str(fld.value).strip()]
        note = ("still missing: " + ", ".join(missing)) if missing else "ready to save"
        put(stdscr, top + height - 2, left + width - len(note) - 3, note,
            attr(C_WARN if missing else C_DONE))
        stdscr.refresh()

        f = fields[idx]          # the selected field — never the loop's last
        ch = stdscr.getch()
        if ch == -1:
            continue                                   # animation frame

        if ch == 27:                                   # Esc
            if editing:
                editing = False
                continue
            # A stray escape sequence shouldn't silently bin a filled-in form.
            if any(fld.value for fld in fields) and not confirm(
                    stdscr, "discard this form?", timeout=90):
                continue
            stdscr.timeout(-1)
            return None
        if ch in (19, curses.KEY_F2):                  # Ctrl-S / F2
            for fld in fields:
                settle(fld)
            values = {f.key: f.value for f in fields}
            problems = validate(values) if validate else []
            if not problems:
                stdscr.timeout(-1)
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
            settle(f)
            idx = (idx + 1) % len(fields)
        elif ch == curses.KEY_UP:
            settle(f)
            idx = (idx - 1) % len(fields)
        elif f.kind == "duration" and (
                chr(ch).isdigit() if 32 <= ch < 127 else False):
            f.typed += chr(ch)                 # a digit starts a typed length
        elif f.kind == "duration" and f.typed and 32 <= ch < 127 and \
                chr(ch).lower() in "dhm":
            f.typed += chr(ch).lower()
        elif f.kind == "duration" and f.typed and ch in (
                curses.KEY_BACKSPACE, 127, 8):
            f.typed = f.typed[:-1]
        elif f.kind == "duration" and f.typed and ch in (
                curses.KEY_ENTER, 10, 13):
            if parse_duration(f.typed):
                settle(f)
                idx = min(idx + 1, len(fields) - 1)
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT) and f.kind in (
                "choice", "duration"):
            f.typed = ""
            opts = [v for v, _ in (f.choices or [])]
            if opts:
                step = 1 if ch == curses.KEY_RIGHT else -1
                here = opts.index(f.value) if f.value in opts else -step % len(opts)
                f.value = opts[(here + step) % len(opts)]
        elif ch in (curses.KEY_ENTER, 10, 13):
            if f.kind == "text":
                editing, cursor = True, len(f.value)
            else:
                if not f.value and f.choices:
                    f.value = f.choices[0][0]
                idx = min(idx + 1, len(fields) - 1)
        elif 32 <= ch < 127 and f.kind in ("choice", "duration") and f.choices:
            letter = chr(ch).lower()
            match = next((v for v, text in f.choices
                          if text.lower().startswith(letter)), None)
            if match:
                f.value = match
        elif 32 <= ch < 127 and f.kind == "text":
            f.value += chr(ch)
            editing, cursor = True, len(f.value)


def prompt(stdscr, label: str, value: str = "", react=None) -> str | None:
    """A floating one-line input. Returns None if cancelled.

    This is the capture path, so it has to be quick, and it reacts as you
    type: the caret breathes, the frame lights up once there is something in
    it, and `react(value)` can put a live note under the field — which is how
    "nothing" gets told it is a real answer rather than an empty one.
    """
    curses.curs_set(0)
    cursor = len(value)
    pulse = fx.Pulse(0.9)
    stdscr.timeout(90)                 # wake up to animate even with no input
    try:
        while True:
            h, w = stdscr.getmaxyx()
            width = min(w - 6, max(48, len(label) + 42))
            left = max(2, (w - width) // 2)
            top = max(1, h // 2 - 2)

            shade(stdscr, top, left, 5, width)
            frame(stdscr, top, left, 5, width, label,
                  C_NEON if value else C_FRAME,
                  C_NEON if value else C_ACCENT)

            # Scroll a window that keeps the cursor inside it, rather than
            # always showing the tail — otherwise editing the middle of a long
            # line puts the caret somewhere the text isn't.
            inner = width - 6
            start = 0 if len(value) <= inner else max(0, min(cursor - inner + 1,
                                                            len(value) - inner))
            shown = fit(value[start:], inner)
            put(stdscr, top + 2, left + 3, pad(shown, inner), attr(C_GHOST))
            # The caret sits at the cursor's COLUMN offset, which is not its
            # character offset once anything wide is on the line.
            put(stdscr, top + 2, left + 3 + cols(value[start:cursor]),
                fx.caret(pulse.phase), attr(C_NEON, True))

            note, tone = (react(value) if react else (None, C_DIM))
            put(stdscr, top + 3, left + 3,
                ellipsis(note or "enter to save · esc to cancel", inner),
                attr(tone if note else C_DIM))
            stdscr.refresh()

            ch = stdscr.getch()
            if ch == -1:
                continue                       # just a frame of animation
            if ch == 27:
                return None
            if ch in (curses.KEY_ENTER, 10, 13):
                return value
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if cursor:
                    value = value[:cursor - 1] + value[cursor:]
                    cursor -= 1
            elif ch == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif ch == curses.KEY_RIGHT:
                cursor = min(len(value), cursor + 1)
            elif ch == curses.KEY_HOME:
                cursor = 0
            elif ch == curses.KEY_END:
                cursor = len(value)
            elif ch == curses.KEY_DC:
                value = value[:cursor] + value[cursor + 1:]
            elif ch == curses.KEY_RESIZE:
                continue
            elif 32 <= ch < 127:
                value = value[:cursor] + chr(ch) + value[cursor:]
                cursor += 1
    finally:
        stdscr.timeout(-1)
        curses.curs_set(0)


def confirm(stdscr, question: str, timeout: int = -1) -> bool:
    """A red-framed panel. Destructive things should look destructive.

    `timeout` is what to restore when the answer comes in — animated callers
    pass the cadence they were running at.
    """
    h, w = stdscr.getmaxyx()
    width = min(w - 6, max(40, len(question) + 10))
    left, top = max(2, (w - width) // 2), max(1, h // 2 - 2)
    shade(stdscr, top, left, 5, width)
    frame(stdscr, top, left, 5, width, "confirm", C_WARN, C_WARN)
    put(stdscr, top + 2, left + 3, ellipsis(question, width - 6), attr(C_GHOST))
    put(stdscr, top + 3, left + 3, "y to confirm · anything else cancels",
        attr(C_DIM))
    stdscr.refresh()

    # Wait for a real key. Callers that animate leave an input timeout set,
    # and inheriting it here means getch() returns -1 within a tenth of a
    # second and the question answers itself "no" before you can reach the
    # keyboard.
    stdscr.timeout(-1)
    try:
        while True:
            ch = stdscr.getch()
            if ch not in (-1, curses.KEY_RESIZE):
                return ch in (ord("y"), ord("Y"))
    finally:
        stdscr.timeout(timeout)
