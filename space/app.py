"""The board itself: four views over the local SQLite database."""

from __future__ import annotations

import calendar
import curses
import random
from datetime import date

from . import db
from .model import (
    CATEGORIES, EFFORT_LABELS, GREETINGS, STATUS_KEYS, STATUS_LABELS,
    add_days, today, validate_task,
)
from .ui import (
    C_ACCENT, C_DIM, C_DOING, C_DONE, C_HEAD, C_SEL, C_WARN, Field,
    attr, confirm, disable_flow_control, effort_field, ellipsis, hline,
    init_colors, put, run_form, wrap,
)

VIEWS = [("board", "Board"), ("calendar", "Calendar"),
         ("longterm", "Long-term"), ("goals", "Goals")]

STATUS_COLOR = {"todo": C_DIM, "doing": C_DOING, "done": C_DONE}

HELP = [
    ("1-4 / Tab", "switch view"),
    ("j k", "move down / up"),
    ("h l", "move between columns"),
    ("J K", "reorder task within its column"),
    ("space", "advance status (todo → doing → done)"),
    ("n", "new task"),
    ("g", "new goal"),
    ("e / Enter", "edit"),
    ("x", "delete"),
    ("[ ]", "previous / next day"),
    ("t", "jump to today"),
    ("?", "this help"),
    ("q", "quit"),
]


class App:
    def __init__(self, stdscr, conn):
        self.stdscr = stdscr
        self.conn = conn
        self.view = "board"
        self.day = today()
        self.col = 0                      # selected status column
        self.row = 0                      # selected card in that column
        self.goal_row = 0
        self.message = ""
        self.greeting = random.choice(GREETINGS)
        self.cal_cursor = date.fromisoformat(self.day)

    # --- data helpers -------------------------------------------------------

    @property
    def goals(self):
        return db.goals(self.conn)

    def goal_choices(self):
        return [(g.id, g.title) for g in self.goals]

    def columns(self):
        """Tasks for the current view, grouped into the three status columns."""
        if self.view == "longterm":
            items = db.tasks(self.conn, category="longterm")
        else:
            items = [t for t in db.tasks(self.conn, category="board")
                     if t.due_date == self.day]
        return {s: [t for t in items if t.status == s] for s in STATUS_KEYS}

    def selected(self):
        cols = self.columns()
        items = cols[STATUS_KEYS[self.col]]
        if not items:
            return None
        self.row = min(self.row, len(items) - 1)
        return items[self.row]

    # --- drawing ------------------------------------------------------------

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        self.draw_header(w)
        body_h = h - 4
        if self.view in ("board", "longterm"):
            self.draw_board(3, body_h, w)
        elif self.view == "calendar":
            self.draw_calendar(3, body_h, w)
        else:
            self.draw_goals(3, body_h, w)
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

    def draw_board(self, top, height, w):
        cols = self.columns()
        if self.view == "board":
            d = date.fromisoformat(self.day)
            stamp = d.strftime("%a %d %b %Y")
            label = "today" if self.day == today() else ""
            put(self.stdscr, top - 1, 2, f"{stamp}  {label}", attr(C_HEAD, True))
        else:
            put(self.stdscr, top - 1, 2, "Long-term — no due date, bigger than a day",
                attr(C_HEAD, True))

        detail_h = 7
        list_h = height - detail_h - 1
        cw = max(18, (w - 6) // 3)

        for ci, status in enumerate(STATUS_KEYS):
            x = 2 + ci * cw
            items = cols[status]
            head = f"{STATUS_LABELS[status]} ({len(items)})"
            put(self.stdscr, top, x, head,
                attr(STATUS_COLOR[status], ci == self.col))
            hline(self.stdscr, top + 1, x, cw - 2,
                  attr(C_ACCENT if ci == self.col else C_DIM))

            # Cards are 2-4 lines tall, so scroll by card: keep the selected
            # one on screen and say how many are hidden either way.
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
                mark = "▸ " if on else "  "
                a = attr(C_SEL, True) if on else attr(STATUS_COLOR[status])
                put(self.stdscr, y, x, mark + ellipsis(t.title, cw - 5), a,
                    width=cw - 2)
                y += 1
                # The definition of done, on the card face.
                if t.outcome:
                    put(self.stdscr, y, x + 2,
                        ellipsis("✓ " + t.outcome, cw - 6), attr(C_DIM))
                    y += 1
                meta = []
                if t.effort:
                    meta.append(EFFORT_LABELS[t.effort])
                if t.due_time:
                    meta.append(t.due_time[:5])
                if not t.defined:
                    meta.append("undefined!")
                if meta:
                    put(self.stdscr, y, x + 2, ellipsis(" · ".join(meta), cw - 6),
                        attr(C_WARN if not t.defined else C_DIM))
                    y += 1
                y += 1

        self.draw_detail(top + list_h, detail_h, w)

    @staticmethod
    def card_height(t) -> int:
        return 2 + bool(t.outcome) + bool(t.effort or t.due_time or not t.defined)

    def scroll_start(self, items, col_index: int, room: int) -> int:
        """First card to draw so the selected one fits in `room` lines."""
        if col_index != self.col or not items:
            return 0
        sel = min(self.row, len(items) - 1)
        start = 0
        while True:
            used = sum(self.card_height(t) for t in items[start:sel + 1])
            if used <= room or start >= sel:
                return start
            start += 1

    def draw_detail(self, top, height, w):
        hline(self.stdscr, top, 2, w - 4, attr(C_DIM))
        t = self.selected()
        if not t:
            put(self.stdscr, top + 1, 2, "no task selected — press n to add one",
                attr(C_DIM))
            return
        titles = db.goal_titles(self.conn)
        put(self.stdscr, top + 1, 2, t.title, attr(C_ACCENT, True))
        bits = [f"goal: {titles.get(t.goal_id, '— none —')}",
                f"effort: {EFFORT_LABELS.get(t.effort, '—')}",
                f"status: {STATUS_LABELS[t.status]}"]
        if t.due_time:
            bits.append(f"at {t.due_time[:5]}")
        put(self.stdscr, top + 2, 2, "  ".join(bits), attr(C_DIM))
        put(self.stdscr, top + 3, 2, f"done when: {t.outcome or '—'}",
            attr(C_DONE if t.outcome else C_WARN))
        put(self.stdscr, top + 4, 2, f"next action: {t.next_action or '—'}",
            attr(C_DOING if t.next_action else C_WARN))
        if t.description and height > 6:
            for i, line in enumerate(wrap(t.description, w - 6)[:1]):
                put(self.stdscr, top + 5 + i, 2, line, attr(C_DIM))

    def draw_calendar(self, top, height, w):
        cur = self.cal_cursor
        first = cur.replace(day=1)
        days_in = calendar.monthrange(cur.year, cur.month)[1]
        all_days = [first.replace(day=i).isoformat() for i in range(1, days_in + 1)]
        counts = db.counts_by_day(self.conn, all_days)

        put(self.stdscr, top - 1, 2, cur.strftime("%B %Y"), attr(C_HEAD, True))
        for i, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            put(self.stdscr, top, 2 + i * 10, name, attr(C_DIM))

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
                a = attr(C_DIM)
                if total and done == total:
                    a = attr(C_DONE)
                elif total:
                    a = attr(C_DOING)
                if iso == today():
                    a |= curses.A_UNDERLINE
                if d == cur:
                    a = attr(C_SEL, True)
                put(self.stdscr, y, 2 + i * 10, cell.ljust(8), a)
            y += 2

        put(self.stdscr, y, 2,
            "Enter opens that day on the board · h/j/k/l move · t today",
            attr(C_DIM))

    def draw_goals(self, top, height, w):
        gs = self.goals
        put(self.stdscr, top - 1, 2, f"Goals ({len(gs)})", attr(C_HEAD, True))
        if not gs:
            put(self.stdscr, top + 1, 2, "no goals yet — press g to add one",
                attr(C_DIM))
            return
        self.goal_row = min(self.goal_row, len(gs) - 1)
        # Two lines per goal, three when it has a description; the draw loop
        # below stops early if the descriptions eat the extra room.
        room = max(1, (height - 3) // 2)
        start = max(0, min(self.goal_row - room + 1, len(gs) - room))
        if start > 0:
            put(self.stdscr, top, 2, f"↑ {start} above", attr(C_DIM))
        y = top + (1 if start else 0)
        for i, g in enumerate(gs):
            if i < start:
                continue
            if y >= top + height - 2:
                put(self.stdscr, y, 2, f"↓ {len(gs) - i} more", attr(C_DIM))
                break
            tasks = db.tasks(self.conn, goal_id=g.id)
            done = sum(t.status == "done" for t in tasks)
            on = i == self.goal_row
            put(self.stdscr, y, 2, ("▸ " if on else "  ") + ellipsis(g.title, w - 30),
                attr(C_SEL, True) if on else attr(C_ACCENT))
            tail = f"{done}/{len(tasks)} done"
            if g.target_date:
                tail += f" · by {g.target_date}"
            put(self.stdscr, y, w - len(tail) - 4, tail, attr(C_DIM))
            y += 1
            if g.description:
                put(self.stdscr, y, 4, ellipsis(g.description, w - 8), attr(C_DIM))
                y += 1
            y += 1

    def draw_footer(self, h, w):
        if self.message:
            put(self.stdscr, h - 2, 2, self.message, attr(C_WARN))
        put(self.stdscr, h - 1, 2,
            "n new · e edit · space advance · x delete · [ ] day · ? help · q quit",
            attr(C_DIM))

    # --- actions ------------------------------------------------------------

    def task_form(self, task=None):
        goals = self.goal_choices()
        if not goals:
            self.message = "add a goal first (press g) — every task needs one"
            return
        category = task.category if task else (
            "longterm" if self.view == "longterm" else "board")
        fields = [
            Field("title", "Title", required=True, value=task.title if task else ""),
            Field("goal_id", "Goal", "choice", required=True, choices=goals,
                  value=task.goal_id if task else goals[0][0]),
            Field("outcome", "Done when", required=True,
                  value=(task.outcome if task else "") or "",
                  hint="the definition of done — how you'll know it's finished"),
            effort_field((task.effort if task else "") or ""),
            Field("next_action", "Next action", required=True,
                  value=(task.next_action if task else "") or "",
                  hint="the first physical step, small enough to start now"),
            Field("category", "Where it lives", "choice", choices=list(CATEGORIES),
                  value=category),
            Field("due_date", "Due date", value=(task.due_date if task else self.day) or "",
                  hint="YYYY-MM-DD, or blank for long-term"),
            Field("due_time", "Time", value=(task.due_time if task else "") or "",
                  hint="HH:MM, optional"),
            Field("description", "Notes", value=(task.description if task else "") or ""),
        ]

        def validate(v):
            return validate_task(
                title=v["title"], goal_id=v["goal_id"], outcome=v["outcome"],
                effort=v["effort"], next_action=v["next_action"],
                category=v["category"])

        vals = run_form(self.stdscr, "Edit task" if task else "New task",
                        fields, validate)
        if vals is None:
            return
        if vals["category"] == "longterm":
            vals["due_date"] = vals["due_date"] or None
        if task:
            db.update(self.conn, "tasks", task.id, **vals)
            self.message = "task updated"
        else:
            db.add_task(self.conn, status=STATUS_KEYS[self.col], **vals)
            self.message = "task added"

    def goal_form(self, goal=None):
        fields = [
            Field("title", "Title", required=True, value=goal.title if goal else ""),
            Field("description", "Description",
                  value=(goal.description if goal else "") or ""),
            Field("target_date", "Target date",
                  value=(goal.target_date if goal else "") or "",
                  hint="YYYY-MM-DD, optional"),
        ]
        vals = run_form(self.stdscr, "Edit goal" if goal else "New goal", fields,
                        lambda v: [] if v["title"].strip() else ["title is required"])
        if vals is None:
            return
        if goal:
            db.update(self.conn, "goals", goal.id, **vals)
            self.message = "goal updated"
        else:
            db.add_goal(self.conn, vals["title"], vals["description"],
                        vals["target_date"] or None)
            self.message = "goal added"

    def show_help(self):
        self.stdscr.erase()
        put(self.stdscr, 1, 2, "Keys", attr(C_HEAD, True))
        for i, (k, what) in enumerate(HELP):
            put(self.stdscr, 3 + i, 4, k.ljust(12), attr(C_ACCENT))
            put(self.stdscr, 3 + i, 18, what, attr(C_DIM))
        put(self.stdscr, 5 + len(HELP), 2, "any key to go back", attr(C_DIM))
        self.stdscr.refresh()
        self.stdscr.getch()

    # --- input --------------------------------------------------------------

    def handle(self, ch) -> bool:
        """Returns False to quit."""
        self.message = ""

        if ch in (ord("q"), ord("Q")):
            return False
        if ch == ord("?"):
            self.show_help()
            return True
        if ch == 9:                                    # Tab
            i = [k for k, _ in VIEWS].index(self.view)
            self.view = VIEWS[(i + 1) % len(VIEWS)][0]
            return True
        if ord("1") <= ch <= ord("4"):
            self.view = VIEWS[ch - ord("1")][0]
            return True
        if ch == ord("g"):
            self.goal_form()
            return True
        if ch == ord("t"):
            self.day = today()
            self.cal_cursor = date.fromisoformat(self.day)
            return True

        if self.view == "calendar":
            return self.handle_calendar(ch)
        if self.view == "goals":
            return self.handle_goals(ch)
        return self.handle_board(ch)

    def handle_board(self, ch):
        cols = self.columns()
        items = cols[STATUS_KEYS[self.col]]
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
            nxt = STATUS_KEYS[(STATUS_KEYS.index(t.status) + 1) % 3]
            db.set_status(self.conn, t.id, nxt)
            self.message = f"{t.title} → {STATUS_LABELS[nxt]}"
        elif ch == ord("n"):
            self.task_form()
        elif ch in (ord("e"), curses.KEY_ENTER, 10, 13) and t:
            self.task_form(t)
        elif ch == ord("x") and t:
            if confirm(self.stdscr, f"delete '{ellipsis(t.title, 40)}'?"):
                db.delete(self.conn, "tasks", t.id)
                self.message = "deleted"
        elif ch == ord("[") and self.view == "board":
            self.day, self.row = add_days(self.day, -1), 0
        elif ch == ord("]") and self.view == "board":
            self.day, self.row = add_days(self.day, 1), 0
        return True

    def handle_calendar(self, ch):
        step = {ord("h"): -1, curses.KEY_LEFT: -1, ord("l"): 1,
                curses.KEY_RIGHT: 1, ord("j"): 7, curses.KEY_DOWN: 7,
                ord("k"): -7, curses.KEY_UP: -7,
                ord("["): -1, ord("]"): 1}.get(ch)
        if step:
            self.cal_cursor = date.fromisoformat(
                add_days(self.cal_cursor.isoformat(), step))
        elif ch in (curses.KEY_ENTER, 10, 13, ord(" ")):
            self.day = self.cal_cursor.isoformat()
            self.view, self.row = "board", 0
        elif ch == ord("n"):
            self.day = self.cal_cursor.isoformat()
            self.task_form()
        return True

    def handle_goals(self, ch):
        gs = self.goals
        if ch in (ord("j"), curses.KEY_DOWN):
            self.goal_row = min(self.goal_row + 1, max(0, len(gs) - 1))
        elif ch in (ord("k"), curses.KEY_UP):
            self.goal_row = max(0, self.goal_row - 1)
        elif ch in (ord("e"), curses.KEY_ENTER, 10, 13) and gs:
            self.goal_form(gs[self.goal_row])
        elif ch == ord("x") and gs:
            g = gs[self.goal_row]
            n = len(db.tasks(self.conn, goal_id=g.id))
            if confirm(self.stdscr,
                       f"delete goal '{ellipsis(g.title, 30)}'? {n} tasks keep existing"):
                db.delete(self.conn, "goals", g.id)
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
    conn = db.connect()
    App(stdscr, conn).run()


def run():
    curses.wrapper(main)
