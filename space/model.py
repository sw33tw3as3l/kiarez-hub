"""Domain rules.

Two ideas drive the shape of this:

1. Capture is free, committing is not. Anything can be written down in one
   line. A task only has to be *defined* — area, outcome, next action, kind,
   estimate — before you're allowed to start it.
2. The tool should be able to tell you whether a day was real. That needs a
   ship/support split on every task, an honest end-of-day line, and a record
   of where the hours actually went.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

STATUSES = [("todo", "To Do"), ("doing", "Doing"), ("done", "Done")]
STATUS_KEYS = [k for k, _ in STATUSES]
STATUS_LABELS = dict(STATUSES)

# Real work vs fake work. "Ship" means someone other than you could notice it
# happened. "Support" is everything that only makes shipping easier later —
# tooling, config, research, process. Support isn't bad; a week that is all
# support is.
KINDS = [("ship", "Ship"), ("support", "Support")]
KIND_KEYS = [k for k, _ in KINDS]
KIND_LABELS = dict(KINDS)

ESTIMATES = [
    ("15m", "15m", 15),
    ("30m", "30m", 30),
    ("1h", "1h", 60),
    ("2h", "2h", 120),
    ("half_day", "Half day", 240),
    ("day_plus", "Day+", 480),
]
ESTIMATE_KEYS = [k for k, _, _ in ESTIMATES]
ESTIMATE_LABELS = {k: label for k, label, _ in ESTIMATES}
ESTIMATE_MINUTES = {k: mins for k, _, mins in ESTIMATES}

# Bigger than half a day is not one task. It still gets captured, it just
# shouldn't be dropped onto a single day pretending it will happen.
OVERSIZED = {"half_day", "day_plus"}

STALE_DAYS = 14          # untouched this long and it wants a decision
NAGGING_ROLLS = 3        # rolled forward this often and it wants a decision

GREETINGS = [
    "Hi KiaRez",
    "What's up?",
    "One thing at a time",
    "Start small",
    "Focus time",
    "Let's go",
    "Ship something",
    "Nice work",
]


@dataclass
class Area:
    """A permanent part of your life. Areas are never finished or achieved."""
    id: str
    name: str
    position: int = 0
    created_at: str = ""


@dataclass
class Task:
    id: str
    title: str
    area_id: str | None = None
    day: str | None = None            # None = inbox, not yet scheduled
    status: str = "todo"
    kind: str | None = None           # ship | support
    outcome: str | None = None        # definition of done
    next_action: str | None = None
    estimate: str | None = None
    doing_seconds: int = 0
    doing_since: str | None = None
    rolls: int = 0                    # times auto-rolled to the next day
    position: int = 0
    created_at: str = ""
    touched_at: str = ""
    done_at: str | None = None

    @property
    def defined(self) -> bool:
        return bool(self.area_id and self.outcome and self.next_action
                    and self.kind and self.estimate)

    @property
    def missing(self) -> list[str]:
        return [name for name, val in (
            ("area", self.area_id), ("outcome", self.outcome),
            ("next action", self.next_action), ("kind", self.kind),
            ("estimate", self.estimate)) if not val]

    @property
    def oversized(self) -> bool:
        return self.estimate in OVERSIZED

    @property
    def actual_minutes(self) -> int:
        secs = self.doing_seconds
        if self.doing_since:
            secs += max(0, int((utc_now() - parse(self.doing_since))
                               .total_seconds()))
        return round(secs / 60)

    @property
    def estimate_minutes(self) -> int | None:
        return ESTIMATE_MINUTES.get(self.estimate or "")

    def stale_days(self) -> int:
        if not self.touched_at:
            return 0
        return (utc_now() - parse(self.touched_at)).days


@dataclass
class Day:
    """What you said shipped that day. 'nothing' is a legal, visible answer."""
    date: str
    shipped: str | None = None
    logged_at: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse(stamp: str) -> datetime:
    d = datetime.fromisoformat(stamp)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def today() -> str:
    return date.today().isoformat()


def add_days(date_str: str, delta: int) -> str:
    return (date.fromisoformat(date_str) + timedelta(days=delta)).isoformat()


def fmt_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h" if not mins else f"{hours}h{mins:02d}"


def can_start(task: Task) -> list[str]:
    """Why this task may not be started yet. Empty list means go ahead.

    This is the only friction in the system, and it sits at the moment of
    commitment rather than the moment of capture.
    """
    if task.defined:
        return []
    return [f"{m} is missing" for m in task.missing]


def ship_ratio(tasks) -> tuple[int, int]:
    """(shipped, total) over finished tasks — the real-vs-fake-work number."""
    done = [t for t in tasks if t.status == "done"]
    return sum(t.kind == "ship" for t in done), len(done)
