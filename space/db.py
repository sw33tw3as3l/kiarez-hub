"""SQLite storage layer. One file, no server, no network.

The database lives at ~/.kiarez-space/data.db unless KIAREZ_SPACE_DB says
otherwise. Schema matches the old Postgres tables field for field.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .model import Goal, Task

SCHEMA = """
create table if not exists goals (
  id          text primary key,
  title       text not null,
  description text,
  target_date text,
  position    integer not null default 0,
  archived    integer not null default 0,
  created_at  text not null
);

create table if not exists tasks (
  id          text primary key,
  title       text not null,
  description text,
  status      text not null default 'todo'
                check (status in ('todo','doing','done')),
  category    text not null default 'board'
                check (category in ('board','longterm')),
  due_date    text,
  due_time    text,
  position    integer not null default 0,
  created_at  text not null,
  goal_id     text references goals(id) on delete set null,
  outcome     text,
  effort      text check (effort in
                ('15m','30m','1h','2h','half_day','day_plus')),
  next_action text
);

create index if not exists tasks_goal_id_idx   on tasks (goal_id);
create index if not exists tasks_due_date_idx  on tasks (due_date);
create index if not exists tasks_category_idx  on tasks (category);
"""


def db_path() -> Path:
    env = os.environ.get("KIAREZ_SPACE_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".kiarez-space" / "data.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


# --- reads ------------------------------------------------------------------

def _task(row: sqlite3.Row) -> Task:
    d = dict(row)
    return Task(**d)


def _goal(row: sqlite3.Row) -> Goal:
    d = dict(row)
    d["archived"] = bool(d["archived"])
    return Goal(**d)


def goals(conn, include_archived: bool = False) -> list[Goal]:
    sql = "select * from goals"
    if not include_archived:
        sql += " where archived = 0"
    sql += " order by position, created_at"
    return [_goal(r) for r in conn.execute(sql)]


def goal_titles(conn) -> dict[str, str]:
    return {g.id: g.title for g in goals(conn, include_archived=True)}


def tasks(
    conn,
    *,
    category: str | None = None,
    due_date: str | None = None,
    status: str | None = None,
    goal_id: str | None = None,
) -> list[Task]:
    sql, args = "select * from tasks where 1=1", []
    for col, val in (
        ("category", category),
        ("due_date", due_date),
        ("status", status),
        ("goal_id", goal_id),
    ):
        if val is not None:
            sql += f" and {col} = ?"
            args.append(val)
    sql += " order by position, created_at"
    return [_task(r) for r in conn.execute(sql, args)]


def task(conn, task_id: str) -> Task | None:
    row = conn.execute("select * from tasks where id = ?", (task_id,)).fetchone()
    return _task(row) if row else None


def counts_by_day(conn, days: list[str]) -> dict[str, tuple[int, int]]:
    """{day: (done, total)} for board tasks — feeds the calendar view."""
    if not days:
        return {}
    marks = ",".join("?" * len(days))
    rows = conn.execute(
        f"""select due_date,
                   sum(status = 'done') as done,
                   count(*)             as total
              from tasks
             where category = 'board' and due_date in ({marks})
             group by due_date""",
        days,
    )
    return {r["due_date"]: (r["done"], r["total"]) for r in rows}


# --- writes -----------------------------------------------------------------

def _next_position(conn, table: str, where: str = "", args=()) -> int:
    row = conn.execute(
        f"select coalesce(max(position), -1) + 1 as p from {table} {where}", args
    ).fetchone()
    return row["p"]


def add_goal(conn, title: str, description: str = "", target_date: str | None = None) -> str:
    gid = new_id()
    conn.execute(
        "insert into goals (id, title, description, target_date, position, created_at)"
        " values (?,?,?,?,?,?)",
        (gid, title.strip(), description.strip() or None, target_date or None,
         _next_position(conn, "goals"), now()),
    )
    conn.commit()
    return gid


def add_task(conn, **fields) -> str:
    tid = new_id()
    cat = fields.get("category", "board")
    row = {
        "id": tid,
        "title": fields["title"].strip(),
        "description": (fields.get("description") or "").strip() or None,
        "status": fields.get("status", "todo"),
        "category": cat,
        "due_date": fields.get("due_date") or None,
        "due_time": fields.get("due_time") or None,
        "position": _next_position(conn, "tasks", "where category = ?", (cat,)),
        "created_at": now(),
        "goal_id": fields.get("goal_id") or None,
        "outcome": (fields.get("outcome") or "").strip() or None,
        "effort": fields.get("effort") or None,
        "next_action": (fields.get("next_action") or "").strip() or None,
    }
    cols = ",".join(row)
    conn.execute(f"insert into tasks ({cols}) values ({','.join('?' * len(row))})",
                 list(row.values()))
    conn.commit()
    return tid


def update(conn, table: str, row_id: str, **fields) -> None:
    if not fields:
        return
    sets = ",".join(f"{k} = ?" for k in fields)
    conn.execute(f"update {table} set {sets} where id = ?",
                 [*fields.values(), row_id])
    conn.commit()


def delete(conn, table: str, row_id: str) -> None:
    conn.execute(f"delete from {table} where id = ?", (row_id,))
    conn.commit()


def set_status(conn, task_id: str, status: str) -> None:
    update(conn, "tasks", task_id, status=status)


def reorder(conn, task_id: str, delta: int) -> None:
    """Swap a task with its neighbour inside its own column."""
    t = task(conn, task_id)
    if not t:
        return
    siblings = [
        x for x in tasks(conn, category=t.category, status=t.status)
        if x.due_date == t.due_date
    ]
    idx = next((i for i, x in enumerate(siblings) if x.id == task_id), None)
    if idx is None:
        return
    swap = idx + delta
    if not 0 <= swap < len(siblings):
        return
    siblings[idx], siblings[swap] = siblings[swap], siblings[idx]
    for i, x in enumerate(siblings):
        conn.execute("update tasks set position = ? where id = ?", (i, x.id))
    conn.commit()
