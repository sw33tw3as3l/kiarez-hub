"""Five views over the local database."""

from __future__ import annotations

import calendar
import curses
import os
import random
import time
from datetime import date, datetime

from . import db
from .review import WEEKLY, owed, questions_for, review_day, weekly_owed
from .model import (
    ESTIMATE_KEYS, ESTIMATE_LABELS, ESTIMATE_MINUTES, GREETINGS,
    NAGGING_ROLLS, STALE_DAYS, STATUS_KEYS, STATUS_LABELS, add_days, can_start,
    done_count, estimate_accuracy, estimate_hint, fmt_minutes, parse_duration,
    today,
)
from . import fx
from .theme import fx_enabled  # noqa: F401
from .ui import cols, fit, pad  # noqa: F401
from .ui import (
    C_ACCENT, C_DEEP, C_DIM, C_DOING, C_DONE, C_FRAME, C_GHOST, C_HEAD,
    C_NEON, C_SEL, C_SEL_ALT, C_VIOLET, C_WARN, Field, attr, confirm,
    disable_flow_control, ellipsis, estimate_field, frame, hline, init_colors,
    prompt, put, run_form, wrap,
)

VIEWS = [("today", "Today"), ("calendar", "Calendar"), ("inbox", "Inbox"),
         ("tree", "Tree"), ("review", "Review")]

# A quiet second label on each view. Decoration, but decoration that still
# says which screen you are on.
TAGS = {"today": "今日", "calendar": "暦", "inbox": "受信",
        "tree": "系統", "review": "反省"}

STATUS_COLOR = {"todo": C_DIM, "doing": C_DOING, "done": C_DONE}

# Watchlist colours, as chosen per app. Red is time spent against you and is
# what the day strip counts as distraction; the rest is time merely accounted for.
APP_COLOR = {"red": C_WARN, "yellow": C_DOING, "green": C_DONE,
             "cyan": C_ACCENT, "dim": C_DIM}

HELP = [
    ("1-5 / Tab", "switch view"),
    ("c", "capture — one line, no fields, from any view"),
    ("/", "filter the board · empty clears it"),
    ("f / F", "in Tree: scope the board to that branch / clear the scope"),
    ("X / I", "in Review: kill or re-inbox everything rotting"),
    ("j k / h l", "move · J K reorder"),
    ("space", "advance status — refuses to start an undefined task"),
    ("e / Enter", "define or edit"),
    ("s / S", "schedule onto the open day / send back to inbox"),
    ("w", "answer the day's questions"),
    ("W", "answer the week's, on the Monday after it ends"),
    ("a", "in Tree: add a child · A adds a root · m moves · x deletes"),
    ("[ ] t", "previous day / next day / today"),
    ("g", "go to a date — YYYY-MM-DD, or +3 / -7"),
    ("< >", "move the selected task to another day"),
    ("? q", "help / quit"),
]


class App:
    def __init__(self, stdscr, conn):
        self.stdscr = stdscr
        self.conn = conn
        self.view = "today"
        self.day = today()
        self.col = 0
        self.row = 0
        self.list_row = 0            # inbox / tree / review cursor
        self.message = ""
        self.greeting = random.choice(GREETINGS)
        self.pulse = fx.Pulse(1.3)
        self.message_at = 0.0
        self.glitch_until = 0.0
        self.filter = ""
        self.node_filter: str | None = None
        self.cal_cursor = date.fromisoformat(self.day)
        self.collapsed: set[str] = set()
        rolled = db.roll_forward(conn)
        db.close_out(conn, today())
        if rolled:
            self.message_at = time.monotonic()
            self.message = f"{rolled} unfinished task(s) rolled forward to today"
        # Anything owed is handled by the lock, so this is only about tonight:
        # a nudge late in the day that today is not written down yet. Earlier
        # than that it would be nagging about a day still being lived.
        if (datetime.now().hour >= 20
                and not db.day_log(conn, today()).answered):
            note = "today is not written down yet — press w"
            self.message_at = time.monotonic()
            self.message = f"{self.message} · {note}" if self.message else note
        if weekly_owed(conn):
            note = "last week is unreviewed — press W"
            self.message_at = time.monotonic()
            self.message = f"{self.message} · {note}" if self.message else note

    # --- data ---------------------------------------------------------------

    @property
    def tree(self):
        return db.tree(self.conn)

    def node_choices(self):
        """Every node, indented, so the form shows where it sits."""
        t = self.tree
        return [(n.id, "  " * depth + n.name) for n, depth in t.walk()]

    def visible_nodes(self):
        """(node, depth) in display order, skipping collapsed subtrees."""
        t = self.tree
        out = []

        def walk(parent, depth):
            for n in t.kids(parent):
                # A branch stays visible when anything beneath it matches,
                # otherwise filtering a tree just empties it.
                subtree = [n] + t.descendants(n.id)
                if self.filter and not any(self.matches(x.name) for x in subtree):
                    continue
                out.append((n, depth))
                if n.id not in self.collapsed:
                    walk(n.id, depth + 1)

        walk(None, 0)
        return out

    def selected_node(self):
        items = self.visible_nodes()
        if not items:
            return None
        self.list_row = min(self.list_row, len(items) - 1)
        return items[self.list_row][0]

    def read_tasks(self, **kw):
        """db.tasks for the current frame, materialised at most once."""
        key = tuple(sorted(kw.items()))
        cache = getattr(self, "_frame_cache", None)
        if cache is None:
            return db.tasks(self.conn, **kw)
        if key not in cache:
            cache[key] = db.tasks(self.conn, **kw)
        return cache[key]

    def matches(self, text: str) -> bool:
        return not self.filter or self.filter in (text or "").lower()

    def scope_ids(self) -> set[str] | None:
        """The node ids the board is scoped to, or None for all of them."""
        if not self.node_filter:
            return None
        t = self.tree
        return {self.node_filter} | {d.id for d in t.descendants(self.node_filter)}

    def keep(self, tasks):
        """Apply the active filters: the text one, and the branch one."""
        ids = self.scope_ids()
        if ids is not None:
            tasks = [t for t in tasks if t.node_id in ids]
        if not self.filter:
            return tasks
        return [t for t in tasks
                if self.matches(t.title) or self.matches(t.outcome)
                or self.matches(t.next_action)]

    def columns(self):
        items = self.keep(self.read_tasks(day=self.day))
        return {s: [t for t in items if t.status == s] for s in STATUS_KEYS}

    def selected(self):
        items = self.columns()[STATUS_KEYS[self.col]]
        if not items:
            return None
        self.row = min(self.row, len(items) - 1)
        return items[self.row]

    def inbox(self):
        return self.keep(self.read_tasks(inbox=True))

    def selected_inbox(self):
        items = self.inbox()
        if not items:
            return None
        self.list_row = min(self.list_row, len(items) - 1)
        return items[self.list_row]

    def stale(self, tasks=None):
        """Work that has stopped being work: untouched, or endlessly rolled."""
        out = []
        for t in (self.read_tasks() if tasks is None else tasks):
            if t.status == "done":
                continue
            if t.rolls >= NAGGING_ROLLS:
                out.append((t, f"rolled {t.rolls}×"))
            elif t.stale_days() >= STALE_DAYS:
                out.append((t, f"untouched {t.stale_days()}d"))
        return out

    # --- drawing ------------------------------------------------------------

    def draw(self):
        # One frame, one set of reads. draw_day alone asked for the day's
        # tasks three times over, and every view rebuilt the same objects for
        # its chips; on a large board that was the whole frame budget.
        self._frame_cache = {}
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        self.draw_header(w)
        body = h - 5
        {"today": self.draw_day, "calendar": self.draw_calendar,
         "inbox": self.draw_inbox, "tree": self.draw_tree,
         "review": self.draw_review}[self.view](3, body, w)
        self.draw_footer(h, w)
        self.stdscr.refresh()

    def badges(self) -> dict[str, int]:
        """What each view would tell you if you went there.

        Counted in SQL: these three numbers are on screen every frame and
        loading the whole task table to work them out was most of the cost of
        drawing one.
        """
        if self.filter:
            # A text filter has to read the text, so count what the views
            # themselves would actually show rather than asking SQL.
            counts = {
                "inbox": len(self.inbox()),
                "review": len(self.stale()),
                "today": sum(1 for group in self.columns().values()
                             for t in group if not t.defined),
            }
        else:
            counts = db.badge_counts(self.conn, self.day, STALE_DAYS,
                                     NAGGING_ROLLS, self.scope_ids())
        return {k: v for k, v in counts.items() if v}

    def draw_header(self, w):
        badges = self.badges()

        # Lay the chips out first — they are the navigation and they win. The
        # wordmark then takes whatever is left, shedding the greeting and then
        # its own tail rather than being written over. Below about seventy
        # columns the labels go too, but the numbers never do: losing the
        # shortcut keys off the left edge is worse than losing their names.
        def chip_for(i, key, label, full):
            badge = f"·{badges[key]}" if badges.get(key) else ""
            if full or key == self.view:
                return f" {i + 1} {label}" + (f" {badge} " if badge else " ")
            return f" {i + 1}{badge} "

        full = sum(cols(chip_for(i, k, l, True)) + 1
                   for i, (k, l) in enumerate(VIEWS)) <= w - 12
        widths = [chip_for(i, k, l, full) for i, (k, l) in enumerate(VIEWS)]
        room = w - sum(cols(c) + 1 for c in widths) - 6

        put(self.stdscr, 0, 1, "◤", attr(C_NEON, True))
        if room >= 6:
            # The channels do not line up. Writing the word three times, one
            # column apart, leaves a magenta edge on its left and a cyan one
            # on its right — the tear everything in this world is drawn with,
            # standing still.
            # The channels show at the edges rather than as doubled letters:
            # a magenta bar on the left, a cyan one on the right. Ghosted
            # glyphs read as a rendering fault; bars read as intent.
            put(self.stdscr, 0, 2, "▌", attr(C_DOING))
            put(self.stdscr, 0, 3, "KIAREZ", attr(C_NEON, True))
            put(self.stdscr, 0, 9, "▐", attr(C_HEAD))
        if room >= 18:
            put(self.stdscr, 0, 11, "／", attr(C_VIOLET))
            put(self.stdscr, 0, 13, "▌", attr(C_DOING))
            put(self.stdscr, 0, 14, "SPACE", attr(C_ACCENT, True))
            put(self.stdscr, 0, 19, "▐", attr(C_HEAD))
        if room >= 23 + len(self.greeting) and not (self.filter or self.node_filter):
            put(self.stdscr, 0, 22, self.greeting, attr(C_VIOLET))
        tag = TAGS.get(self.view, "")
        if tag and room >= 29 + len(self.greeting) and not (
                self.filter or self.node_filter):
            put(self.stdscr, 0, 24 + len(self.greeting), tag, attr(C_DOING))
        scope = ""
        if self.node_filter:
            scope = "▣ " + (db.node_paths(self.conn).get(self.node_filter, "?")
                            .split(" › ")[-1])
        if self.filter:
            scope = (scope + " " if scope else "") + f"/{self.filter}"
        if scope and room >= 14:
            put(self.stdscr, 0, min(22, max(3, room - 12)),
                ellipsis(scope, 26), attr(C_SEL_ALT, True))
        put(self.stdscr, 0, w - 2, "◥", attr(C_NEON, True))

        x = w - 4
        for i in range(len(VIEWS) - 1, -1, -1):
            key, label = VIEWS[i]
            chip, count = widths[i], badges.get(key)
            x -= cols(chip) + 1
            if x < 1:
                break                      # no room left; drop the rest
            on = key == self.view
            put(self.stdscr, 0, x, chip,
                attr(C_SEL_ALT, True) if on else attr(C_DIM))
            if count and not on:
                # The number is the point; keep it lit even when the chip isn't.
                put(self.stdscr, 0, x + chip.index(f"·{count}"),
                    f"·{count}", attr(C_NEON, True))

        # The rule burns under the live view and fades away from it. On a
        # view change it tears for a couple of frames, then settles.
        # The rule goes to hazard stripes once the day has cost you an hour.
        # It is the one piece of chrome that changes meaning during the day.
        burned = db.usage_total(self.conn, self.day, color="red") >= 3600
        rule = fx.hazard(w - 3, int(time.monotonic()) % 3) if burned \
            else "─" * (w - 3)
        if time.monotonic() < self.glitch_until:
            rule = fx.glitched(rule, 0.35)
        put(self.stdscr, 1, 1, rule, attr(C_WARN if burned else C_FRAME))
        put(self.stdscr, 1, 1, "━" * 18, attr(C_NEON))
        put(self.stdscr, 1, 19, "╸", attr(C_ACCENT))

    def day_strip(self, y, w):
        """The line that says whether this day was real."""
        items = self.keep(self.read_tasks(day=self.day))
        finished, total = done_count(items)
        distraction = db.usage_total(self.conn, self.day, color="red") // 60
        tracked = db.usage_total(self.conn, self.day) // 60
        log = db.day_log(self.conn, self.day)

        d = date.fromisoformat(self.day)
        stamp = d.strftime("%Y.%m.%d %a").upper()
        put(self.stdscr, y, 2, stamp, attr(C_ACCENT, True))
        if self.day == today():
            put(self.stdscr, y, 2 + cols(stamp) + 1, "◂", attr(C_NEON, True))

        x = 34
        put(self.stdscr, y, x, f"◆ {finished}/{total}",
            attr(C_DONE if finished else C_DIM))
        x += 10

        # A gauge, not a number: four hours of red is the full bar.
        segments = 10
        filled = min(segments, round(distraction / 240 * segments))
        hot = distraction >= 60
        put(self.stdscr, y, x, "▲", attr(C_WARN if hot else C_DIM))
        put(self.stdscr, y, x + 2, "▰" * filled,
            attr(C_WARN, hot and self.pulse.on(0.55)))
        put(self.stdscr, y, x + 2 + filled, "▱" * (segments - filled), attr(C_DIM))
        put(self.stdscr, y, x + 3 + segments, fmt_minutes(distraction),
            attr(C_WARN if hot else C_DIM))
        x += segments + 10

        # What you are on right now, and for how long — the one number the
        # board can show that changes while you watch it.
        doing = [t for t in self.read_tasks(day=self.day, status="doing")]
        if doing:
            t = doing[0]
            run = fmt_minutes(t.actual_minutes)
            if t.overrun:
                # Stopped counting: this is a forgotten timer, and saying so
                # is the only way the number stays worth anything.
                run += " ⚠ stopped counting"
            over = t.overrun or (t.estimate_minutes
                                 and t.actual_minutes > t.estimate_minutes)
            put(self.stdscr, y, x, "◈", attr(C_DOING, self.pulse.on(0.5)))
            put(self.stdscr, y, x + 2,
                ellipsis(f"{t.title} {run}", max(12, w - x - 30)),
                attr(C_WARN if over else C_DOING))
            x += min(len(t.title) + len(run) + 6, max(18, w - x - 26))

        span = [add_days(self.day, -i) for i in range(6, -1, -1)]
        by_day = db.usage_totals(self.conn, span, color="red")
        week = [by_day.get(d, 0) for d in span]
        if any(week):
            put(self.stdscr, y, x, fx.sparkline(week), attr(C_VIOLET))
            x += 9
        put(self.stdscr, y, x, f"◇ {fmt_minutes(tracked)}", attr(C_DIM))
        x += 11
        if log.answered:
            room = max(10, (w - x - 6) // 2)
            put(self.stdscr, y, x, f"did: {ellipsis(log.did, room)}", attr(C_DONE))
            if log.not_done:
                x2 = x + 5 + min(len(log.did), room) + 3
                put(self.stdscr, y, x2, f"not: {ellipsis(log.not_done, room)}",
                    attr(C_WARN))
        elif self.day == review_day(conn=self.conn):
            put(self.stdscr, y, x, "unanswered — press w",
                attr(C_WARN, self.pulse.on(0.6)))
        elif self.day < today():
            put(self.stdscr, y, x, "unanswered, and closed", attr(C_DIM))

    def draw_day(self, top, height, w):
        self.day_strip(top - 1, w)
        cols = self.columns()
        detail_h, cw = 7, max(18, (w - 6) // 3)
        list_h = height - detail_h - 1

        for ci, status in enumerate(STATUS_KEYS):
            x, items = 2 + ci * cw, cols[STATUS_KEYS[ci]]
            head = f"{STATUS_LABELS[status].upper()} ▚ {len(items):02d}"
            put(self.stdscr, top, x, head,
                attr(STATUS_COLOR[status], ci == self.col))
            live = ci == self.col
            hline(self.stdscr, top + 1, x, cw - 2, attr(C_FRAME))
            if live:
                put(self.stdscr, top + 1, x, "━" * min(cw - 2, len(head) + 2),
                    attr(C_NEON))
            start = self.scroll_start(items, ci, list_h - 2)
            if start:
                put(self.stdscr, top + 2, x, f"↑ {start} above", attr(C_DIM))
            y = top + (3 if start else 2)
            for ri, t in enumerate(items):
                if ri < start:
                    continue
                if y >= top + list_h - 1:
                    put(self.stdscr, y, x, f"↓ {len(items) - ri} more", attr(C_DIM))
                    break
                on = ci == self.col and ri == self.row
                edge = "┃" if on else "│"
                put(self.stdscr, y, x, edge,
                    attr(C_NEON if on else C_FRAME, on))
                put(self.stdscr, y, x + 2, ellipsis(t.title, cw - 6),
                    attr(C_SEL, True) if on else attr(STATUS_COLOR[status]))
                y += 1
                if t.outcome:
                    put(self.stdscr, y, x, edge, attr(C_NEON if on else C_FRAME))
                    put(self.stdscr, y, x + 2, ellipsis("→ " + t.outcome, cw - 7),
                        attr(C_GHOST if on else C_DIM))
                    y += 1
                put(self.stdscr, y, x, edge, attr(C_NEON if on else C_FRAME))
                put(self.stdscr, y, x + 2, ellipsis(self.card_meta(t), cw - 7),
                    attr(C_WARN if not t.defined else C_DIM))
                y += 2

        self.draw_detail(top + list_h, detail_h, w)

    def card_meta(self, t) -> str:
        if not t.defined:
            return "needs " + ", ".join(t.missing)
        bits = [ESTIMATE_LABELS.get(t.estimate, "—")]
        if t.status != "todo" and t.actual_minutes:
            bits.append(f"actual {fmt_minutes(t.actual_minutes)}")
        if t.rolls:
            bits.append(f"rolled {t.rolls}×")
        return " · ".join(bits)

    @staticmethod
    def card_height(t) -> int:
        return 3 + bool(t.outcome)

    def scroll_start(self, items, col_index: int, room: int) -> int:
        if col_index != self.col or not items:
            return 0
        sel, start = min(self.row, len(items) - 1), 0
        while start < sel and sum(
                self.card_height(t) for t in items[start:sel + 1]) > room:
            start += 1
        return start

    def draw_detail(self, top, height, w):
        hline(self.stdscr, top, 2, w - 4, attr(C_DIM))
        t = self.selected()
        if not t:
            put(self.stdscr, top + 1, 2, "c capture · n new", attr(C_DIM))
            return
        paths = db.node_paths(self.conn)
        put(self.stdscr, top + 1, 2, t.title, attr(C_ACCENT, True))
        bits = [paths.get(t.node_id, "—"),
                ESTIMATE_LABELS.get(t.estimate, "—")]
        if t.actual_minutes:
            est = t.estimate_minutes
            ratio = f" {t.actual_minutes / est:.1f}×" if est else ""
            bits.append(f"actual {fmt_minutes(t.actual_minutes)}{ratio}")
        put(self.stdscr, top + 2, 2, " ／ ".join(bits), attr(C_DIM))
        put(self.stdscr, top + 3, 2, f"✓ {t.outcome or '—'}",
            attr(C_DONE if t.outcome else C_WARN))
        put(self.stdscr, top + 4, 2, f"▸ {t.next_action or '—'}",
            attr(C_DOING if t.next_action else C_WARN))

    def draw_calendar(self, top, height, w):
        cur = self.cal_cursor
        first = cur.replace(day=1)
        span = calendar.monthrange(cur.year, cur.month)[1]
        days = [first.replace(day=i).isoformat() for i in range(1, span + 1)]
        counts, logs = db.counts_by_day(self.conn, days), db.logged_days(self.conn)

        put(self.stdscr, top - 1, 2, cur.strftime("%B %Y"), attr(C_HEAD, True))
        for i, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            put(self.stdscr, top, 2 + i * 11, name, attr(C_DIM))

        y = top + 1
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
                cur.year, cur.month):
            for i, d in enumerate(week):
                if d.month != cur.month:
                    continue
                iso = d.isoformat()
                done, total = counts.get(iso, (0, 0))
                cell = f"{d.day:2d}"
                if total:
                    cell += f" {done}/{total}"
                if iso in logs:
                    did, missed = logs[iso]
                    cell += " ✓" if did.lower() not in ("", "nothing") else " ·"
                    if missed:
                        cell += "!"
                a = attr(C_DIM)
                if total and done == total:
                    a = attr(C_DONE)
                elif total:
                    a = attr(C_DOING)
                if iso == today():
                    a |= curses.A_UNDERLINE
                if d == cur:
                    a = attr(C_SEL, True)
                put(self.stdscr, y, 2 + i * 11, cell.ljust(9), a)
            y += 2

        put(self.stdscr, y, 2,
            "✓ did · · nothing · ! missed", attr(C_DIM))
        self.draw_day_answers(y + 2, w)

    def draw_day_answers(self, top, w):
        """The two answers for whatever day the calendar cursor is on."""
        iso = self.cal_cursor.isoformat()
        log = db.day_log(self.conn, iso)
        hline(self.stdscr, top, 2, w - 4, attr(C_DIM))
        put(self.stdscr, top + 1, 2,
            self.cal_cursor.strftime("%A %d %B"), attr(C_ACCENT, True))
        if not log.answered:
            closed = "never answered — that day is closed" \
                if iso < review_day(conn=self.conn) \
                else "not answered yet"
            put(self.stdscr, top + 2, 2, closed, attr(C_DIM))
            return
        for i, (label, text, color) in enumerate(
                [("did", log.did or "—", C_DONE),
                 ("not", log.not_done or "—", C_WARN)]):
            put(self.stdscr, top + 2 + i, 2, f"{label}:", attr(color, True))
            put(self.stdscr, top + 2 + i, 8, ellipsis(text, w - 12), attr(C_DIM))

        # The week that day belongs to, if it was ever reviewed. Three
        # considered answers a week are worth nothing if you can never read
        # them back.
        week = db.week_log(self.conn, iso)
        if week.answered:
            put(self.stdscr, top + 4, 2, f"week of {week.week_start}",
                attr(C_ACCENT, True))
            for i, (label, text) in enumerate(
                    [("moved", week.moved), ("avoided", week.avoided),
                     ("change", week.change)]):
                put(self.stdscr, top + 5 + i, 2, f"{label}:", attr(C_VIOLET))
                put(self.stdscr, top + 5 + i, 12, ellipsis(text or "—", w - 16),
                    attr(C_DIM))

    def draw_inbox(self, top, height, w):
        items = self.inbox()
        put(self.stdscr, top - 1, 2,
            f"INBOX 受信 {len(items):02d}", attr(C_HEAD, True))
        if not items:
            put(self.stdscr, top + 1, 2, "c capture", attr(C_DIM))
            return
        self.list_row = min(self.list_row, len(items) - 1)
        room = max(1, (height - 3) // 2)
        start = max(0, min(self.list_row - room + 1, len(items) - room))
        if start:
            put(self.stdscr, top, 2, f"↑ {start} above", attr(C_DIM))
        y = top + (1 if start else 0)
        paths = db.node_paths(self.conn)
        for i, t in enumerate(items):
            if i < start:
                continue
            if y >= top + height - 2:
                put(self.stdscr, y, 2, f"↓ {len(items) - i} more", attr(C_DIM))
                break
            on = i == self.list_row
            put(self.stdscr, y, 2, ("▸ " if on else "  ") + ellipsis(t.title, w - 30),
                attr(C_SEL, True) if on else attr(C_ACCENT))
            tail = paths.get(t.node_id, "no goal") if t.defined else \
                "needs " + ", ".join(t.missing)
            put(self.stdscr, y + 1, 4, ellipsis(tail, w - 30),
                attr(C_DIM if t.defined else C_WARN))
            age = t.age_days
            if age:
                note = f"captured {age}d ago"
                put(self.stdscr, y + 1, max(4, w - cols(note) - 4), note,
                    attr(C_WARN if age >= 14 else C_DIM))
            y += 2
        put(self.stdscr, top + height - 2, 2,
            "s schedule · e define · x delete", attr(C_DIM))

    def draw_tree(self, top, height, w):
        items = self.visible_nodes()
        t = self.tree
        put(self.stdscr, top - 1, 2,
            f"TREE 系統 {len(t.nodes):02d}", attr(C_HEAD, True))
        if not items:
            put(self.stdscr, top + 1, 2,
                "A root · a child", attr(C_DIM))
            return

        self.list_row = min(self.list_row, len(items) - 1)
        room = height - 3
        start = max(0, min(self.list_row - room + 1, len(items) - room))
        if start:
            put(self.stdscr, top, 2, f"↑ {start} above", attr(C_DIM))
        y = top + (1 if start else 0)

        # One pass over the tasks, then roll the counts up the tree — asking
        # the database twice per visible node turns a full screen into three
        # hundred queries, and a board with a few thousand tasks on it into a
        # noticeable pause on every keystroke.
        counts: dict[str, tuple[int, int]] = {}
        for task in self.read_tasks():
            done, total = counts.get(task.node_id, (0, 0))
            counts[task.node_id] = (done + (task.status == "done"), total + 1)
        subtree_counts: dict[str, tuple[int, int]] = {}

        def roll_up(node_id: str) -> tuple[int, int]:
            done, total = counts.get(node_id, (0, 0))
            for child in t.kids(node_id):
                cd, ct = roll_up(child.id)
                done, total = done + cd, total + ct
            subtree_counts[node_id] = (done, total)
            return done, total

        for root in t.kids(None):
            roll_up(root.id)

        # Indentation is capped, otherwise a deep chain walks off the right
        # edge and the nodes simply stop being drawn. Past the cap the depth
        # is written as a number instead of as whitespace.
        max_indent = max(2, min(24, w // 4))
        for i, (node, depth) in enumerate(items):
            if i < start:
                continue
            if y >= top + height - 2:
                put(self.stdscr, y, 2, f"↓ {len(items) - i} more", attr(C_DIM))
                break
            leaf = t.is_leaf(node.id)
            marker = "  " if leaf else ("▾ " if node.id not in self.collapsed
                                        else "▸ ")
            indent = min(depth * 2, max_indent)
            x = 2 + indent
            if depth * 2 > max_indent:
                put(self.stdscr, y, x - 2, f"{depth}", attr(C_VIOLET))
            on = i == self.list_row
            label = marker + node.name

            own_done, own_total = counts.get(node.id, (0, 0))
            finished, total = subtree_counts.get(node.id, (0, 0))
            tail = f"{total - finished} open · {finished} done"
            if not leaf and total != own_total:
                tail += f" · {total - own_total} below"

            # The name gets whatever the tail leaves, never a fixed guess.
            room = max(8, w - x - cols(tail) - 7)
            put(self.stdscr, y, x, ("▸" if on else " ") + ellipsis(label, room),
                attr(C_SEL, True) if on else
                attr(C_DONE if leaf else C_ACCENT, not leaf))
            put(self.stdscr, y, max(x + room + 2, w - cols(tail) - 4), tail,
                attr(C_DIM))
            y += 1

        put(self.stdscr, top + height - 2, 2,
            "a child · A root · e rename · m move · f scope · x delete",
            attr(C_DIM))

    def draw_review(self, top, height, w):
        put(self.stdscr, top - 1, 2, "REVIEW 反省", attr(C_HEAD, True))
        y = top
        all_tasks = self.read_tasks()         # read once, used by two sections
        # Three sections sharing one screen, any of which can be long: a wide
        # estimate scale, a week of apps, a pile of rotting work. Each is
        # bounded and says what it hid, rather than running into the rail.
        limit = top + height - 3

        # 1. Where the last seven days actually went.
        put(self.stdscr, y, 2, "FOCUS ／ 7 DAYS", attr(C_ACCENT, True))
        y += 1
        span = [add_days(today(), -i) for i in range(6, -1, -1)]   # oldest first
        matrix = db.usage_matrix(self.conn, span)

        col, left = 8, 16
        put(self.stdscr, y, left - 14, "app", attr(C_DIM))
        for i, d in enumerate(span):
            head = date.fromisoformat(d).strftime("%a")
            a = attr(C_ACCENT, True) if d == today() else attr(C_DIM)
            put(self.stdscr, y, left + i * col, head.rjust(col - 1), a)
        put(self.stdscr, y, left + 7 * col + 2, "total".rjust(6), attr(C_DIM))
        y += 1

        if not matrix:
            put(self.stdscr, y, 4, "no data", attr(C_DIM))
            y += 1
        for row in matrix[:max(1, min(5, limit - y - 6))]:
            color = APP_COLOR.get(row["color"], C_DIM)
            bold = row["color"] == "red"
            put(self.stdscr, y, 2, pad(ellipsis(row["label"], 13), 13),
                attr(color, bold))
            for i, d in enumerate(span):
                secs = row["by_day"].get(d, 0)
                cell = fmt_minutes(secs // 60) if secs else "·"
                put(self.stdscr, y, left + i * col, cell.rjust(col - 1),
                    attr(color if secs else C_DIM, bold and secs >= 3600))
            put(self.stdscr, y, left + 7 * col + 2,
                fmt_minutes(row["total"] // 60).rjust(6), attr(color, bold))
            y += 1

        if matrix:
            put(self.stdscr, y, 2, "all".ljust(13), attr(C_DIM))
            for i, d in enumerate(span):
                total = sum(r["by_day"].get(d, 0) for r in matrix)
                put(self.stdscr, y, left + i * col,
                    (fmt_minutes(total // 60) if total else "·").rjust(col - 1),
                    attr(C_DIM))
            grand = sum(r["total"] for r in matrix)
            put(self.stdscr, y, left + 7 * col + 2,
                fmt_minutes(grand // 60).rjust(6), attr(C_DIM))
            y += 1
        y += 1

        # 2. How wrong your estimates are, per size, in your own data.
        accuracy = estimate_accuracy(all_tasks)
        put(self.stdscr, y, 2, "ESTIMATE ／ ACTUAL", attr(C_ACCENT, True))
        y += 1
        if not accuracy:
            put(self.stdscr, y, 4, "nothing timed yet", attr(C_DIM))
            y += 2
        else:
            listed = [k for k in ESTIMATE_KEYS if k in accuracy]
            # Leave at least three rows for whatever needs a decision.
            room = max(1, limit - y - 4)
            hidden = max(0, len(listed) - room)
            for key in listed[:room]:
                n, actual = accuracy[key]
                planned = ESTIMATE_MINUTES[key]
                ratio = actual / planned if planned else 0
                bar = fx.bar(min(ratio, 3.0), 3.0, 18)
                color = (C_DONE if 0.8 <= ratio <= 1.25 else
                         C_WARN if ratio > 1.75 else C_DOING)
                put(self.stdscr, y, 4,
                    f"{ESTIMATE_LABELS[key]:<9} → {fmt_minutes(round(actual)):>6}"
                    f"  {ratio:>4.1f}×  ", attr(color))
                put(self.stdscr, y, 32, bar, attr(color))
                put(self.stdscr, y, 52, f"n={n}", attr(C_DIM))
                y += 1
            if hidden:
                put(self.stdscr, y, 4,
                    f"… {hidden} more size{'' if hidden == 1 else 's'} — "
                    f"space-cli estimates shows them all", attr(C_DIM))
                y += 1
            y += 1

        # 3. What has stopped being work.
        rotting = self.stale(all_tasks)
        if y >= limit:
            return                         # no room left; the sections above won
        put(self.stdscr, y, 2, f"ROTTING {len(rotting):02d}", attr(C_ACCENT, True))
        y += 1
        if not rotting:
            put(self.stdscr, y, 4, "clear", attr(C_DONE))
            return
        self.list_row = min(self.list_row, len(rotting) - 1)
        for i, (t, why) in enumerate(rotting):
            if y >= limit:
                put(self.stdscr, y, 4, f"↓ {len(rotting) - i} more", attr(C_DIM))
                break
            on = i == self.list_row
            put(self.stdscr, y, 4, ("▸ " if on else "  ") + ellipsis(t.title, w - 30),
                attr(C_SEL, True) if on else attr(C_DIM))
            put(self.stdscr, y, max(4, w - len(why) - 4), why, attr(C_WARN))
            y += 1
        put(self.stdscr, top + height - 2, 2,
            "x kill · S inbox · X kill all · I inbox all", attr(C_DIM))

    DAEMONS = [("ASK", "review-reminder.sh"), ("REPO", "repo-watch.sh")]

    def daemons(self) -> dict[str, bool]:
        """Which background pieces are running, cached for half a minute.

        Read straight out of /proc rather than shelling out to pgrep: the
        board redraws several times a second while anything is animating, and
        a subprocess per frame to answer a question that changes hourly is a
        poor trade.
        """
        now = time.monotonic()
        if now - getattr(self, "_daemon_checked", -99) < 30:
            return self._daemon_state
        found = {name: False for name, _ in self.DAEMONS}
        mine = str(os.getpid())
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit() or entry == mine:
                    continue                 # never count ourselves as a daemon
                try:
                    with open(f"/proc/{entry}/cmdline", "rb") as handle:
                        argv = handle.read().decode("utf-8", "replace").split("\0")
                except OSError:
                    continue
                # The script has to BE an argument, not merely be mentioned in
                # one: a shell running a command that names it is not it.
                names = {arg.rsplit("/", 1)[-1] for arg in argv if arg}
                for name, needle in self.DAEMONS:
                    if needle in names:
                        found[name] = True
        except OSError:
            pass
        self._daemon_checked, self._daemon_state = now, found
        return found

    def status_rail(self, h, w):
        """The bottom rail: is anything actually recording, and what time is it.

        All three background pieces, not just the tracker. Silence from any of
        them is indistinguishable from calm, which is exactly how the tracker
        once went an hour without recording anything.
        """
        age = db.last_beat(self.conn)
        if age is None:
            track, color = "TRK OFF", C_WARN
        elif age < 180:
            track, color = "TRK", C_DONE
        else:
            track, color = f"TRK {int(age // 60)}m", C_DOING

        put(self.stdscr, h - 3, 1, "◣", attr(C_NEON))
        x = 3
        put(self.stdscr, h - 3, x, "▰" if color is C_DONE else "▱", attr(color))
        put(self.stdscr, h - 3, x + 2, track, attr(color))
        x += 3 + cols(track)

        for name, running in self.daemons().items():
            tint = C_DONE if running else C_WARN
            put(self.stdscr, h - 3, x, "▰" if running else "▱", attr(tint))
            put(self.stdscr, h - 3, x + 2, name if running else f"{name} OFF",
                attr(tint))
            x += 3 + cols(name) + (0 if running else 4)

        stamp = time.strftime("%H:%M:%S")
        if w - len(stamp) - 4 > x + 3:
            put(self.stdscr, h - 3, x + 1, "─" * (w - len(stamp) - x - 6),
                attr(C_FRAME))
            put(self.stdscr, h - 3, w - len(stamp) - 4, stamp, attr(C_ACCENT))
        put(self.stdscr, h - 3, w - 2, "◢", attr(C_NEON))

    # Longest first; the footer takes the first one that fits.
    KEY_HINTS = [
        "c capture · e define · space advance · < > move day · w answer · ? help · q quit",
        "c capture · e define · space advance · < > move · w answer · ? help · q quit",
        "c capture · e define · space advance · w answer · ? help · q quit",
        "c capture · e define · space advance · ? help",
        "c · e · space · ? help",
        "? help",
    ]

    def draw_footer(self, h, w):
        self.status_rail(h, w)
        if self.message:
            fresh = time.monotonic() - self.message_at < 1.2
            put(self.stdscr, h - 2, 2, ("▸ " if fresh else "  ")
                + ellipsis(self.message, w - 6),
                attr(C_NEON if fresh else C_DIM, fresh))
        hint = next((k for k in self.KEY_HINTS if len(k) <= w - 4),
                    self.KEY_HINTS[-1])
        put(self.stdscr, h - 1, 2, hint, attr(C_DIM))

    # --- actions ------------------------------------------------------------

    @staticmethod
    def capture_react(value: str):
        """Live note under the capture field."""
        n = len(value.strip())
        if not n:
            return "anything at all — you define it later, not now", C_DIM
        if n < 12:
            return "a little more and you'll know what it meant tomorrow", C_VIOLET
        return f"{n} characters · enter drops it in the inbox", C_DONE

    def goto_day(self) -> None:
        """Jump straight to a date. Stepping there one day at a time is fine
        for tomorrow and useless for last month."""
        def react(value: str):
            text = value.strip()
            if not text:
                return "YYYY-MM-DD, or +3 / -7 for days from today", C_DIM
            parsed = self.parse_day(text)
            if not parsed:
                return "not a date I can read", C_WARN
            n = len(db.tasks(self.conn, day=parsed))
            weekday = date.fromisoformat(parsed).strftime("%A")
            return f"{weekday} {parsed} · {n} task{'' if n == 1 else 's'}", C_DONE

        got = prompt(self.stdscr, "go to", react=react)
        if got is None:
            return
        parsed = self.parse_day(got.strip())
        self.message_at = time.monotonic()
        if not parsed:
            self.message = f"“{got.strip()}” is not a date"
            return
        self.day, self.row = parsed, 0
        self.cal_cursor = date.fromisoformat(parsed)
        self.message = f"jumped to {parsed}"

    @staticmethod
    def parse_day(text: str) -> str | None:
        """A date, or an offset in days from today: +3, -7, 0."""
        text = text.strip()
        if not text:
            return None
        if text[0] in "+-" or text.isdigit():
            try:
                return add_days(today(), int(text))
            except ValueError:
                return None
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None

    def filter_react(self, value: str):
        """Count the matches while you type, so you know before you commit."""
        needle = value.strip().lower()
        if not needle:
            return "empty clears the filter", C_DIM
        saved, self.filter = self.filter, needle
        try:
            hits = len(self.keep(db.tasks(self.conn))) + len(
                [n for n in db.nodes(self.conn) if self.matches(n.name)])
        finally:
            self.filter = saved
        return (f"{hits} match{'' if hits == 1 else 'es'}",
                C_DONE if hits else C_WARN)

    def capture(self):
        """One line, no fields, from anywhere. Lands in the inbox."""
        text = prompt(self.stdscr, "capture", react=self.capture_react)
        if text and text.strip():
            db.capture(self.conn, text)
            self.message_at = time.monotonic()
            self.message = "captured to inbox"

    def register_estimate(self, key: str | None) -> None:
        """A length typed into the form joins the scale.

        Otherwise a one-off "1h45" would have no minutes behind it, and the
        accuracy table could never say anything about it.
        """
        if not key or key in ESTIMATE_MINUTES:
            return
        minutes = parse_duration(key)
        if minutes:
            db.add_estimate(self.conn, key, key, minutes)

    def estimate_hint(self, value: str) -> str:
        """What the size under the cursor has actually cost you before."""
        if not value:
            return "← → to pick, or type a length — 45m, 1h30, 2d"
        learned = estimate_hint(estimate_accuracy(db.tasks(self.conn)), value)
        if learned:
            return learned
        label = ESTIMATE_LABELS.get(value, value)
        if value not in ESTIMATE_LABELS:
            # A size this task still carries after it left the scale. Saying so
            # is better than a bare label, and far better than the KeyError
            # this used to be.
            return f"{label} is no longer in the scale — kept for this task"
        return f"no finished {label} tasks yet to compare against"

    def task_form(self, task=None, day=None):
        choices = self.node_choices()
        if not choices:
            self.message_at = time.monotonic()
            self.message = "build the tree first (press 4, then A) — a task needs a goal"
            return
        fields = [
            Field("title", "Title", required=True, value=task.title if task else ""),
            Field("node_id", "Goal", "choice", required=True, choices=choices,
                  value=(task.node_id if task else None) or choices[0][0],
                  hint="← → walks the tree; any node works, leaf or branch"),
            Field("outcome", "Done when", required=True,
                  value=(task.outcome if task else "") or "",
                  hint="how you'll know it's finished"),
            estimate_field((task.estimate if task else "") or "",
                           hint=self.estimate_hint,
                           keep=task.estimate if task else None),
            Field("next_action", "Next action", required=True,
                  value=(task.next_action if task else "") or "",
                  hint="the first physical step, small enough to start now"),
        ]

        def validate(v):
            return [f"{k} is required" for k, name in (
                ("title", "title"), ("node_id", "goal"), ("outcome", "outcome"),
                ("estimate", "estimate"),
                ("next_action", "next action")) if not str(v[k]).strip()]

        vals = run_form(self.stdscr, "Define task" if task else "New task",
                        fields, validate)
        if vals is None:
            return
        self.register_estimate(vals.get("estimate"))
        if task:
            db.update_task(self.conn, task.id, **vals)
            self.message_at = time.monotonic()
            self.message = "defined"
        else:
            db.capture(self.conn, day=day if day is not None else self.day, **vals)
            self.message_at = time.monotonic()
            self.message = "added"
        if vals["estimate"] in ("half_day", "day_plus"):
            self.message += " — that's bigger than half a day; consider splitting it"

    def answer_day(self):
        """The day's two questions. Only the open day is writable — a day locks at
        midnight, because a journal you can backfill records what you wish had
        happened rather than what did."""
        # The question always belongs to the open day, whatever day the board
        # happens to be showing. Telling someone that tomorrow "is closed"
        # because they were looking at it is nonsense.
        day = review_day(conn=self.conn)
        looking_elsewhere = self.day != day
        log = db.day_log(self.conn, day)
        answers = {}
        for key, question, _hint in questions_for(day):
            existing = log.did if key == "did" else log.not_done

            def react(value, key=key):
                v = value.strip().lower()
                if not v:
                    return ("blank is not an answer — write \"nothing\" if that's true"
                            if key == "did" else
                            "blank means there was nothing you missed"), C_DIM
                if v in ("nothing", "none", "-"):
                    return "recorded as a real answer, and it will show", C_WARN
                return ("that is what the day was for" if key == "did"
                        else "written down is better than carried"), C_DONE

            got = prompt(self.stdscr, question.lower(), existing, react=react)
            if got is None:
                self.message_at = time.monotonic()
                self.message = "left unanswered"
                return
            answers[key] = got
        db.log_day(self.conn, day, answers["did"] or "nothing", answers["missed"])
        self.message_at = time.monotonic()
        self.message = f"logged for {day}" if looking_elsewhere else "logged"

    def advance(self, t):
        nxt = STATUS_KEYS[(STATUS_KEYS.index(t.status) + 1) % 3]
        if nxt == "doing":
            blockers = can_start(t)
            if blockers:
                self.message_at = time.monotonic()
                self.message = "can't start: " + ", ".join(blockers) + " — press e"
                return
        db.set_status(self.conn, t.id, nxt)
        self.message_at = time.monotonic()
        self.message = f"{ellipsis(t.title, 30)} → {STATUS_LABELS[nxt]}"
        if nxt == "done":
            self.celebrate(t)

    def celebrate(self, task) -> None:
        """A wave of light across the footer for whatever just got finished."""
        h, _ = self.stdscr.getmaxyx()
        fx.sweep(self.stdscr, h - 3, 2,
                 "✓ DONE  " + ellipsis(task.title, 44),
                 attr(C_DIM), attr(C_NEON, True))

    def show_help(self):
        """Keys, and what the board is for. Fits itself to the screen."""
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        put(self.stdscr, 1, 2, "Keys", attr(C_HEAD, True))

        # Everything below has to fit: the last row is reserved for the way
        # out, and anything that doesn't fit is dropped deliberately rather
        # than written past the edge and silently lost.
        room = h - 5
        shown = HELP[:max(1, room)]
        for i, (k, what) in enumerate(shown):
            put(self.stdscr, 3 + i, 4, k.ljust(12), attr(C_ACCENT))
            put(self.stdscr, 3 + i, 18, ellipsis(what, w - 22), attr(C_DIM))
        y = 3 + len(shown)
        if len(shown) < len(HELP):
            rest = len(HELP) - len(shown)
            put(self.stdscr, y, 4,
                f"… {rest} more key{'' if rest == 1 else 's'} — "
                f"a taller window shows them all", attr(C_DIM))
            y += 1

        prose = [
            "The tree is permanent: a leaf is a goal, a branch an area, nothing closes.",
            "Capture is free; a task only has to be defined before you start it.",
            "Unfinished work rolls to today — Review shows what keeps rolling.",
            "Ship = someone else could notice. Support = only helps you ship later.",
            "Time counts while a task sits in Doing, against your estimate.",
            "space-track records how long watched apps hold focus.",
        ]
        if h - y > 4:
            put(self.stdscr, y + 1, 2, "How it works", attr(C_HEAD, True))
            for i, line in enumerate(prose[:h - y - 4]):
                put(self.stdscr, y + 3 + i, 4, ellipsis(line, w - 8), attr(C_DIM))

        put(self.stdscr, h - 1, 2, "any key to go back", attr(C_DIM))
        self.stdscr.refresh()
        self.stdscr.timeout(-1)
        while self.stdscr.getch() in (-1, curses.KEY_RESIZE):
            pass

    # --- input --------------------------------------------------------------

    def switch(self, view: str) -> None:
        if view != self.view and fx.fx_enabled():
            self.glitch_until = time.monotonic() + 0.22
        self.view, self.list_row = view, 0

    def alive(self) -> bool:
        """Is anything on screen worth animating? Otherwise we block on input.

        Kept cheap and kept honest: an idle board must return False, or it
        spins at the frame rate forever for no reason.
        """
        now = time.monotonic()
        if now < self.glitch_until or now - self.message_at < 2.0:
            return True
        if not db.day_log(self.conn, review_day(conn=self.conn)).answered:
            return True
        if db.tasks(self.conn, day=self.day, status="doing"):
            return True                    # a running clock has to actually run
        return db.usage_total(self.conn, self.day, color="red") >= 3600

    def handle(self, ch) -> bool:
        self.message = ""
        if ch in (ord("q"), ord("Q")):
            return False
        if ch == ord("?"):
            self.show_help()
            return True
        if ch == ord("c"):
            self.capture()
            return True
        if ch == ord("n") and self.view not in ("today",):
            # The form is not a property of one view; opening it anywhere and
            # having nothing happen is just a key that appears to be broken.
            self.task_form()
            return True
        if ch == ord("F") and self.node_filter:
            self.node_filter = None
            self.message_at = time.monotonic()
            self.message = "showing everything again"
            return True
        if ch == ord("/"):
            found = prompt(self.stdscr, "filter", self.filter,
                           react=self.filter_react)
            if found is not None:
                self.filter = found.strip().lower()
                self.list_row = self.row = 0
                self.message_at = time.monotonic()
                self.message = (f"filtering on “{self.filter}” — / then enter "
                                f"to clear") if self.filter else "filter cleared"
            return True
        if ch == 9:
            i = [k for k, _ in VIEWS].index(self.view)
            self.switch(VIEWS[(i + 1) % len(VIEWS)][0])
            return True
        if ord("1") <= ch <= ord("5"):
            self.switch(VIEWS[ch - ord("1")][0])
            return True
        if ch in (ord("a"), ord("A")) and self.view != "tree":
            self.view, self.list_row = "tree", 0
            self.message_at = time.monotonic()
            self.message = "pick where it goes: a adds a child, A adds a root"
            return True
        if ch == ord("w"):
            self.answer_day()
            return True
        if ch == ord("W"):
            if not self.ask_weekly():
                if not self.message:
                    self.message_at = time.monotonic()
                    self.message = "no weekly review is owed"
            return True
        if ch == ord("t"):
            self.day = today()
            self.cal_cursor = date.fromisoformat(self.day)
            return True
        if ch == ord("g"):
            self.goto_day()
            return True

        return {"today": self.handle_day, "calendar": self.handle_calendar,
                "inbox": self.handle_inbox, "tree": self.handle_tree,
                "review": self.handle_review}[self.view](ch)

    def handle_day(self, ch):
        items = self.columns()[STATUS_KEYS[self.col]]
        t = self.selected()
        if ch in (ord("j"), curses.KEY_DOWN):
            self.row = min(self.row + 1, max(0, len(items) - 1))
        elif ch in (ord("k"), curses.KEY_UP):
            self.row = max(0, self.row - 1)
        elif ch in (ord("l"), curses.KEY_RIGHT):
            self.col, self.row = min(self.col + 1, 2), 0
        elif ch in (ord("h"), curses.KEY_LEFT):
            self.col, self.row = max(self.col - 1, 0), 0
        elif ch == ord("J") and t:
            db.reorder(self.conn, t.id, 1)
            self.row += 1
        elif ch == ord("K") and t:
            db.reorder(self.conn, t.id, -1)
            self.row = max(0, self.row - 1)
        elif ch == ord(" ") and t:
            self.advance(t)
        elif ch == ord("n"):
            self.task_form()
        elif ch in (ord("e"), curses.KEY_ENTER, 10, 13) and t:
            self.task_form(t)
        elif ch in (ord(">"), ord("<")) and t and t.day:
            # Move the task, not the view. [ and ] walk the days; < and >
            # carry the selected card with you.
            moved = add_days(t.day, 1 if ch == ord(">") else -1)
            db.schedule(self.conn, t.id, moved)
            self.message_at = time.monotonic()
            self.message = f"{ellipsis(t.title, 30)} → {moved}"
        elif ch == ord("S") and t:
            db.schedule(self.conn, t.id, None)
            self.message_at = time.monotonic()
            self.message = "sent back to the inbox"
        elif ch == ord("x") and t:
            if confirm(self.stdscr, f"delete '{ellipsis(t.title, 40)}'?"):
                db.delete(self.conn, "tasks", t.id)
        elif ch == ord("["):
            self.day, self.row = add_days(self.day, -1), 0
        elif ch == ord("]"):
            self.day, self.row = add_days(self.day, 1), 0
        return True

    def handle_calendar(self, ch):
        step = {ord("h"): -1, curses.KEY_LEFT: -1, ord("l"): 1, curses.KEY_RIGHT: 1,
                ord("j"): 7, curses.KEY_DOWN: 7, ord("k"): -7, curses.KEY_UP: -7,
                ord("["): -1, ord("]"): 1}.get(ch)
        if step:
            self.cal_cursor = date.fromisoformat(
                add_days(self.cal_cursor.isoformat(), step))
        elif ch in (curses.KEY_ENTER, 10, 13, ord(" ")):
            self.day, self.view, self.row = self.cal_cursor.isoformat(), "today", 0
        return True

    def handle_inbox(self, ch):
        items = self.inbox()
        t = self.selected_inbox()
        if ch in (ord("j"), curses.KEY_DOWN):
            self.list_row = min(self.list_row + 1, max(0, len(items) - 1))
        elif ch in (ord("k"), curses.KEY_UP):
            self.list_row = max(0, self.list_row - 1)
        elif ch in (ord("e"), curses.KEY_ENTER, 10, 13) and t:
            self.task_form(t)
        elif ch == ord("s") and t:
            if can_start(t):
                # Scheduling something undefined is the moment you have to
                # define it anyway, so do that here instead of bouncing the
                # user to another key and back.
                self.task_form(t)
                t = db.task(self.conn, t.id)
            if t and not can_start(t):
                db.schedule(self.conn, t.id, self.day)
                self.message_at = time.monotonic()
                self.message = f"scheduled for {self.day}"
            else:
                self.message_at = time.monotonic()
                self.message = "still not defined — it stays in the inbox"
        elif ch == ord("x") and t:
            if confirm(self.stdscr, f"delete '{ellipsis(t.title, 40)}'?"):
                db.delete(self.conn, "tasks", t.id)
        return True

    def handle_tree(self, ch):
        items = self.visible_nodes()
        node = self.selected_node()
        t = self.tree

        if ch in (ord("j"), curses.KEY_DOWN):
            self.list_row = min(self.list_row + 1, max(0, len(items) - 1))
        elif ch in (ord("k"), curses.KEY_UP):
            self.list_row = max(0, self.list_row - 1)
        elif ch in (ord("l"), curses.KEY_RIGHT) and node:
            self.collapsed.discard(node.id)
        elif ch in (ord("h"), curses.KEY_LEFT) and node:
            if t.is_leaf(node.id) or node.id in self.collapsed:
                # Already folded (or nothing to fold): step out to the parent.
                parent = node.parent_id
                if parent:
                    self.list_row = next(
                        (i for i, (n, _) in enumerate(items) if n.id == parent),
                        self.list_row)
            else:
                self.collapsed.add(node.id)
        elif ch == ord("A"):
            name = prompt(self.stdscr, "new root:")
            if name and name.strip():
                db.add_node(self.conn, name)
                self.message_at = time.monotonic()
                self.message = f"'{name.strip()}' added as a root"
        elif ch == ord("a") and node:
            name = prompt(self.stdscr, f"child of {node.name}:")
            if name and name.strip():
                db.add_node(self.conn, name, node.id)
                self.collapsed.discard(node.id)
                self.message_at = time.monotonic()
                self.message = f"'{name.strip()}' added under {node.name}"
        elif ch in (ord("e"), curses.KEY_ENTER, 10, 13) and node:
            name = prompt(self.stdscr, "rename:", node.name)
            if name and name.strip():
                db.rename_node(self.conn, node.id, name)
        elif ch == ord("f") and node:
            # Scope the whole board to this branch. A tree that knows your
            # structure but cannot filter by it is only a picture of it.
            if self.node_filter == node.id:
                self.node_filter = None
                self.message_at = time.monotonic()
                self.message = "showing everything again"
            else:
                self.node_filter = node.id
                self.view, self.row = "today", 0
                self.message_at = time.monotonic()
                self.message = (f"scoped to {t.path(node.id)} — "
                                f"f again on it, or F anywhere, to clear")
        elif ch == ord("m") and node:
            self.move_node(node)
        elif ch == ord("x") and node:
            sub = t.descendants(node.id)
            affected = db.subtree_tasks(self.conn, node.id)
            what = f"delete '{node.name}'?"
            if sub:
                what += f" {len(sub)} node(s) below go too"
            if affected:
                what += f"; {len(affected)} task(s) lose their goal"
            if confirm(self.stdscr, what):
                db.delete(self.conn, "nodes", node.id)
                self.list_row = max(0, self.list_row - 1)
        return True

    def move_node(self, node):
        """Reparent, choosing the new parent from the rest of the tree."""
        t = self.tree
        banned = {node.id} | {d.id for d in t.descendants(node.id)}
        options = [("", "— top level —")] + [
            (n.id, "  " * depth + n.name)
            for n, depth in t.walk() if n.id not in banned]
        if len(options) == 1 and not node.parent_id:
            self.message_at = time.monotonic()
            self.message = "nowhere to move it — it's already a root"
            return
        vals = run_form(self.stdscr, f"Move '{node.name}'",
                        [Field("parent", "New parent", "choice",
                               choices=options, value=node.parent_id or "",
                               hint="← → to pick, then Ctrl-S")])
        if vals is None:
            return
        err = db.move_node(self.conn, node.id, vals["parent"] or None)
        self.message_at = time.monotonic()
        self.message = err or f"moved under {t.path(vals['parent']) or 'top level'}"

    def handle_review(self, ch):
        rotting = self.stale()
        pick = rotting[self.list_row][0] if rotting and \
            self.list_row < len(rotting) else None
        if ch in (ord("j"), curses.KEY_DOWN):
            self.list_row = min(self.list_row + 1, max(0, len(rotting) - 1))
        elif ch in (ord("k"), curses.KEY_UP):
            self.list_row = max(0, self.list_row - 1)
        elif ch == ord("x") and pick:
            if confirm(self.stdscr, f"kill '{ellipsis(pick.title, 40)}'?"):
                db.delete(self.conn, "tasks", pick.id)
        elif ch == ord("S") and pick:
            db.update_task(self.conn, pick.id, day=None, rolls=0)
            self.message_at = time.monotonic()
            self.message = "back to the inbox, roll count reset"
        elif ch in (ord("X"), ord("I")) and rotting:
            # Triage in one go. A list of forty things you have been pushing
            # forward for a month is not a list you clear one keystroke at a
            # time, and leaving it uncleared is how the view stops being read.
            kill = ch == ord("X")
            what = "kill" if kill else "send back to the inbox"
            if confirm(self.stdscr, f"{what} all {len(rotting)}?"):
                for task, _ in rotting:
                    if kill:
                        db.delete(self.conn, "tasks", task.id)
                    else:
                        db.update_task(self.conn, task.id, day=None, rolls=0)
                self.list_row = 0
                self.message_at = time.monotonic()
                self.message = (f"{len(rotting)} killed" if kill
                                else f"{len(rotting)} back in the inbox")
        return True

    def locked_out(self) -> bool:
        """Hold the board shut until the day's question is answered.

        Only while a question is actually due — between midnight and the
        four o'clock close. A board that demanded an answer about a day you
        are still living would just teach you to type anything to get in.
        Returns False if the user chose to quit instead.
        """
        while True:
            day = owed(self.conn)
            if not day:
                return True

            h, w = self.stdscr.getmaxyx()
            self.stdscr.erase()
            width = max(24, min(w - 4, 76))

            items = db.tasks(self.conn, day=day)
            finished, total = done_count(items)
            red = db.usage_total(self.conn, day, color="red") // 60
            when = date.fromisoformat(day).strftime("%A %d %B")

            # In priority order. Being locked out of the board with no visible
            # way to answer is the worst thing this screen can do, so the way
            # out is drawn first and everything else fills the room left.
            essential = [(f"{when} is waiting for its answer.", C_GHOST, True)]
            optional = [
                ("", C_DIM, False),
                (f"you finished {finished} of {total}", C_DIM, False),
                (f"distraction {fmt_minutes(red)}",
                 C_WARN if red else C_DIM, False),
                ("", C_DIM, False),
                ("Two questions, about a minute.", C_VIOLET, False),
                ("It closes at midnight tonight, answered or not.", C_VIOLET, False),
            ]
            # Longest that fits. This line is the only thing on screen that
            # has to survive, so it gets its own ladder.
            exit_line = next(
                (t for t in ("any key to answer · q to quit",
                             "any key answers · q quits",
                             "any key · q quits",
                             "q quits")
                 if cols(t) <= width - 6), "q quits")

            room = max(0, h - 6)                     # frame, padding, way out
            body = essential + optional[:max(0, room - len(essential))]
            height = min(h - 1, len(body) + 5)
            top = max(0, (h - height) // 2)
            left = max(0, (w - width) // 2)

            frame(self.stdscr, top, left, height, width, "LOCKED 施錠",
                  C_WARN, C_WARN)
            for i, (text, color, bold) in enumerate(body):
                if text:
                    put(self.stdscr, top + 2 + i, left + 3,
                        ellipsis(text, width - 6), attr(color, bold))
            put(self.stdscr, top + height - 2, left + 3,
                ellipsis(exit_line, width - 6), attr(C_DIM))
            self.stdscr.refresh()

            self.stdscr.timeout(-1)
            ch = self.stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                return False

            log = db.day_log(self.conn, day)
            answers = {}
            for key, question, _hint in questions_for(day):
                existing = log.did if key == "did" else log.not_done
                got = prompt(self.stdscr, question.lower(), existing,
                             react=self.answer_react(key))
                if got is None:
                    break                  # backed out; the panel comes back
                answers[key] = got
            if "did" in answers:
                db.log_day(self.conn, day, answers["did"] or "nothing",
                           answers.get("missed", ""))
                self.ask_weekly()          # a Sunday owes three more

    def ask_weekly(self) -> bool:
        """The three Sunday questions, if the week is still owed.

        Reachable from the board because the reminder asks about it: being
        told something is outstanding by a thing that cannot then help you
        answer it is worse than never being told.
        """
        week_day = weekly_owed(self.conn)
        if not week_day:
            return False
        existing = db.week_log(self.conn, week_day)
        rolling = [t.title for t in db.tasks(self.conn)
                   if t.status != "done" and t.rolls >= NAGGING_ROLLS]
        answers = {}
        for key, question, hint in WEEKLY:
            def react(value, key=key, hint=hint):
                if key == "avoided" and not value.strip() and rolling:
                    return f"you kept pushing: {ellipsis(', '.join(rolling), 46)}", C_WARN
                return (hint, C_DIM) if not value.strip() else \
                    ("that is the week, then", C_DONE)
            got = prompt(self.stdscr, question.lower(),
                         getattr(existing, key) or "", react=react)
            if got is None:
                self.message_at = time.monotonic()
                self.message = "the week is still open — press W"
                return False
            answers[key] = got
        db.log_week(self.conn, week_day, answers["moved"], answers["avoided"],
                    answers["change"])
        self.message_at = time.monotonic()
        self.message = f"week of {db.week_start(week_day)} logged"
        return True

    @staticmethod
    def answer_react(key: str):
        def react(value: str):
            v = value.strip().lower()
            if not v:
                return ("blank is not an answer — write \"nothing\" if that's true"
                        if key == "did" else
                        "blank means there was nothing you missed"), C_DIM
            if v in ("nothing", "none", "-"):
                return "recorded as a real answer, and it will show", C_WARN
            return ("that is what the day was for" if key == "did"
                    else "written down is better than carried"), C_DONE
        return react

    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        if not self.locked_out():
            return
        while True:
            self.draw()
            # Only spin when something on screen is moving; otherwise block,
            # so an idle board costs nothing at all.
            self.stdscr.timeout(180 if self.alive() else -1)
            ch = self.stdscr.getch()
            if ch in (-1, curses.KEY_RESIZE):
                continue
            if not self.handle(ch):
                return


def main(stdscr):
    init_colors()
    disable_flow_control()
    curses.curs_set(0)
    fx.boot(stdscr, "a board that knows what the day cost")
    App(stdscr, db.connect()).run()


def run():
    curses.wrapper(main)
