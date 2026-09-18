"""SQLite storage. One file, no server, no network.

Lives at ~/.kiarez-space/data.db unless KIAREZ_SPACE_DB says otherwise.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

from .model import Day, Node, Task, Tree, add_days, today, utc_now

SCHEMA = """
-- A forest. parent_id null means a root. A node with children reads as an
-- area, a leaf reads as a goal; that is derived at display time, never stored.
create table if not exists nodes (
  id         text primary key,
  parent_id  text references nodes(id) on delete cascade,
  name       text not null,
  position   integer not null default 0,
  created_at text not null
);

create index if not exists nodes_parent_idx on nodes (parent_id);

create table if not exists tasks (
  id            text primary key,
  title         text not null,
  node_id       text references nodes(id) on delete set null,
  day           text,                      -- null = inbox
  status        text not null default 'todo'
                  check (status in ('todo','doing','done')),
  kind          text check (kind in ('ship','support')),
  outcome       text,
  next_action   text,
  estimate      text check (estimate in
                  ('15m','30m','1h','2h','half_day','day_plus')),
  doing_seconds integer not null default 0,
  doing_since   text,
  rolls         integer not null default 0,
  position      integer not null default 0,
  created_at    text not null,
  touched_at    text not null,
  done_at       text
);

create index if not exists tasks_day_idx    on tasks (day);
create index if not exists tasks_node_idx   on tasks (node_id);
create index if not exists tasks_status_idx on tasks (status);

-- One row per day: the honest end-of-day answer to "what shipped?"
create table if not exists days (
  date      text primary key,
  shipped   text,
  logged_at text
);

-- Focused seconds per app per day, written by the tracker.
create table if not exists app_usage (
  date    text not null,
  app     text not null,
  seconds integer not null default 0,
  primary key (date, app)
);

-- Apps worth counting against you.
create table if not exists watchlist (
  app   text primary key,
  label text not null
);
"""

DEFAULT_WATCHLIST = [
    ("org.telegram.desktop", "Telegram"),
    ("google-chrome", "Chrome"),
]


def db_path() -> Path:
    env = os.environ.get("KIAREZ_SPACE_DB")
    return Path(env).expanduser() if env else Path.home() / ".kiarez-space" / "data.db"


def connect(path=None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")     # tracker writes concurrently
    _guard_old_schema(conn, p)
    conn.executescript(SCHEMA)
    if not conn.execute("select count(*) from watchlist").fetchone()[0]:
        conn.executemany("insert into watchlist (app, label) values (?,?)",
                         DEFAULT_WATCHLIST)
        conn.commit()
    return conn


def _guard_old_schema(conn, path: Path) -> None:
    """Fail clearly on a database from the pre-areas design.

    `create table if not exists` silently keeps an old table, and the first
    query against a missing column is a baffling error a long way from here.
    """
    row = conn.execute("select name from sqlite_master where type = 'table' "
                       "and name = 'tasks'").fetchone()
    if not row:
        return
    cols = {r["name"] for r in conn.execute("pragma table_info(tasks)")}
    if "day" not in cols or "node_id" not in cols:
        raise SystemExit(
            f"{path} uses an older schema than this version.\n"
            f"Back it up and remove it, then start fresh:\n"
            f"  mv {path} {path}.old")


def now() -> str:
    return utc_now().isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


# --- reads ------------------------------------------------------------------

def _task(row) -> Task:
    return Task(**dict(row))


def nodes(conn) -> list[Node]:
    return [Node(**dict(r)) for r in
            conn.execute("select * from nodes order by position, created_at")]


def tree(conn) -> Tree:
    items = nodes(conn)
    children: dict[str | None, list[Node]] = {}
    for n in items:
        children.setdefault(n.parent_id, []).append(n)
    return Tree(items, children)


def node_paths(conn) -> dict[str, str]:
    """{id: 'PayCheck › Scoring › Grade endpoint'} for every node."""
    t = tree(conn)
    return {n.id: t.path(n.id) for n in t.nodes}


def tasks(conn, *, day="__any__", status=None, node_id=None,
          inbox=False) -> list[Task]:
    sql, args = "select * from tasks where 1=1", []
    if inbox:
        sql += " and day is null and status != 'done'"
    elif day != "__any__":
        sql += " and day is ?" if day is None else " and day = ?"
        args.append(day)
    if status:
        sql += " and status = ?"
        args.append(status)
    if node_id:
        sql += " and node_id = ?"
        args.append(node_id)
    sql += " order by position, created_at"
    return [_task(r) for r in conn.execute(sql, args)]


def task(conn, task_id: str) -> Task | None:
    row = conn.execute("select * from tasks where id = ?", (task_id,)).fetchone()
    return _task(row) if row else None


def day_log(conn, date_str: str) -> Day:
    row = conn.execute("select * from days where date = ?", (date_str,)).fetchone()
    return Day(**dict(row)) if row else Day(date=date_str)


def logged_days(conn) -> dict[str, str]:
    return {r["date"]: (r["shipped"] or "")
            for r in conn.execute("select date, shipped from days")}


def counts_by_day(conn, days: list[str]) -> dict[str, tuple[int, int]]:
    if not days:
        return {}
    marks = ",".join("?" * len(days))
    rows = conn.execute(
        f"""select day, sum(status = 'done') done, count(*) total
              from tasks where day in ({marks}) group by day""", days)
    return {r["day"]: (r["done"], r["total"]) for r in rows}


def usage(conn, date_str: str) -> list[tuple[str, str, int]]:
    """[(app, label, seconds)] for watched apps on a day, worst first."""
    rows = conn.execute(
        """select u.app, coalesce(w.label, u.app) label, u.seconds
             from app_usage u left join watchlist w on w.app = u.app
            where u.date = ? order by u.seconds desc""", (date_str,))
    return [(r["app"], r["label"], r["seconds"]) for r in rows]


def usage_total(conn, date_str: str) -> int:
    row = conn.execute("select coalesce(sum(seconds), 0) s from app_usage "
                       "where date = ?", (date_str,)).fetchone()
    return row["s"]


def watchlist(conn) -> list[tuple[str, str]]:
    return [(r["app"], r["label"]) for r in
            conn.execute("select app, label from watchlist order by label")]


# --- writes -----------------------------------------------------------------

def _next_position(conn, where="", args=()) -> int:
    return conn.execute(
        f"select coalesce(max(position), -1) + 1 p from tasks {where}",
        args).fetchone()["p"]


def add_node(conn, name: str, parent_id: str | None = None) -> str:
    nid = new_id()
    pos = conn.execute(
        "select coalesce(max(position), -1) + 1 p from nodes where parent_id is ?",
        (parent_id,)).fetchone()["p"]
    conn.execute("insert into nodes (id, parent_id, name, position, created_at) "
                 "values (?,?,?,?,?)", (nid, parent_id, name.strip(), pos, now()))
    conn.commit()
    return nid


def rename_node(conn, node_id: str, name: str) -> None:
    conn.execute("update nodes set name = ? where id = ?", (name.strip(), node_id))
    conn.commit()


def move_node(conn, node_id: str, parent_id: str | None) -> str | None:
    """Reparent a node. Returns an error string, or None on success."""
    if node_id == parent_id:
        return "a node can't be its own parent"
    t = tree(conn)
    if parent_id and parent_id in {d.id for d in t.descendants(node_id)}:
        return "can't move a node inside its own subtree"
    pos = conn.execute(
        "select coalesce(max(position), -1) + 1 p from nodes where parent_id is ?",
        (parent_id,)).fetchone()["p"]
    conn.execute("update nodes set parent_id = ?, position = ? where id = ?",
                 (parent_id, pos, node_id))
    conn.commit()
    return None


def subtree_tasks(conn, node_id: str) -> list[Task]:
    """Tasks on this node and everything under it."""
    t = tree(conn)
    ids = [node_id] + [d.id for d in t.descendants(node_id)]
    marks = ",".join("?" * len(ids))
    return [_task(r) for r in conn.execute(
        f"select * from tasks where node_id in ({marks}) "
        f"order by position, created_at", ids)]


def capture(conn, title: str, *, node_id=None, day=None, **rest) -> str:
    """Write something down. Title is the only thing required."""
    tid = new_id()
    stamp = now()
    conn.execute(
        """insert into tasks
             (id, title, node_id, day, status, kind, outcome, next_action,
              estimate, position, created_at, touched_at)
           values (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, title.strip(), node_id, day, rest.get("status", "todo"),
         rest.get("kind"), (rest.get("outcome") or "").strip() or None,
         (rest.get("next_action") or "").strip() or None,
         rest.get("estimate"),
         _next_position(conn, "where day is ?", (day,)), stamp, stamp))
    conn.commit()
    return tid


def update_task(conn, task_id: str, **fields) -> None:
    if not fields:
        return
    fields["touched_at"] = now()
    sets = ",".join(f"{k} = ?" for k in fields)
    conn.execute(f"update tasks set {sets} where id = ?",
                 [*fields.values(), task_id])
    conn.commit()


def delete(conn, table: str, row_id: str) -> None:
    key = "date" if table == "days" else "id"
    conn.execute(f"delete from {table} where {key} = ?", (row_id,))
    conn.commit()


def set_status(conn, task_id: str, status: str) -> None:
    """Status changes are also the clock: time is counted while in 'doing'."""
    t = task(conn, task_id)
    if not t or t.status == status:
        return
    fields = {"status": status}
    if t.status == "doing" and t.doing_since:        # leaving doing: bank it
        from .model import parse
        fields["doing_seconds"] = t.doing_seconds + max(
            0, int((utc_now() - parse(t.doing_since)).total_seconds()))
        fields["doing_since"] = None
    if status == "doing":
        fields["doing_since"] = now()
    fields["done_at"] = now() if status == "done" else None
    update_task(conn, task_id, **fields)


def schedule(conn, task_id: str, day: str | None) -> None:
    update_task(conn, task_id, day=day)


def reorder(conn, task_id: str, delta: int) -> None:
    t = task(conn, task_id)
    if not t:
        return
    siblings = [x for x in tasks(conn, day=t.day) if x.status == t.status]
    idx = next((i for i, x in enumerate(siblings) if x.id == task_id), None)
    if idx is None or not 0 <= idx + delta < len(siblings):
        return
    siblings[idx], siblings[idx + delta] = siblings[idx + delta], siblings[idx]
    for i, x in enumerate(siblings):
        conn.execute("update tasks set position = ? where id = ?", (i, x.id))
    conn.commit()


def log_shipped(conn, date_str: str, text: str) -> None:
    conn.execute("""insert into days (date, shipped, logged_at) values (?,?,?)
                    on conflict(date) do update set shipped = excluded.shipped,
                                                    logged_at = excluded.logged_at""",
                 (date_str, text.strip(), now()))
    conn.commit()


def add_usage(conn, date_str: str, app: str, seconds: int) -> None:
    conn.execute("""insert into app_usage (date, app, seconds) values (?,?,?)
                    on conflict(date, app) do update
                      set seconds = seconds + excluded.seconds""",
                 (date_str, app, int(seconds)))
    conn.commit()


def set_watch(conn, app: str, label: str | None) -> None:
    if label is None:
        conn.execute("delete from watchlist where app = ?", (app,))
    else:
        conn.execute("""insert into watchlist (app, label) values (?,?)
                        on conflict(app) do update set label = excluded.label""",
                     (app, label))
    conn.commit()


# --- the daily roll ---------------------------------------------------------

def roll_forward(conn, upto: str | None = None) -> int:
    """Move unfinished work from past days onto today, counting the rolls.

    Runs on every start. A task that has rolled many times is not a task you
    are doing; the review view says so.
    """
    upto = upto or today()
    rows = conn.execute(
        "select id from tasks where day is not null and day < ? "
        "and status != 'done'", (upto,)).fetchall()
    if not rows:
        return 0
    conn.execute(
        "update tasks set day = ?, rolls = rolls + 1 "
        "where day is not null and day < ? and status != 'done'", (upto, upto))
    conn.commit()
    return len(rows)


def close_out(conn, date_str: str) -> None:
    """Stop the clock on anything left running from an earlier day."""
    for t in conn.execute("select id from tasks where doing_since is not null "
                          "and day < ?", (date_str,)).fetchall():
        set_status(conn, t["id"], "todo")
