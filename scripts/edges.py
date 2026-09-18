"""Edge cases the happy path never reaches.

Pure data-layer checks — no terminal, no pty, runs in a second. The smoke
test covers the UI; this covers what the UI would have to be unlucky to hit.

    python3 scripts/edges.py
"""
import sys, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from space import db
from space.model import today, add_days, can_start

fails = []
def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        fails.append(f"{name}: raised {type(e).__name__}: {e}")
        print(f"RAISE {name}: {type(e).__name__}: {e}")
        return
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(f"{name}: {detail}")

path = os.path.join(__import__("tempfile").mkdtemp(), "edge.db")
for s in ("", "-wal", "-shm"):
    try: os.remove(path + s)
    except FileNotFoundError: pass
c = db.connect(path)
root = db.add_node(c, "Root")
kid = db.add_node(c, "Kid", root)

check("delete a node, tasks survive without it", lambda: (
    (lambda tid: (db.delete(c, "nodes", kid) or True) and
        (db.task(c, tid) is not None and db.task(c, tid).node_id is None,
         "task vanished or kept a dead node"))(
        db.capture(c, "orphan", node_id=kid, day=today(),
                   kind="ship", estimate="1h", outcome="x", next_action="y"))))

check("moving a node under itself is refused", lambda: (
    db.move_node(c, root, root) is not None, "self-parent allowed"))

check("reorder past the end does nothing bad", lambda: (
    (lambda t: (db.reorder(c, t, 99) or True) and (db.task(c, t) is not None, "gone"))(
        db.capture(c, "solo", node_id=root, day=today()))))

check("roll_forward is idempotent", lambda: (
    (db.roll_forward(c), db.roll_forward(c) == 0)[1], "second roll moved rows again"))

check("rolling does not touch done tasks", lambda: (
    (lambda t: (db.set_status(c, t, "done"),
                db.roll_forward(c),
                db.task(c, t).day == add_days(today(), -3))[2])(
        db.capture(c, "old done", node_id=root, day=add_days(today(), -3))),
    "a finished task got dragged forward"))

check("refund cannot go negative", lambda: (
    (db.add_usage(c, today(), "x", 60),
     db.refund_usage(c, today(), "x", 9999),
     db.usage_detail(c, "x", today())["seconds"] == 0)[2], "went below zero"))

check("usage_matrix tolerates an unwatched app", lambda: (
    (db.add_usage(c, today(), "unwatched.app", 120),
     any(r["app"] == "unwatched.app" and r["label"] == "unwatched.app"
         for r in db.usage_matrix(c, [today()])))[1], "row missing"))

check("usage_matrix drops apps with no time", lambda: (
    not any(r["app"] == "x" for r in db.usage_matrix(c, [today()])),
    "a zero-second row survived"))

check("empty tree renders a path", lambda: (
    db.tree(c).path(None) == "", "path of nothing is not empty"))

check("can_start on a bare capture refuses", lambda: (
    len(can_start(db.task(c, db.capture(c, "bare")))) == 5, "wrong blocker count"))

check("week_start lands on a Monday", lambda: (
    __import__("datetime").date.fromisoformat(db.week_start(today())).weekday() == 0,
    "not a Monday"))

check("day_log for an unknown day is blank not missing", lambda: (
    db.day_log(c, "2020-01-01").answered is False, "claims answered"))

check("logging an empty answer still marks the day", lambda: (
    (db.log_day(c, today(), "nothing", ""),
     db.day_log(c, today()).answered)[1], "day not marked answered"))

print("\n" + (f"{len(fails)} FAILURE(S)" if fails else "all edges clean"))
for f in fails:
    print(" -", f)
raise SystemExit(1 if fails else 0)
