"""Scriptable CLI over the same database the TUI uses.

    space-cli c "something I thought of"     # capture, no fields
    space-cli today
    space-cli inbox
    space-cli tree                           # the whole forest
    space-cli node-add Scoring --parent paycheck
    space-cli define 4f2a --goal scoring --outcome "..." --kind ship \
                          --estimate 1h --next "..."
    space-cli start 4f2a / done 4f2a
    space-review                             # the day's two questions
    space-cli day                            # read them back
    space-cli focus            # where today's hours went
    space-cli review           # stale work, estimate accuracy
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import db
from .review import review_day
from .text import cols, ellipsis, pad
from .model import (
    ESTIMATE_MINUTES, estimate_accuracy, ESTIMATE_KEYS, ESTIMATE_LABELS,
    KIND_KEYS, KIND_LABELS, NAGGING_ROLLS, parse_duration,
    STALE_DAYS, STATUS_KEYS, STATUS_LABELS, add_days, can_start, fmt_minutes,
    ship_ratio, today,
)

DIM, ACC, OK, WARN, OFF = "\033[2m", "\033[33m", "\033[32m", "\033[31m", "\033[0m"

# Per-app colours, as chosen on the watchlist.
APP_COLORS = {"red": "\033[31m", "yellow": "\033[33m", "green": "\033[32m",
              "cyan": "\033[36m", "dim": "\033[2m"}


def app_color(name: str) -> str:
    return "" if not OFF else APP_COLORS.get(name, DIM)


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


def valid_date(text: str) -> str:
    """Reject anything that isn't a real YYYY-MM-DD.

    Without this a typo silently becomes a day with nothing on it, which
    reads exactly like a day on which you did nothing.
    """
    try:
        from datetime import date as _date
        return _date.fromisoformat(text).isoformat()
    except ValueError:
        sys.exit(f"'{text}' is not a date — use YYYY-MM-DD")


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
    day = valid_date(a.date) if a.date else today()
    db.roll_forward(conn)
    items = db.tasks(conn, day=day)
    paths = db.node_paths(conn)
    shipped, done = ship_ratio(items)
    mins = db.usage_total(conn, day) // 60
    log = db.day_log(conn, day)

    print(f"{ACC}{day}{OFF}   ship {shipped}/{done}   "
          f"distraction {fmt_minutes(mins)}")
    if log.answered:
        print(f"{DIM}did: {log.did}{OFF}")
        if log.not_done:
            print(f"{DIM}not: {log.not_done}{OFF}")
    else:
        print(f"{DIM}not answered{OFF}")
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
             db.tasks(conn, day=valid_date(a.date) if a.date else "__any__",
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
    day = None if a.inbox else (valid_date(a.date) if a.date else today())
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
        print(f"{ACC}{node.id[:8]}{OFF}  {pad(ellipsis(name, 44), 44)} "
              f"{DIM}{open_now} open · {shipped}/{finished} shipped"
              f"{'' if leaf else ' (subtree)'}{OFF}")


def cmd_node_add(conn, a):
    parent = resolve_node(conn, a.parent) if a.parent else None
    print(db.add_node(conn, " ".join(a.name), parent)[:8])


def cmd_node_mv(conn, a):
    if not a.root and not a.parent:
        sys.exit("say where it goes: --parent <node>, or --root")
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


def cmd_day(conn, a):
    """Read or write the day's two answers. Use `space-review` to be asked.

    With no --date this means the day still open for answering, which before
    04:00 is yesterday — the same day the board and the reminder mean.
    """
    day = valid_date(a.date) if a.date else review_day()
    log = db.day_log(conn, day)
    if (a.did or a.missed) and day != review_day():
        # The lock is the whole point of the daily question; the CLI must not
        # be a way around it.
        sys.exit(f"{day} is closed — only {review_day()} can still be answered")
    if not a.did and not a.missed:
        if not log.answered:
            print(f"{DIM}{day} not answered{OFF}")
            return
        print(f"{OK}did:{OFF} {log.did}")
        print(f"{WARN}not:{OFF} {log.not_done or '—'}")
        return
    db.log_day(conn, day, a.did or log.did, a.missed or log.not_done)
    print(f"logged for {day}")


def resolve_app(conn, text: str) -> tuple[str, str]:
    """Match a watched app by class or label, e.g. 'telegram'."""
    needle = text.lower()
    for app, label, _ in db.watchlist(conn):
        if needle in app.lower() or needle in label.lower():
            return app, label
    sys.exit(f"'{text}' is not watched — see `space-cli watch`")


def cmd_focus(conn, a):
    day = valid_date(a.date) if a.date else today()
    if a.app:
        return focus_detail(conn, resolve_app(conn, a.app), day, a.days)
    if a.week:
        return focus_matrix(conn, day, a.days)

    rows = db.usage(conn, day)
    if not rows:
        print(f"{DIM}nothing recorded for {day} — is space-track running?{OFF}")
        return
    peak = max(r[3] for r in rows) or 1
    for app, label, color, secs in rows:
        d = db.usage_detail(conn, app, day)
        mins = secs // 60
        bar = "█" * max(1, round(30 * secs / peak))
        extra = f"{d['opens']} checks · longest {fmt_minutes(d['longest'] // 60)}"
        tint = app_color(color)
        print(f"{tint}{pad(ellipsis(label, 14), 14)} {fmt_minutes(mins):>7}  "
              f"{bar:<30}{OFF} {DIM}{extra}{OFF}")
    total = db.usage_total(conn, day)
    red = db.usage_total(conn, day, color="red")
    print(f"{DIM}tracked {fmt_minutes(total // 60)}{OFF}"
          f"   {WARN}red {fmt_minutes(red // 60)}{OFF}")


def focus_matrix(conn, day, days):
    """One row per app, one column per day — the whole span at a glance."""
    from datetime import date as _date
    span = [add_days(day, -i) for i in range(days - 1, -1, -1)]
    matrix = db.usage_matrix(conn, span)
    if not matrix:
        print(f"{DIM}nothing recorded — is space-track running?{OFF}")
        return

    head = "".join(_date.fromisoformat(d).strftime("%a %d").rjust(8) for d in span)
    print(f"{DIM}{'app':<14}{head}{'total'.rjust(9)}{OFF}")
    for row in matrix:
        tint = app_color(row["color"])
        cells = "".join(
            (fmt_minutes(row['by_day'][d] // 60) if row["by_day"].get(d) else "·"
             ).rjust(8) for d in span)
        print(f"{tint}{pad(ellipsis(row['label'], 14), 14)}{cells}"
              f"{fmt_minutes(row['total'] // 60).rjust(9)}{OFF}")
    def day_total(d):
        secs = sum(r["by_day"].get(d, 0) for r in matrix)
        return fmt_minutes(secs // 60) if secs else "·"     # 0m is not "·"

    totals = "".join(day_total(d).rjust(8) for d in span)
    grand = sum(r["total"] for r in matrix)
    print(f"{DIM}{'all':<14}{totals}{fmt_minutes(grand // 60).rjust(9)}{OFF}")


def focus_detail(conn, app_label, day, days):
    """Everything known about one app: the interaction picture, not just time."""
    app, label = app_label
    d = db.usage_detail(conn, app, day)
    span = [add_days(day, -i) for i in range(days)]
    total = db.usage_range(conn, app, span)

    print(f"{ACC}{label} — {day}{OFF}")
    if not d["seconds"]:
        print(f"  {DIM}nothing recorded{OFF}")
    else:
        mins = d["seconds"] // 60
        print(f"  focused      {fmt_minutes(mins)}")
        print(f"  checks       {d['opens']}"
              f"{DIM}  (separate times you went to it){OFF}")
        print(f"  longest      {fmt_minutes(d['longest'] // 60)}"
              f"{DIM}  (single unbroken stretch){OFF}")
        print(f"  interactions {d['switches']}"
              f"{DIM}  (moves between chats/views inside it){OFF}")
        if d["opens"]:
            print(f"  per check    {fmt_minutes(mins // max(1, d['opens']))}")

    if d["hours"]:
        print(f"\n{ACC}By hour{OFF}")
        peak = max(d["hours"].values()) or 1
        for hour in sorted(d["hours"]):
            secs = d["hours"][hour]
            bar = "█" * max(1, round(30 * secs / peak))
            print(f"  {hour:02d}:00  {fmt_minutes(secs // 60):>6}  "
                  f"{WARN if secs >= 1800 else DIM}{bar}{OFF}")

    print(f"\n{ACC}Last {days} days{OFF}")
    print(f"  focused      {fmt_minutes(total['seconds'] // 60)}"
          f"{DIM}  ({fmt_minutes(total['seconds'] // 60 // days)}/day){OFF}")
    print(f"  checks       {total['opens']}"
          f"{DIM}  ({total['opens'] // days}/day){OFF}")
    print(f"  longest      {fmt_minutes(total['longest'] // 60)}")


def cmd_watch(conn, a):
    if a.remove:
        db.set_watch(conn, a.remove, None)
        print(f"stopped watching {a.remove}")
    elif a.add:
        db.set_watch(conn, a.add, a.label or a.add, a.color)
        print(f"watching {a.add}")
    for app, label, color in db.watchlist(conn):
        print(f"{app_color(color)}{label:14}{OFF} {DIM}{color:7} {app}{OFF}")


def cmd_review(conn, a):
    print(f"{ACC}Where the last 7 days went{OFF}  "
          f"{DIM}keyboard focus only — idle and locked screens excluded{OFF}")
    totals = {}
    for i in range(7):
        for app, label, color, secs in db.usage(conn, add_days(today(), -i)):
            prev = totals.get(label, (color, 0))[1]
            totals[label] = (color, prev + secs)
    for label, (color, secs) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        print(f"  {app_color(color)}{pad(ellipsis(label, 14), 14)} "
              f"{fmt_minutes(secs // 60)}{OFF}")
    if not totals:
        print(f"  {DIM}nothing recorded{OFF}")

    print(f"\n{ACC}Estimate vs actual{OFF}  {DIM}median per size{OFF}")
    accuracy = estimate_accuracy(db.tasks(conn))
    if not accuracy:
        print(f"  {DIM}nothing finished and timed yet{OFF}")
    for key in ESTIMATE_KEYS:
        if key not in accuracy:
            continue
        n, actual = accuracy[key]
        ratio = actual / ESTIMATE_MINUTES[key]
        tint = OK if 0.8 <= ratio <= 1.25 else (WARN if ratio > 1.75 else ACC)
        print(f"  {ESTIMATE_LABELS[key]:<9} → {fmt_minutes(round(actual)):>6}"
              f"  {tint}{ratio:.1f}×{OFF}  {DIM}n={n}{OFF}")

    print(f"\n{ACC}Needs a decision{OFF}")
    rotting = [(t, f"rolled {t.rolls}×" if t.rolls >= NAGGING_ROLLS
                else f"untouched {t.stale_days()}d")
               for t in db.tasks(conn)
               if t.status != "done" and (t.rolls >= NAGGING_ROLLS
                                          or t.stale_days() >= STALE_DAYS)]
    for t, why in rotting:
        print(f"  {t.id[:8]}  {pad(ellipsis(t.title, 50), 52)}{WARN}{why}{OFF}")
    if not rotting:
        print(f"  {OK}nothing rotting{OFF}")


def cmd_estimates(conn, a):
    """List or edit the sizes you estimate in."""
    if a.reset:
        db.reset_estimates(conn)
        print("scale reset to the defaults")
    if a.add:
        minutes = parse_duration(a.add)
        if not minutes:
            sys.exit(f"'{a.add}' is not a duration — try 45m, 1h30, 2d")
        key = a.key or a.add.strip().lower()
        db.add_estimate(conn, key, a.label or key, minutes)
        print(f"added {key} = {fmt_minutes(minutes)}")
    if a.remove:
        if a.remove not in ESTIMATE_LABELS:
            sys.exit(f"'{a.remove}' is not in the scale")
        if len(ESTIMATE_KEYS) <= 1:
            sys.exit("the scale needs at least one size")
        used = db.remove_estimate(conn, a.remove)
        print(f"removed {a.remove}"
              + (f" — {used} existing task(s) still carry it and keep it"
                 if used else ""))

    accuracy = estimate_accuracy(db.tasks(conn))
    for key in ESTIMATE_KEYS:
        n, actual = accuracy.get(key, (0, 0))
        planned = ESTIMATE_MINUTES[key]
        real = (f"  {DIM}actually {fmt_minutes(round(actual))} "
                f"({actual / planned:.1f}×, n={n}){OFF}") if n >= 2 else ""
        print(f"{ACC}{key:<10}{OFF} {fmt_minutes(planned):>7}{real}")
    orphans = {r["estimate"] for r in conn.execute(
        "select distinct estimate from tasks where estimate is not null")
        } - set(ESTIMATE_KEYS)
    for key in sorted(orphans):
        print(f"{DIM}{key:<10} (no longer in the scale, still on old tasks){OFF}")


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


# Every table that holds something you typed or something that was measured.
# heartbeat is deliberately absent: it says whether the tracker is alive now,
# which means nothing in a file.
EXPORT_TABLES = ["nodes", "tasks", "days", "weeks", "estimates", "watchlist",
                 "app_usage", "app_usage_hours"]


def cmd_export(conn, a):
    """Everything, in a form that `import` can put back."""
    out = {"format": 1}
    for table in EXPORT_TABLES:
        out[table] = [dict(r) for r in conn.execute(f"select * from {table}")]
    json.dump(out, sys.stdout, indent=2)
    print()


def cmd_import(conn, a):
    """Put an export back. Rows replace by key; nothing else is touched."""
    raw = json.load(open(a.file)) if a.file != "-" else json.load(sys.stdin)
    if not isinstance(raw, dict) or "tasks" not in raw:
        sys.exit("that does not look like a space export")
    if raw.get("format") != 1:
        print(f"{WARN}older export — importing what can be read{OFF}",
              file=sys.stderr)

    counts = {}
    for table in EXPORT_TABLES:
        rows = raw.get(table) or []
        if not rows:
            continue
        have = {r["name"] for r in conn.execute(f"pragma table_info({table})")}
        usable = [{k: v for k, v in row.items() if k in have} for row in rows]
        cols = sorted({k for row in usable for k in row})
        if not cols:
            continue
        marks = ",".join("?" * len(cols))
        conn.executemany(
            f"insert or replace into {table} ({','.join(cols)}) values ({marks})",
            [[row.get(c) for c in cols] for row in usable])
        counts[table] = len(usable)
    conn.commit()
    for table, n in counts.items():
        print(f"{table:16} {n}")
    skipped = [t for t in EXPORT_TABLES if t not in counts]
    if skipped:
        print(f"{DIM}nothing to restore for: {', '.join(skipped)}{OFF}")


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
    s.add_argument("--estimate", choices=ESTIMATE_KEYS or None)
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

    s = add("estimates", help="list or edit the sizes you estimate in")
    s.add_argument("--add", metavar="DURATION", help="45m, 1h30, 2d")
    s.add_argument("--key", help="short name for --add (defaults to the duration)")
    s.add_argument("--label", help="how it reads in the form")
    s.add_argument("--remove", metavar="KEY")
    s.add_argument("--reset", action="store_true", help="back to the defaults")
    s.set_defaults(fn=cmd_estimates)

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

    s = add("day", help="read or write the day's two answers")
    s.add_argument("--did", help="what important things you did")
    s.add_argument("--missed", help="what important things you did not")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_day)

    s = add("focus", help="where the day's hours went")
    s.add_argument("--date")
    s.add_argument("--app", help="drill into one watched app, e.g. telegram")
    s.add_argument("--week", action="store_true",
                   help="a row per app, a column per day")
    s.add_argument("--days", type=int, default=7,
                   help="span for the totals shown with --app")
    s.set_defaults(fn=cmd_focus)

    s = add("watch", help="manage the distraction watchlist")
    s.add_argument("--add", metavar="APP_CLASS")
    s.add_argument("--label")
    s.add_argument("--color", default="dim",
                   choices=["red", "yellow", "green", "cyan", "dim"],
                   help="red marks time spent against you")
    s.add_argument("--remove", metavar="APP_CLASS")
    s.set_defaults(fn=cmd_watch)

    add("review", help="stale work, estimate accuracy, distraction").set_defaults(fn=cmd_review)
    add("stats", help="counts").set_defaults(fn=cmd_stats)
    add("export", help="dump everything as JSON").set_defaults(fn=cmd_export)

    s = add("import", help="restore an export (rows replace by key)")
    s.add_argument("file", help="a file written by `space-cli export`, or - for stdin")
    s.set_defaults(fn=cmd_import)
    return p


def main(argv=None):
    # Connect first: the estimate scale lives in the database and the parser
    # offers it as choices, so building the parser before connecting would
    # advertise the default scale rather than yours.
    conn = db.connect()
    args = build_parser().parse_args(argv)
    if getattr(args, "plain", False):
        plain()
    args.fn(conn, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
