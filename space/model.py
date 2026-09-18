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
class Node:
    """One node of the tree of things you care about.

    The tree is a forest of permanent nodes — nothing is ever completed or
    closed. A node with children reads as an area; a leaf reads as a goal.
    That distinction is derived, never stored, so a goal becomes an area the
    moment you nest something under it and nothing has to be migrated.

    Tasks may hang off any node, not only leaves: the natural place for a
    task is wherever you were thinking when you wrote it down.
    """
    id: str
    name: str
    parent_id: str | None = None
    position: int = 0
    created_at: str = ""


@dataclass
class Tree:
    """A flattened view of the forest: every node with its depth and path."""
    nodes: list[Node]
    children: dict[str | None, list[Node]]

    def kids(self, node_id: str | None) -> list[Node]:
        return self.children.get(node_id, [])

    def is_leaf(self, node_id: str) -> bool:
        return not self.children.get(node_id)

    def label(self, node_id: str) -> str:
        """What this node is, in the vocabulary of the tree."""
        return "goal" if self.is_leaf(node_id) else "area"

    def path(self, node_id: str | None, sep: str = " › ") -> str:
        by_id = {n.id: n for n in self.nodes}
        parts, seen = [], set()
        while node_id and node_id in by_id and node_id not in seen:
            seen.add(node_id)
            parts.append(by_id[node_id].name)
            node_id = by_id[node_id].parent_id
        return sep.join(reversed(parts))

    def descendants(self, node_id: str) -> list[Node]:
        out, stack = [], list(self.kids(node_id))
        while stack:
            n = stack.pop()
            out.append(n)
            stack.extend(self.kids(n.id))
        return out

    def walk(self, node_id: str | None = None, depth: int = 0):
        """Depth-first, yielding (node, depth) in display order."""
        for child in self.kids(node_id):
            yield child, depth
            yield from self.walk(child.id, depth + 1)


@dataclass
class Task:
    id: str
    title: str
    node_id: str | None = None        # anywhere in the tree, leaf or not
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
        return bool(self.node_id and self.outcome and self.next_action
                    and self.kind and self.estimate)

    @property
    def missing(self) -> list[str]:
        return [name for name, val in (
            ("goal", self.node_id), ("outcome", self.outcome),
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
    """The day's two answers. 'nothing' is legal, recorded, and visible.

    `shipped` holds what mattered that you did; it keeps its original name
    from when there was only one question.
    """
    date: str
    shipped: str | None = None
    missed: str | None = None
    logged_at: str | None = None

    @property
    def did(self) -> str:
        return (self.shipped or "").strip()

    @property
    def not_done(self) -> str:
        return (self.missed or "").strip()

    @property
    def answered(self) -> bool:
        return bool(self.logged_at or self.did or self.not_done)

    @property
    def empty_day(self) -> bool:
        """Answered, and the answer was that nothing of note happened."""
        return self.did.lower() in ("nothing", "none", "-", "")


@dataclass
class Week:
    """The Sunday review: what moved, what you avoided, what changes."""
    week_start: str
    moved: str | None = None
    avoided: str | None = None
    change: str | None = None
    logged_at: str | None = None

    @property
    def answered(self) -> bool:
        return bool(self.moved or self.avoided or self.change)


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
