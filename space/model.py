"""Domain model for the local board: statuses, categories, effort sizes.

Mirrors the schema the old web app used, so the exported Supabase rows
import without any field mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

STATUSES = [("todo", "To Do"), ("doing", "Doing"), ("done", "Done")]
STATUS_KEYS = [k for k, _ in STATUSES]
STATUS_LABELS = dict(STATUSES)

CATEGORIES = [("board", "Board"), ("longterm", "Long-term")]
CATEGORY_KEYS = [k for k, _ in CATEGORIES]

EFFORTS = [
    ("15m", "15m"),
    ("30m", "30m"),
    ("1h", "1h"),
    ("2h", "2h"),
    ("half_day", "Half day"),
    ("day_plus", "Day+"),
]
EFFORT_KEYS = [k for k, _ in EFFORTS]
EFFORT_LABELS = dict(EFFORTS)

# Anything at or above half a day is too big to live on the day board:
# it has to be split into smaller tasks or promoted to Long-term.
OVERSIZED = {"half_day", "day_plus"}

GREETINGS = [
    "Hi KiaRez",
    "What's up?",
    "You got this",
    "Keep going",
    "Focus time",
    "Let's go",
    "One step at a time",
    "Nice work",
]


@dataclass
class Goal:
    id: str
    title: str
    description: str | None = None
    target_date: str | None = None
    position: int = 0
    archived: bool = False
    created_at: str = ""


@dataclass
class Task:
    id: str
    title: str
    description: str | None = None
    status: str = "todo"
    category: str = "board"
    due_date: str | None = None
    due_time: str | None = None
    position: int = 0
    created_at: str = ""
    goal_id: str | None = None
    outcome: str | None = None
    effort: str | None = None
    next_action: str | None = None

    @property
    def defined(self) -> bool:
        """A task is only 'defined' once all four Tier 1 fields are filled in."""
        return bool(self.goal_id and self.outcome and self.effort and self.next_action)

    @property
    def oversized(self) -> bool:
        return is_oversized(self.effort)


def is_oversized(effort: str | None) -> bool:
    return bool(effort) and effort in OVERSIZED


def today() -> str:
    return date.today().isoformat()


def add_days(date_str: str, delta: int) -> str:
    return (date.fromisoformat(date_str) + timedelta(days=delta)).isoformat()


def validate_task(
    *, title: str, goal_id: str | None, outcome: str, effort: str | None,
    next_action: str, category: str,
) -> list[str]:
    """Return the list of reasons this task is not acceptable, empty if fine.

    Same four required fields the web form enforced, plus the board/oversize rule.
    """
    problems = []
    if not title.strip():
        problems.append("title is required")
    if not goal_id:
        problems.append("a goal is required")
    if not outcome.strip():
        problems.append("outcome (definition of done) is required")
    if not effort:
        problems.append("effort is required")
    elif effort not in EFFORT_KEYS:
        problems.append(f"effort must be one of: {', '.join(EFFORT_KEYS)}")
    if not next_action.strip():
        problems.append("next action is required")
    if category == "board" and is_oversized(effort):
        problems.append(
            "half-day or bigger is too large for the day board — split it, "
            "or file it under Long-term"
        )
    return problems
