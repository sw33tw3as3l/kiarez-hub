"""Scriptable CLI over the same database the TUI uses.

    space-cli c "something I thought of"     # capture, no fields
    space-cli today
    space-cli inbox
    space-cli tree                           # the whole forest
    space-cli node-add Scoring --parent paycheck
    space-cli define 4f2a --goal scoring --outcome "..." --kind ship \
                          --estimate 1h --next "..."
    space-cli start 4f2a / done 4f2a
    space-cli shipped "the grade endpoint is live"
    space-cli focus            # where today's hours went
    space-cli review           # stale work, estimate accuracy
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import db
from .model import (
    ESTIMATE_KEYS, ESTIMATE_LABELS, KIND_KEYS, KIND_LABELS, NAGGING_ROLLS,
    STALE_DAYS, STATUS_KEYS, STATUS_LABELS, add_days, can_start, fmt_minutes,
    ship_ratio, today,
)

DIM, ACC, OK, WARN, OFF = "\033[2m", "\033[33m", "\033[32m", "\033[31m", "\033[0m"


def plain():
    globals().update(DIM="", ACC="", OK="", WARN="", OFF="")


def resolve(conn, prefix: str) -> str:
    """Any unambiguous id prefix, the way git takes short SHAs."""
    rows = conn.execute("select id from tasks where id like ?",
                        (prefix + "%",)).fetchall()
    if not rows:
        sys.exit(f"no task matching '{prefix}'")
    if len(rows) > 1:
        sys.exit(f"'{prefix}' matches {len(rows)} tasks — use a longer prefix")
    return rows[0]["id"]


def resolve_node(conn, text: str) -> str:
    """Match a node by id prefix or by a unique piece of its name."""
    rows = conn.execute(
        "select id, name from nodes where id like ? or lower(name) like ?",
        (text + "%", f"%{text.lower()}%")).fetchall()
    if not rows:
        sys.exit(f"no node matching '{text}' — see `space-cli tree`")
    if len(rows) > 1:
        sys.exit("'%s' matches: %s" % (text, ", ".join(r["name"] for r in rows)))
    return rows[0]["id"]


def show(t, paths):
    color = {"todo": DIM, "doing": ACC, "done": OK}[t.status]
    print(f"{color}{t.id[:8]}  {t.title}{OFF}")
    if not t.defined:
        print(f"          {WARN}needs {', '.join(t.missing)}{OFF}")
        return
    bits = [KIND_LABELS[t.kind], ESTIMATE_LABELS[t.estimate],
            paths.get(t.node_id, "—")]
    if t.actual_minutes:
        bits.append(f"actual {fmt_minutes(t.actual_minutes)}")
    if t.rolls:
        bits.append(f"rolled {t.rolls}×")
    print(f"          {DIM}{' · '.join(bits)}{OFF}")
    if t.outcome:
        print(f"          {DIM}done when: {t.outcome}{OFF}")


def cmd_capture(conn, a):
    print(db.capture(conn, " ".join(a.text))[:8])


def cmd_today(conn, a):
    day = a.date or today()
    db.roll_forward(conn)
    items = db.tasks(conn, day=day)
    paths = db.node_paths(conn)
    shipped, done = ship_ratio(items)
    mins = db.usage_total(conn, day) // 60
    log = db.day_log(conn, day)

    print(f"{ACC}{day}{OFF}   ship {shipped}/{done}   "
          f"distraction {fmt_minutes(mins)}")
    print(f"{DIM}shipped: {log.shipped or 'not logged'}{OFF}")
    for s in STATUS_KEYS:
        group = [t for t in items if t.status == s]
        print(f"\n{STATUS_LABELS[s]} ({len(group)})")
        for t in group:
            show(t, paths)


def cmd_inbox(conn, a):
    paths = db.node_paths(conn)
    items = db.tasks(conn, inbox=True)
    for t in items:
        show(t, paths)
    if not items:
        print(f"{DIM}inbox empty{OFF}")


def cmd_ls(conn, a):
    node = resolve_node(conn, a.goal) if a.goal else None
    items = (db.subtree_tasks(conn, node) if node and a.deep else
             db.tasks(conn, day=a.date if a.date else "__any__",
                      status=a.status, node_id=node))
    if a.json:
        print(json.dumps([asdict(t) for t in items], indent=2))
        return
    paths = db.node_paths(conn)
    for t in items:
        show(t, paths)


def cmd_define(conn, a):
    tid = resolve(conn, a.id)
    fields = {}
    if a.goal:
        fields["node_id"] = resolve_node(conn, a.goal)
    for key, val in (("outcome", a.outcome), ("next_action", a.next_action),
                     ("kind", a.kind), ("estimate", a.estimate),
                     ("title", a.title)):
        if val:
            fields[key] = val
    db.update_task(conn, tid, **fields)
    t = db.task(conn, tid)
    print(f"{tid[:8]} {'defined' if t.defined else 'still needs ' + ', '.join(t.missing)}")


def cmd_status(conn, a):
    tid = resolve(conn, a.id)
    t = db.task(conn, tid)
    if a.status == "doing":
        blockers = can_start(t)
        if blockers:
            sys.exit(f"{WARN}can't start: {', '.join(blockers)}{OFF}\n"
                     f"run: space-cli define {tid[:8]} ...")
    db.set_status(conn, tid, a.status)
    print(f"{tid[:8]} → {STATUS_LABELS[a.status]}")


def cmd_schedule(conn, a):
    tid = resolve(conn, a.id)
    day = None if a.inbox else (a.date or today())
    if day:
        blockers = can_start(db.task(conn, tid))
        if blockers:
            sys.exit(f"{WARN}define it first: {', '.join(blockers)}{OFF}")
    db.schedule(conn, tid, day)
    print(f"{tid[:8]} → {day or 'inbox'}")


def cmd_rm(conn, a):
    tid = resolve(conn, a.id)
    db.delete(conn, "tasks", tid)
    print(f"deleted {tid[:8]}")


def cmd_tree(conn, a):
    t = db.tree(conn)
    if not t.nodes:
        print(f"{DIM}empty — space-cli node-add PayCheck{OFF}")
        return
    for node, depth in t.walk():
        sub = db.subtree_tasks(conn, node.id)
        shipped, finished = ship_ratio(sub)
        open_now = sum(x.status != "done" for x in sub)
        leaf = t.is_leaf(node.id)
        name = ("  " * depth) + ("" if leaf else "▾ ") + node.name
        print(f"{ACC}{node.id[:8]}{OFF}  {name:44} "
              f"{DIM}{open_now} open · {shipped}/{finished} shipped"
              f"{'' if leaf else ' (subtree)'}{OFF}")


def cmd_node_add(conn, a):
    parent = resolve_node(conn, a.parent) if a.parent else None
    print(db.add_node(conn, " ".join(a.name), parent)[:8])


def cmd_node_mv(conn, a):
    nid = resolve_node(conn, a.id)
    parent = None if a.root else resolve_node(conn, a.parent)
    err = db.move_node(conn, nid, parent)
    sys.exit(err) if err else print(f"{nid[:8]} moved")


def cmd_node_rm(conn, a):
    nid = resolve_node(conn, a.id)
    t = db.tree(conn)
    below, tasks_hit = t.descendants(nid), db.subtree_tasks(conn, nid)
    db.delete(conn, "nodes", nid)
    print(f"deleted {nid[:8]}"
          + (f" and {len(below)} node(s) below" if below else "")
          + (f"; {len(tasks_hit)} task(s) lost their goal" if tasks_hit else ""))


def cmd_shipped(conn, a):
    day = a.date or today()
    text = " ".join(a.text) if a.text else ""
    if not text:
        print(db.day_log(conn, day).shipped or "not logged")
        return
    db.log_shipped(conn, day, text)
    print(f"logged for {day}: {text}")


def cmd_focus(conn, a):
    day = a.date or today()
    rows = db.usage(conn, day)
    if not rows:
        print(f"{DIM}nothing recorded for {day} — is space-track running?{OFF}")
        return
    for app, label, secs in rows:
        mins = secs // 60
        bar = "█" * min(40, mins // 5)
        print(f"{label:14} {fmt_minutes(mins):>7}  {WARN if mins >= 60 else DIM}{bar}{OFF}")
    print(f"{DIM}total {fmt_minutes(db.usage_total(conn, day) // 60)}{OFF}")


def cmd_watch(conn, a):
    if a.remove:
        db.set_watch(conn, a.remove, None)
        print(f"stopped watching {a.remove}")
    elif a.add:
        db.set_watch(conn, a.add, a.label or a.add)
        print(f"watching {a.add}")
    for app, label in db.watchlist(conn):
        print(f"{label:14} {DIM}{app}{OFF}")


def cmd_review(conn, a):
    print(f"{ACC}Distraction, last 7 days{OFF}")
    totals = {}
    for i in range(7):
        for app, label, secs in db.usage(conn, add_days(today(), -i)):
            totals[label] = totals.get(label, 0) + secs
    for label, secs in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"  {label:14} {fmt_minutes(secs // 60)}")
    if not totals:
        print(f"  {DIM}nothing recorded{OFF}")

    print(f"\n{ACC}Estimate vs actual{OFF}")
    finished = [t for t in db.tasks(conn)
                if t.status == "done" and t.estimate_minutes and t.doing_seconds]
    if finished:
        ratios = [t.actual_minutes / t.estimate_minutes for t in finished]
        print(f"  {len(finished)} timed tasks · you take "
              f"{sum(ratios) / len(ratios):.1f}× your estimate")
    else:
        print(f"  {DIM}no finished timed tasks yet{OFF}")

    print(f"\n{ACC}Needs a decision{OFF}")
    rotting = [(t, f"rolled {t.rolls}×" if t.rolls >= NAGGING_ROLLS
                else f"untouched {t.stale_days()}d")
               for t in db.tasks(conn)
               if t.status != "done" and (t.rolls >= NAGGING_ROLLS
                                          or t.stale_days() >= STALE_DAYS)]
    for t, why in rotting:
        print(f"  {t.id[:8]}  {t.title[:50]:52} {WARN}{why}{OFF}")
    if not rotting:
        print(f"  {OK}nothing rotting{OFF}")


def cmd_stats(conn, a):
    row = conn.execute("""
        select count(*) total, coalesce(sum(status='done'),0) done,
               coalesce(sum(status='doing'),0) doing,
               coalesce(sum(day is null and status!='done'),0) inbox,
               coalesce(sum(kind='ship' and status='done'),0) shipped
          from tasks""").fetchone()
    print(f"tasks   {row['total']}")
    print(f"done    {row['done']} ({row['shipped']} shipped)")
    print(f"doing   {row['doing']}")
    print(f"inbox   {row['inbox']}")
    print(f"nodes   {len(db.nodes(conn))}")
    print(f"db      {db.db_path()}")


def cmd_export(conn, a):
    json.dump({"nodes": [asdict(x) for x in db.nodes(conn)],
               "tasks": [asdict(t) for t in db.tasks(conn)],
               "days": {d: s for d, s in db.logged_days(conn).items()}},
              sys.stdout, indent=2)
    print()


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS matters: without it a subparser that didn't see --plain writes
    # its own False over the value the top-level parser already set, so
    # `space-cli --plain today` would silently keep the color.
    common.add_argument("--plain", action="store_true",
                        default=argparse.SUPPRESS, help="no ANSI color")
    p = argparse.ArgumentParser(prog="space-cli", description=__doc__,
                                parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    _sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        return _sub.add_parser(name, parents=[common], **kw)

    for name in ("capture", "c"):
        s = add(name, help="write something down — title only")
        s.add_argument("text", nargs="+")
        s.set_defaults(fn=cmd_capture)

    s = add("today", help="the day board")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_today)

    add("inbox", help="captured, not yet scheduled").set_defaults(fn=cmd_inbox)

    s = add("ls", help="list tasks")
    s.add_argument("--date")
    s.add_argument("--status", choices=STATUS_KEYS)
    s.add_argument("--goal", help="node id prefix or part of its name")
    s.add_argument("--deep", action="store_true",
                   help="with --goal: include everything below it")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ls)

    s = add("define", help="fill in what a task needs before it can start")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--goal")
    s.add_argument("--outcome")
    s.add_argument("--next", dest="next_action")
    s.add_argument("--kind", choices=KIND_KEYS)
    s.add_argument("--estimate", choices=ESTIMATE_KEYS)
    s.set_defaults(fn=cmd_define)

    for name, status in (("start", "doing"), ("done", "done"), ("stop", "todo")):
        s = add(name, help=f"mark a task {status}")
        s.add_argument("id")
        s.set_defaults(fn=cmd_status, status=status)

    s = add("schedule", help="put a task on a day, or back in the inbox")
    s.add_argument("id")
    s.add_argument("--date")
    s.add_argument("--inbox", action="store_true")
    s.set_defaults(fn=cmd_schedule)

    s = add("rm", help="delete a task")
    s.add_argument("id")
    s.set_defaults(fn=cmd_rm)

    add("tree", help="the whole forest").set_defaults(fn=cmd_tree)

    s = add("node-add", help="add a node (a root, or a child of --parent)")
    s.add_argument("name", nargs="+")
    s.add_argument("--parent")
    s.set_defaults(fn=cmd_node_add)

    s = add("node-mv", help="reparent a node")
    s.add_argument("id")
    s.add_argument("--parent")
    s.add_argument("--root", action="store_true")
    s.set_defaults(fn=cmd_node_mv)

    s = add("node-rm", help="delete a node and everything under it")
    s.add_argument("id")
    s.set_defaults(fn=cmd_node_rm)

    s = add("shipped", help="log (or read) what shipped on a day")
    s.add_argument("text", nargs="*")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_shipped)

    s = add("focus", help="where the day's hours went")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_focus)

    s = add("watch", help="manage the distraction watchlist")
    s.add_argument("--add", metavar="APP_CLASS")
    s.add_argument("--label")
    s.add_argument("--remove", metavar="APP_CLASS")
    s.set_defaults(fn=cmd_watch)

    add("review", help="stale work, estimate accuracy, distraction").set_defaults(fn=cmd_review)
    add("stats", help="counts").set_defaults(fn=cmd_stats)
    add("export", help="dump everything as JSON").set_defaults(fn=cmd_export)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "plain", False):
        plain()
    args.fn(db.connect(), args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
