"""The end-of-day question.

One question a day, always the same one, asked with the day's facts on screen
above it. The facts matter more than the question: it is hard to type "good
day" underneath 23 Telegram checks and nothing shipped.

Rules, all deliberate:
  · Only today can be answered. At midnight the day locks and an unanswered
    day stays blank forever, because a journal you can backfill becomes a
    record of what you wish had happened.
  · "nothing" is a real answer, recorded as such, and shows in the calendar.
  · No streaks, no score, no guilt. The numbers do that job honestly already.
  · On Sunday there are three more questions, where a week of data makes the
    answers real rather than guessed.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from . import db
from .model import (
    NAGGING_ROLLS, add_days, fmt_minutes, ship_ratio, today,
)

DIM, ACC, OK, WARN, OFF = "\033[2m", "\033[33m", "\033[32m", "\033[31m", "\033[0m"

# The question is asked at midnight, when the day you are reporting on has
# just ended. So the reviewable day runs to 04:00, not to 24:00: at 00:30 you
# are still answering for the day you actually lived. After 04:00 that day is
# closed for good — the lock still exists, it just sits where the sleep does.
DAY_ENDS_AT = 4

# Two questions, in this order. The second is the one that does the work:
# what you did is usually already on the board, what you didn't is not
# recorded anywhere and is what the day actually cost.
DAILY = [
    ("did", "What important things did you do today?",
     'the ones that mattered — "nothing" is a real answer'),
    ("missed", "What important things did you not do today?",
     "the ones you meant to and didn't"),
]

WEEKLY = [
    ("moved", "What actually moved this week?",
     "one line — the thing someone else could notice"),
    ("avoided", "What did you keep avoiding?",
     "the honest answer is usually already on the list above"),
    ("change", "What will you do differently next week?",
     "one change, small enough to actually do"),
]


def review_day(when: datetime | None = None) -> str:
    """The day currently being reviewed — yesterday until 04:00, then today."""
    when = when or datetime.now()
    return (when - timedelta(hours=DAY_ENDS_AT)).date().isoformat()


def questions_for(day: str) -> list[tuple[str, str, str]]:
    """The day's questions, naming the day when it isn't the calendar's today."""
    if day == date.today().isoformat():
        return DAILY
    weekday = date.fromisoformat(day).strftime("%A")
    return [(key, q.replace("today", f"on {weekday}"), hint)
            for key, q, hint in DAILY]


def ask(question: str, hint: str, existing: str = "") -> str | None:
    """One prompt. Returns None if the user backed out."""
    print(f"\n{ACC}{question}{OFF}")
    print(f"{DIM}{hint}{OFF}")
    if existing:
        print(f"{DIM}currently: {existing}{OFF}")
    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n{DIM}left unanswered{OFF}")
        return None


def day_facts(conn, day: str) -> None:
    """The grounding: what the day looks like from the outside."""
    tasks = db.tasks(conn, day=day)
    done = [t for t in tasks if t.status == "done"]
    unfinished = [t for t in tasks if t.status != "done"]
    shipped, finished = ship_ratio(tasks)

    print(f"{ACC}{date.fromisoformat(day).strftime('%A %d %B')}{OFF}")
    print(f"{DIM}{'─' * 46}{OFF}")

    if done:
        print(f"finished {len(done)} · {shipped} of them shipped")
        for t in done[:6]:
            mark = OK if t.kind == "ship" else DIM
            print(f"  {mark}✓ {t.title}{OFF}")
        if len(done) > 6:
            print(f"  {DIM}… and {len(done) - 6} more{OFF}")
    else:
        print(f"{DIM}nothing finished today{OFF}")

    if unfinished:
        print(f"{DIM}still open: {', '.join(t.title for t in unfinished[:3])}"
              f"{' …' if len(unfinished) > 3 else ''}{OFF}")

    red = db.usage_total(conn, day, color="red")
    tracked = db.usage_total(conn, day)
    if tracked:
        line = f"screen time {fmt_minutes(tracked // 60)}"
        if red:
            detail = []
            for app, label, color, secs in db.usage(conn, day):
                if color == "red":
                    d = db.usage_detail(conn, app, day)
                    detail.append(f"{label} {fmt_minutes(secs // 60)} "
                                  f"in {d['opens']} checks")
            line += f" · {WARN}{', '.join(detail)}{OFF}"
        print(line)
    print()


def daily(conn, day: str) -> bool:
    """Ask the day's two questions. Returns True once both are answered."""
    log = db.day_log(conn, day)
    day_facts(conn, day)
    answers = {}
    for key, question, hint in questions_for(day):
        existing = log.did if key == "did" else log.not_done
        got = ask(question, hint, existing)
        if got is None:
            # Backing out of the second question shouldn't throw away the
            # first — keep what was said, leave the rest blank.
            if answers.get("did"):
                db.log_day(conn, day, answers["did"], "")
                print(f"{DIM}kept what you answered{OFF}")
                return True
            return False
        answers[key] = got
    db.log_day(conn, day, answers["did"] or "nothing", answers["missed"])
    print(f"{OK}logged{OFF}")
    return True


def week_facts(conn, day: str) -> None:
    start = db.week_start(day)
    span = [add_days(start, i) for i in range(7)]
    tasks = [t for d in span for t in db.tasks(conn, day=d)]
    shipped, finished = ship_ratio(tasks)

    print(f"\n{ACC}The week of {start}{OFF}")
    print(f"{DIM}{'─' * 46}{OFF}")
    print(f"finished {finished} · {shipped} shipped")

    totals = {}
    for d in span:
        for app, label, color, secs in db.usage(conn, d):
            prev = totals.get(label, (color, 0))[1]
            totals[label] = (color, prev + secs)
    for label, (color, secs) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        tint = WARN if color == "red" else DIM
        print(f"  {tint}{label:12} {fmt_minutes(secs // 60)}{OFF}")

    rolling = [t for t in db.tasks(conn)
               if t.status != "done" and t.rolls >= NAGGING_ROLLS]
    if rolling:
        print(f"\n{WARN}kept pushing forward:{OFF}")
        for t in rolling[:6]:
            print(f"  {t.title} {DIM}({t.rolls}×){OFF}")
    print()


def weekly(conn, day: str) -> None:
    existing = db.week_log(conn, day)
    week_facts(conn, day)
    answers = {}
    for key, question, hint in WEEKLY:
        got = ask(question, hint, getattr(existing, key) or "")
        if got is None:
            return
        answers[key] = got
    db.log_week(conn, day, answers["moved"], answers["avoided"],
                answers["change"])
    print(f"{OK}week logged{OFF}")


def pending(conn, day: str | None = None) -> bool:
    """Is there anything still answerable?"""
    day = day or review_day()
    if not db.day_log(conn, day).answered:
        return True
    return is_sunday(day) and not db.week_log(conn, day).answered


def is_sunday(day: str) -> bool:
    return date.fromisoformat(day).weekday() == 6


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--plain" in argv:
        globals().update(DIM="", ACC="", OK="", WARN="", OFF="")

    conn = db.connect()
    day = review_day()

    if "--date" in argv:
        wanted = argv[argv.index("--date") + 1]
        if wanted != day:
            print(f"{WARN}{wanted} is closed.{OFF} Only {day} can still be "
                  f"answered — a day you can fill in later stops being a record.",
                  file=sys.stderr)
            return 1

    if "--check" in argv:                     # for scripts: is anything pending?
        return 0 if pending(conn, day) else 1

    log = db.day_log(conn, day)
    if log.answered and "--again" not in argv and not (
            is_sunday(day) and not db.week_log(conn, day).answered):
        print(f"{DIM}{day} is already answered{OFF}")
        print(f"  {OK}did:{OFF} {log.did}")
        print(f"  {WARN}not:{OFF} {log.not_done or '—'}")
        print(f"{DIM}space-review --again to change it{OFF}")
        return 0

    if not log.answered or "--again" in argv:
        if not daily(conn, day):
            return 1

    if is_sunday(day) and not db.week_log(conn, day).answered:
        weekly(conn, day)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
