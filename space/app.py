"""Five views over the local database."""

from __future__ import annotations

import calendar
import curses
import random
from datetime import date

from . import db
from .model import (
    KIND_LABELS, NAGGING_ROLLS, STALE_DAYS, STATUS_KEYS, STATUS_LABELS,
    ESTIMATE_LABELS, GREETINGS, add_days, can_start, fmt_minutes, ship_ratio,
    today,
)
from .ui import (
    C_ACCENT, C_DIM, C_DOING, C_DONE, C_HEAD, C_SEL, C_WARN, Field, attr,
    confirm, disable_flow_control, ellipsis, estimate_field, hline,
    init_colors, kind_field, prompt, put, run_form, wrap,
)

VIEWS = [("today", "Today"), ("calendar", "Calendar"), ("inbox", "Inbox"),
         ("areas", "Areas"), ("review", "Review")]

STATUS_COLOR = {"todo": C_DIM, "doing": C_DOING, "done": C_DONE}

HELP = [
    ("1-5 / Tab", "switch view"),
    ("c", "capture — one line, no fields, from any view"),
    ("j k / h l", "move · J K reorder"),
    ("space", "advance status — refuses to start an undefined task"),
    ("e / Enter", "define or edit"),
    ("s / S", "schedule onto the open day / send back to inbox"),
    ("w", "log what shipped today"),
    ("a", "new area · x delete"),
    ("[ ] t", "previous day / next day / today"),
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
        self.list_row = 0            # inbox / areas / review cursor
        self.message = ""
        self.greeting = random.choice(GREETINGS)
        self.cal_cursor = date.fromisoformat(self.day)
        rolled = db.roll_forward(conn)
        db.close_out(conn, today())
        if rolled:
            self.message = f"{rolled} unfinished task(s) rolled forward to today"

    # --- data ---------------------------------------------------------------

    @property
    def areas(self):
        return db.areas(self.conn)

    def area_choices(self):
        return [(a.id, a.name) for a in self.areas]

    def columns(self):
        items = db.tasks(self.conn, day=self.day)
        return {s: [t for t in items if t.status == s] for s in STATUS_KEYS}

    def selected(self):
        items = self.columns()[STATUS_KEYS[self.col]]
        if not items:
            return None
        self.row = min(self.row, len(items) - 1)
        return items[self.row]

    def inbox(self):
        return db.tasks(self.conn, inbox=True)

    def selected_inbox(self):
        items = self.inbox()
        if not items:
            return None
        self.list_row = min(self.list_row, len(items) - 1)
        return items[self.list_row]

    def stale(self):
        """Work that has stopped being work: untouched, or endlessly rolled."""
        out = []
        for t in db.tasks(self.conn):
            if t.status == "done":
                continue
            if t.rolls >= NAGGING_ROLLS:
                out.append((t, f"rolled {t.rolls}×"))
            elif t.stale_days() >= STALE_DAYS:
                out.append((t, f"untouched {t.stale_days()}d"))
        return out

    # --- drawing ------------------------------------------------------------

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        self.draw_header(w)
        body = h - 4
        {"today": self.draw_day, "calendar": self.draw_calendar,
         "inbox": self.draw_inbox, "areas": self.draw_areas,
         "review": self.draw_review}[self.view](3, body, w)
        self.draw_footer(h, w)
        self.stdscr.refresh()

    def draw_header(self, w):
        put(self.stdscr, 0, 2, "kiarez space", attr(C_ACCENT, True))
        put(self.stdscr, 0, 16, self.greeting, attr(C_DIM))
        x = w - 2
        for key, label in reversed(VIEWS):
            chip = f" {label} "
            x -= len(chip) + 1
            put(self.stdscr, 0, x, chip,
                attr(C_SEL, True) if key == self.view else attr(C_DIM))
        hline(self.stdscr, 1, 2, w - 4, attr(C_DIM))

    def day_strip(self, y, w):
        """The line that says whether this day was real."""
        items = db.tasks(self.conn, day=self.day)
        shipped, done = ship_ratio(items)
        distraction = db.usage_total(self.conn, self.day) // 60
        log = db.day_log(self.conn, self.day)

        d = date.fromisoformat(self.day)
        label = "  today" if self.day == today() else ""
        put(self.stdscr, y, 2, d.strftime("%a %d %b %Y") + label, attr(C_HEAD, True))

        bits = [(f"ship {shipped}/{done}", C_DONE if shipped else C_DIM),
                (f"distraction {fmt_minutes(distraction)}",
                 C_WARN if distraction >= 60 else C_DIM)]
        x = 34
        for text, color in bits:
            put(self.stdscr, y, x, text, attr(color))
            x += len(text) + 4
        if log.shipped:
            put(self.stdscr, y, x, f"shipped: {ellipsis(log.shipped, w - x - 4)}",
                attr(C_DONE))
        elif self.day <= today():
            put(self.stdscr, y, x, "nothing logged — press w", attr(C_DIM))

    def draw_day(self, top, height, w):
        self.day_strip(top - 1, w)
        cols = self.columns()
        detail_h, cw = 7, max(18, (w - 6) // 3)
        list_h = height - detail_h - 1

        for ci, status in enumerate(STATUS_KEYS):
            x, items = 2 + ci * cw, cols[STATUS_KEYS[ci]]
            put(self.stdscr, top, x, f"{STATUS_LABELS[status]} ({len(items)})",
                attr(STATUS_COLOR[status], ci == self.col))
            hline(self.stdscr, top + 1, x, cw - 2,
                  attr(C_ACCENT if ci == self.col else C_DIM))
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
                put(self.stdscr, y, x, ("▸ " if on else "  ") + ellipsis(t.title, cw - 5),
                    attr(C_SEL, True) if on else attr(STATUS_COLOR[status]))
                y += 1
                if t.outcome:
                    put(self.stdscr, y, x + 2, ellipsis("✓ " + t.outcome, cw - 6),
                        attr(C_DIM))
                    y += 1
                put(self.stdscr, y, x + 2, ellipsis(self.card_meta(t), cw - 6),
                    attr(C_WARN if not t.defined else C_DIM))
                y += 2

        self.draw_detail(top + list_h, detail_h, w)

    def card_meta(self, t) -> str:
        if not t.defined:
            return "needs " + ", ".join(t.missing)
        bits = [KIND_LABELS[t.kind], ESTIMATE_LABELS[t.estimate]]
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
            put(self.stdscr, top + 1, 2,
                "nothing here — c captures a line, n opens the form", attr(C_DIM))
            return
        names = db.area_names(self.conn)
        put(self.stdscr, top + 1, 2, t.title, attr(C_ACCENT, True))
        bits = [f"area: {names.get(t.area_id, '—')}",
                f"kind: {KIND_LABELS.get(t.kind, '—')}",
                f"estimate: {ESTIMATE_LABELS.get(t.estimate, '—')}"]
        if t.actual_minutes:
            est = t.estimate_minutes
            ratio = f" ({t.actual_minutes / est:.1f}× estimate)" if est else ""
            bits.append(f"actual: {fmt_minutes(t.actual_minutes)}{ratio}")
        put(self.stdscr, top + 2, 2, "  ".join(bits), attr(C_DIM))
        put(self.stdscr, top + 3, 2, f"done when: {t.outcome or '—'}",
            attr(C_DONE if t.outcome else C_WARN))
        put(self.stdscr, top + 4, 2, f"next action: {t.next_action or '—'}",
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
                    cell += " ✓" if logs[iso].lower() not in ("", "nothing") else " ·"
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

        put(self.stdscr, y, 2, "✓ = you logged something shipped · "
            "· = you logged nothing · Enter opens that day", attr(C_DIM))

    def draw_inbox(self, top, height, w):
        items = self.inbox()
        put(self.stdscr, top - 1, 2,
            f"Inbox ({len(items)}) — captured, not yet on a day", attr(C_HEAD, True))
        if not items:
            put(self.stdscr, top + 1, 2, "empty — press c to capture a thought",
                attr(C_DIM))
            return
        self.list_row = min(self.list_row, len(items) - 1)
        room = max(1, (height - 3) // 2)
        start = max(0, min(self.list_row - room + 1, len(items) - room))
        if start:
            put(self.stdscr, top, 2, f"↑ {start} above", attr(C_DIM))
        y = top + (1 if start else 0)
        names = db.area_names(self.conn)
        for i, t in enumerate(items):
            if i < start:
                continue
            if y >= top + height - 2:
                put(self.stdscr, y, 2, f"↓ {len(items) - i} more", attr(C_DIM))
                break
            on = i == self.list_row
            put(self.stdscr, y, 2, ("▸ " if on else "  ") + ellipsis(t.title, w - 30),
                attr(C_SEL, True) if on else attr(C_ACCENT))
            tail = names.get(t.area_id, "no area") if t.defined else \
                "needs " + ", ".join(t.missing)
            put(self.stdscr, y + 1, 4, ellipsis(tail, w - 8),
                attr(C_DIM if t.defined else C_WARN))
            y += 2
        put(self.stdscr, top + height - 2, 2,
            "s puts it on the open day · e defines it · x deletes", attr(C_DIM))

    def draw_areas(self, top, height, w):
        areas = self.areas
        put(self.stdscr, top - 1, 2, f"Areas ({len(areas)}) — permanent, never finished",
            attr(C_HEAD, True))
        if not areas:
            put(self.stdscr, top + 1, 2,
                "none yet — press a (try PayCheck, Health, Learning, Personal)",
                attr(C_DIM))
            return
        self.list_row = min(self.list_row, len(areas) - 1)
        y = top
        for i, a in enumerate(areas):
            if y >= top + height - 2:
                break
            items = db.tasks(self.conn, area_id=a.id)
            done = sum(t.status == "done" for t in items)
            open_now = sum(t.status != "done" for t in items)
            shipped, finished = ship_ratio(items)
            on = i == self.list_row
            put(self.stdscr, y, 2, ("▸ " if on else "  ") + ellipsis(a.name, w - 40),
                attr(C_SEL, True) if on else attr(C_ACCENT))
            tail = f"{open_now} open · {done} done · {shipped}/{finished} shipped"
            put(self.stdscr, y, max(2, w - len(tail) - 4), tail, attr(C_DIM))
            y += 2

    def draw_review(self, top, height, w):
        put(self.stdscr, top - 1, 2, "Review — what the board would rather you didn't see",
            attr(C_HEAD, True))
        y = top

        # 1. Where the last seven days actually went.
        put(self.stdscr, y, 2, "Distraction, last 7 days", attr(C_ACCENT, True))
        y += 1
        totals = {}
        for i in range(7):
            for app, label, secs in db.usage(self.conn, add_days(today(), -i)):
                totals[label] = totals.get(label, 0) + secs
        if totals:
            for label, secs in sorted(totals.items(), key=lambda kv: -kv[1])[:4]:
                mins = secs // 60
                bar = "█" * min(40, mins // 10)
                put(self.stdscr, y, 4, f"{label:12} {fmt_minutes(mins):>7}  {bar}",
                    attr(C_WARN if mins >= 7 * 60 else C_DIM))
                y += 1
        else:
            put(self.stdscr, y, 4, "nothing recorded — is space-track running?",
                attr(C_DIM))
            y += 1
        y += 1

        # 2. How wrong your estimates are, in your own data.
        finished = [t for t in db.tasks(self.conn)
                    if t.status == "done" and t.estimate and t.doing_seconds]
        put(self.stdscr, y, 2, "Estimate vs actual", attr(C_ACCENT, True))
        y += 1
        if finished:
            ratios = [t.actual_minutes / t.estimate_minutes for t in finished
                      if t.estimate_minutes]
            avg = sum(ratios) / len(ratios)
            put(self.stdscr, y, 4,
                f"over {len(finished)} finished tasks you take {avg:.1f}× your estimate",
                attr(C_WARN if avg > 1.5 else C_DONE))
            y += 1
        else:
            put(self.stdscr, y, 4,
                "no finished timed tasks yet — time counts while a task sits in Doing",
                attr(C_DIM))
            y += 1
        y += 1

        # 3. What has stopped being work.
        rotting = self.stale()
        put(self.stdscr, y, 2, f"Needs a decision ({len(rotting)})", attr(C_ACCENT, True))
        y += 1
        if not rotting:
            put(self.stdscr, y, 4, "nothing rotting", attr(C_DONE))
            return
        self.list_row = min(self.list_row, len(rotting) - 1)
        for i, (t, why) in enumerate(rotting):
            if y >= top + height - 2:
                put(self.stdscr, y, 4, f"↓ {len(rotting) - i} more", attr(C_DIM))
                break
            on = i == self.list_row
            put(self.stdscr, y, 4, ("▸ " if on else "  ") + ellipsis(t.title, w - 30),
                attr(C_SEL, True) if on else attr(C_DIM))
            put(self.stdscr, y, max(4, w - len(why) - 4), why, attr(C_WARN))
            y += 1
        put(self.stdscr, top + height - 2, 2,
            "x kills it · S sends it back to the inbox", attr(C_DIM))

    def draw_footer(self, h, w):
        if self.message:
            put(self.stdscr, h - 2, 2, ellipsis(self.message, w - 4), attr(C_WARN))
        put(self.stdscr, h - 1, 2,
            "c capture · e define · space advance · s schedule · w shipped · ? help · q quit",
            attr(C_DIM))

    # --- actions ------------------------------------------------------------

    def capture(self):
        """One line, no fields, from anywhere. Lands in the inbox."""
        text = prompt(self.stdscr, "capture:")
        if text and text.strip():
            db.capture(self.conn, text)
            self.message = "captured to inbox"

    def task_form(self, task=None, day=None):
        areas = self.area_choices()
        if not areas:
            self.message = "make an area first (press a) — every task lives in one"
            return
        fields = [
            Field("title", "Title", required=True, value=task.title if task else ""),
            Field("area_id", "Area", "choice", required=True, choices=areas,
                  value=(task.area_id if task else None) or areas[0][0]),
            Field("outcome", "Done when", required=True,
                  value=(task.outcome if task else "") or "",
                  hint="how you'll know it's finished"),
            kind_field((task.kind if task else "") or ""),
            estimate_field((task.estimate if task else "") or ""),
            Field("next_action", "Next action", required=True,
                  value=(task.next_action if task else "") or "",
                  hint="the first physical step, small enough to start now"),
        ]

        def validate(v):
            return [f"{k} is required" for k, name in (
                ("title", "title"), ("area_id", "area"), ("outcome", "outcome"),
                ("kind", "kind"), ("estimate", "estimate"),
                ("next_action", "next action")) if not str(v[k]).strip()]

        vals = run_form(self.stdscr, "Define task" if task else "New task",
                        fields, validate)
        if vals is None:
            return
        if task:
            db.update_task(self.conn, task.id, **vals)
            self.message = "defined"
        else:
            db.capture(self.conn, day=day if day is not None else self.day, **vals)
            self.message = "added"
        if vals["estimate"] in ("half_day", "day_plus"):
            self.message += " — that's bigger than half a day; consider splitting it"

    def log_shipped(self):
        existing = db.day_log(self.conn, self.day).shipped or ""
        text = prompt(self.stdscr, f"what shipped on {self.day}?", existing)
        if text is None:
            return
        db.log_shipped(self.conn, self.day, text or "nothing")
        self.message = "logged" if text.strip() else "logged: nothing"

    def advance(self, t):
        nxt = STATUS_KEYS[(STATUS_KEYS.index(t.status) + 1) % 3]
        if nxt == "doing":
            blockers = can_start(t)
            if blockers:
                self.message = "can't start: " + ", ".join(blockers) + " — press e"
                return
        db.set_status(self.conn, t.id, nxt)
        self.message = f"{ellipsis(t.title, 30)} → {STATUS_LABELS[nxt]}"

    def show_help(self):
        self.stdscr.erase()
        put(self.stdscr, 1, 2, "Keys", attr(C_HEAD, True))
        for i, (k, what) in enumerate(HELP):
            put(self.stdscr, 3 + i, 4, k.ljust(12), attr(C_ACCENT))
            put(self.stdscr, 3 + i, 18, what, attr(C_DIM))
        y = 5 + len(HELP)
        put(self.stdscr, y, 2, "How it works", attr(C_HEAD, True))
        for i, line in enumerate([
                "Capture is free; a task only has to be defined before you start it.",
                "Unfinished work rolls to today automatically — Review shows what keeps rolling.",
                "Ship = someone else could notice. Support = only helps you ship later.",
                "Time counts while a task sits in Doing, and is compared to your estimate.",
                "space-track records how long watched apps hold focus."]):
            put(self.stdscr, y + 2 + i, 4, line, attr(C_DIM))
        put(self.stdscr, y + 9, 2, "any key to go back", attr(C_DIM))
        self.stdscr.refresh()
        self.stdscr.getch()

    # --- input --------------------------------------------------------------

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
        if ch == 9:
            i = [k for k, _ in VIEWS].index(self.view)
            self.view, self.list_row = VIEWS[(i + 1) % len(VIEWS)][0], 0
            return True
        if ord("1") <= ch <= ord("5"):
            self.view, self.list_row = VIEWS[ch - ord("1")][0], 0
            return True
        if ch == ord("a"):
            name = prompt(self.stdscr, "new area:")
            if name and name.strip():
                db.add_area(self.conn, name)
                self.message = f"area '{name.strip()}' added"
            return True
        if ch == ord("w"):
            self.log_shipped()
            return True
        if ch == ord("t"):
            self.day = today()
            self.cal_cursor = date.fromisoformat(self.day)
            return True

        return {"today": self.handle_day, "calendar": self.handle_calendar,
                "inbox": self.handle_inbox, "areas": self.handle_areas,
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
        elif ch == ord("S") and t:
            db.schedule(self.conn, t.id, None)
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
            blockers = can_start(t)
            if blockers:
                self.message = "define it first: " + ", ".join(blockers) + " — press e"
            else:
                db.schedule(self.conn, t.id, self.day)
                self.message = f"scheduled for {self.day}"
        elif ch == ord("x") and t:
            if confirm(self.stdscr, f"delete '{ellipsis(t.title, 40)}'?"):
                db.delete(self.conn, "tasks", t.id)
        return True

    def handle_areas(self, ch):
        areas = self.areas
        if ch in (ord("j"), curses.KEY_DOWN):
            self.list_row = min(self.list_row + 1, max(0, len(areas) - 1))
        elif ch in (ord("k"), curses.KEY_UP):
            self.list_row = max(0, self.list_row - 1)
        elif ch in (ord("e"), curses.KEY_ENTER, 10, 13) and areas:
            a = areas[self.list_row]
            name = prompt(self.stdscr, "rename area:", a.name)
            if name and name.strip():
                self.conn.execute("update areas set name = ? where id = ?",
                                  (name.strip(), a.id))
                self.conn.commit()
        elif ch == ord("x") and areas:
            a = areas[self.list_row]
            n = len(db.tasks(self.conn, area_id=a.id))
            if confirm(self.stdscr, f"delete area '{a.name}'? {n} tasks lose their area"):
                db.delete(self.conn, "areas", a.id)
        return True

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
            self.message = "back to the inbox, roll count reset"
        return True

    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        while True:
            self.draw()
            ch = self.stdscr.getch()
            if ch == curses.KEY_RESIZE:
                continue
            if not self.handle(ch):
                return


def main(stdscr):
    init_colors()
    disable_flow_control()
    App(stdscr, db.connect()).run()


def run():
    curses.wrapper(main)
