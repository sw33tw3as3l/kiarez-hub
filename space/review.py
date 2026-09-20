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

import os
import sys
from datetime import date, datetime, timedelta

from . import db
from .model import (
    NAGGING_ROLLS, add_days, done_count, fmt_minutes, today,
)

DIM, ACC, OK, WARN, OFF = "\033[2m", "\033[33m", "\033[32m", "\033[31m", "\033[0m"

# You can always answer yesterday, any time today. At midnight tonight
# yesterday closes for good and today takes its place.
#
# This replaces an hour-of-the-morning cutoff, which sounded reasonable and
# was not: the first two nights it shipped both closed unanswered, because the
# question arrives at midnight while you are busy or asleep and the window had
# already shut by the time you were back at the keyboard. One day of grace is
# still a day you lived and can remember, and it cannot be backfilled — you
# are never writing about Tuesday on Friday.


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


def yesterday(when: datetime | None = None) -> str:
    return ((when or datetime.now()).date() - timedelta(days=1)).isoformat()


def review_day(when: datetime | None = None, conn=None) -> str:
    """The day a sit-down is about: yesterday while it is still unanswered.

    Once yesterday is answered this is today, so an evening entry has
    somewhere to go.
    """
    when = when or datetime.now()
    if conn is not None and not db.day_log(conn, yesterday(when)).answered:
        return yesterday(when)
    return when.date().isoformat()


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
    print(f"{ACC}{date.fromisoformat(day).strftime('%A %d %B')}{OFF}")
    print(f"{DIM}{'─' * 46}{OFF}")

    if done:
        print(f"finished {len(done)} of {len(tasks)}")
        for t in done[:6]:
            print(f"  {OK}✓ {t.title}{OFF}")
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
    finished, total = done_count(tasks)

    print(f"\n{ACC}The week of {start}{OFF}")
    print(f"{DIM}{'─' * 46}{OFF}")
    print(f"finished {finished} of {total}")

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
    """Is anything actually owed — for `day`, or at all?

    Owed, not merely unanswered. Today is unanswered for most of its length
    and is not owed at any point in it, so a reminder built on "unanswered"
    would announce a brand new day the moment you settled the old one.
    """
    due = owed(conn)
    if day is not None:
        if day == due:
            return True
        # A Sunday that has been answered can still owe its weekly review.
        return (day == yesterday() and is_sunday(day)
                and db.day_log(conn, day).answered
                and not db.week_log(conn, day).answered)
    if due:
        return True
    last = yesterday()
    return (is_sunday(last) and db.day_log(conn, last).answered
            and not db.week_log(conn, last).answered)


def owed(conn) -> str | None:
    """Yesterday, if it is still unanswered. Otherwise nothing is due.

    Today is never owed — the day is not over, and demanding an account of a
    day still being lived only teaches you to type something to get past it.
    """
    day = yesterday()
    return day if not db.day_log(conn, day).answered else None


def is_sunday(day: str) -> bool:
    return date.fromisoformat(day).weekday() == 6


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--plain" in argv:
        globals().update(DIM="", ACC="", OK="", WARN="", OFF="")

    conn = db.connect()
    day = review_day(conn=conn)

    if "--day" in argv:                       # for scripts: which day is open?
        print(day)
        return 0

    if "--date" in argv:
        wanted = argv[argv.index("--date") + 1]
        if wanted != day:
            print(f"{WARN}{wanted} is closed.{OFF} Only {day} can still be "
                  f"answered — a day you can fill in later stops being a record.",
                  file=sys.stderr)
            return 1

    if "--check" in argv:                     # for scripts: is anything pending?
        wanted = argv[argv.index("--for") + 1] if "--for" in argv else None
        if wanted:
            return 0 if pending(conn, wanted) else 1
        return 0 if pending(conn) else 1

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
