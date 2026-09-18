"""Scriptable CLI over the same database the TUI uses.

    space-cli today                 # today's board, grouped by status
    space-cli ls --category longterm --status todo
    space-cli add "Title" --goal-id ... --outcome ... --effort 1h --next "..."
    space-cli done <id-prefix>
    space-cli goals
    space-cli stats
    space-cli export > backup.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import db
from .model import EFFORT_LABELS, STATUS_KEYS, STATUS_LABELS, today, validate_task

DIM, ACC, OK, WARN, OFF = "\033[2m", "\033[33m", "\033[32m", "\033[31m", "\033[0m"


def resolve(conn, prefix: str):
    """Accept any unambiguous id prefix, the way git accepts short SHAs."""
    rows = conn.execute("select id, title from tasks where id like ?",
                        (prefix + "%",)).fetchall()
    if not rows:
        sys.exit(f"no task matching '{prefix}'")
    if len(rows) > 1:
        sys.exit(f"'{prefix}' matches {len(rows)} tasks — use a longer prefix")
    return rows[0]["id"]


def show(t, titles, plain=False):
    color = {"todo": DIM, "doing": ACC, "done": OK}[t.status]
    if plain:
        color = OFF
    flag = "" if t.defined else f" {WARN}[undefined]{OFF}"
    meta = " · ".join(filter(None, [
        EFFORT_LABELS.get(t.effort or ""),
        titles.get(t.goal_id or ""),
        (t.due_time or "")[:5],
    ]))
    print(f"{color}{t.id[:8]}  {t.title}{OFF}{flag}")
    if meta:
        print(f"          {DIM}{meta}{OFF}")
    if t.outcome:
        print(f"          {DIM}done when: {t.outcome}{OFF}")


def cmd_ls(conn, a):
    titles = db.goal_titles(conn)
    items = db.tasks(conn, category=a.category, status=a.status,
                     due_date=a.date, goal_id=a.goal_id)
    if a.json:
        print(json.dumps([asdict(t) for t in items], indent=2))
        return
    for t in items:
        show(t, titles, a.plain)
    if not items:
        print(f"{DIM}nothing here{OFF}")


def cmd_today(conn, a):
    titles = db.goal_titles(conn)
    day = a.date or today()
    print(f"{ACC}{day}{OFF}")
    for s in STATUS_KEYS:
        items = [t for t in db.tasks(conn, category="board", due_date=day)
                 if t.status == s]
        print(f"\n{STATUS_LABELS[s]} ({len(items)})")
        for t in items:
            show(t, titles, a.plain)


def cmd_add(conn, a):
    problems = validate_task(
        title=a.title, goal_id=a.goal_id, outcome=a.outcome or "",
        effort=a.effort, next_action=a.next_action or "",
        category=a.category)
    if problems:
        for p in problems:
            print(f"{WARN}✗ {p}{OFF}", file=sys.stderr)
        sys.exit(1)
    tid = db.add_task(
        conn, title=a.title, goal_id=a.goal_id, outcome=a.outcome,
        effort=a.effort, next_action=a.next_action, category=a.category,
        due_date=a.date or (None if a.category == "longterm" else today()),
        due_time=a.time, description=a.description or "")
    print(tid[:8])


def cmd_status(conn, a):
    tid = resolve(conn, a.id)
    db.set_status(conn, tid, a.status)
    print(f"{tid[:8]} → {STATUS_LABELS[a.status]}")


def cmd_rm(conn, a):
    tid = resolve(conn, a.id)
    db.delete(conn, "tasks", tid)
    print(f"deleted {tid[:8]}")


def cmd_goals(conn, a):
    for g in db.goals(conn, include_archived=a.all):
        items = db.tasks(conn, goal_id=g.id)
        done = sum(t.status == "done" for t in items)
        tail = f" · by {g.target_date}" if g.target_date else ""
        print(f"{ACC}{g.id[:8]}{OFF}  {g.title}  {DIM}{done}/{len(items)} done{tail}{OFF}")


def cmd_goal_add(conn, a):
    print(db.add_goal(conn, a.title, a.description or "", a.date)[:8])


def cmd_stats(conn, a):
    row = conn.execute("""
        select count(*) total,
               sum(status = 'done') done,
               sum(status = 'doing') doing,
               sum(goal_id is null or outcome is null
                   or effort is null or next_action is null) undefined
          from tasks""").fetchone()
    print(f"tasks     {row['total']}")
    print(f"done      {row['done']}")
    print(f"doing     {row['doing']}")
    print(f"undefined {row['undefined']}")
    print(f"goals     {len(db.goals(conn))}")
    print(f"db        {db.db_path()}")


def cmd_export(conn, a):
    json.dump(
        {"goals": [asdict(g) for g in db.goals(conn, include_archived=True)],
         "tasks": [asdict(t) for t in db.tasks(conn)]},
        sys.stdout, indent=2)
    print()


def build_parser():
    # Shared flags live on a parent parser so they work on either side of the
    # subcommand: `space-cli --plain today` and `space-cli today --plain`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--plain", action="store_true", help="no ANSI color")

    p = argparse.ArgumentParser(prog="space-cli", description=__doc__,
                                parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    _sub = p.add_subparsers(dest="cmd", required=True)

    class sub:                      # every subparser inherits the common flags
        @staticmethod
        def add_parser(name, **kw):
            return _sub.add_parser(name, parents=[common], **kw)

    t = sub.add_parser("today", help="the day board")
    t.add_argument("--date")
    t.set_defaults(fn=cmd_today)

    ls = sub.add_parser("ls", help="list tasks")
    ls.add_argument("--category", choices=["board", "longterm"])
    ls.add_argument("--status", choices=STATUS_KEYS)
    ls.add_argument("--date")
    ls.add_argument("--goal-id")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=cmd_ls)

    a = sub.add_parser("add", help="add a task (all four fields required)")
    a.add_argument("title")
    a.add_argument("--goal-id", required=True)
    a.add_argument("--outcome", required=True)
    a.add_argument("--effort", required=True)
    a.add_argument("--next", dest="next_action", required=True)
    a.add_argument("--category", default="board", choices=["board", "longterm"])
    a.add_argument("--date")
    a.add_argument("--time")
    a.add_argument("--description")
    a.set_defaults(fn=cmd_add)

    for name, status in (("done", "done"), ("doing", "doing"), ("todo", "todo")):
        s = sub.add_parser(name, help=f"mark a task {status}")
        s.add_argument("id")
        s.set_defaults(fn=cmd_status, status=status)

    r = sub.add_parser("rm", help="delete a task")
    r.add_argument("id")
    r.set_defaults(fn=cmd_rm)

    g = sub.add_parser("goals", help="list goals")
    g.add_argument("--all", action="store_true", help="include archived")
    g.set_defaults(fn=cmd_goals)

    ga = sub.add_parser("goal-add", help="add a goal")
    ga.add_argument("title")
    ga.add_argument("--description")
    ga.add_argument("--date")
    ga.set_defaults(fn=cmd_goal_add)

    sub.add_parser("stats", help="counts").set_defaults(fn=cmd_stats)
    sub.add_parser("export", help="dump everything as JSON").set_defaults(fn=cmd_export)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "plain", False):
        globals().update(DIM="", ACC="", OK="", WARN="", OFF="")
    conn = db.connect()
    args.fn(conn, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
