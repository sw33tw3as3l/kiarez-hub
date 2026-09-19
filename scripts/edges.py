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

# --- the estimate scale is data, not code -------------------------------------
from space.model import parse_duration                     # noqa: E402

check("durations parse the way people write them", lambda: (
    [parse_duration(x) for x in ("45m", "1h", "1h30", "90", "2d", "3h15")]
    == [45, 60, 90, 90, 960, 195], "a duration parsed wrong"))

check("nonsense durations are refused", lambda: (
    all(parse_duration(x) is None for x in ("", "banana", "0", "1x")),
    "nonsense accepted as a duration"))

check("the scale can be extended and shrunk", lambda: (
    (db.add_estimate(c, "45m", "45m", 45),
     "45m" in __import__("space.model", fromlist=["x"]).ESTIMATE_KEYS,
     db.remove_estimate(c, "45m"),
     "45m" not in __import__("space.model", fromlist=["x"]).ESTIMATE_KEYS)[3],
    "adding or removing a size did not take effect"))

check("a custom size can be stored on a task", lambda: (
    (db.add_estimate(c, "7h", "7h", 420),
     (lambda t: db.task(c, t).estimate == "7h")(
         db.capture(c, "custom", node_id=root, day=today(), kind="ship",
                    estimate="7h", outcome="x", next_action="y")))[1],
    "the estimate column still refuses custom values"))

from space.model import duration_key                       # noqa: E402

check("duration keys read back the way they were typed", lambda: (
    [duration_key(m) for m in (45, 60, 90, 105, 240, 480)]
    == ["45m", "1h", "1h30", "1h45", "4h", "8h"], "a key came out wrong"))

check("typing and parsing round-trip", lambda: (
    all(parse_duration(duration_key(m)) == m
        for m in (5, 45, 60, 90, 105, 195, 240, 480)), "a length did not survive"))

# --- the estimate clock -------------------------------------------------------
from datetime import timedelta                            # noqa: E402
from space.model import (MAX_DOING_STRETCH, estimate_accuracy,               # noqa: E402
                         estimate_hint, utc_now)

def timed(minutes_ago, estimate="1h"):
    tid = db.capture(c, f"ran {minutes_ago}m", node_id=root, day=today(),
                     kind="ship", estimate=estimate, outcome="x", next_action="y")
    db.set_status(c, tid, "doing")
    db.update_task(c, tid, doing_since=(utc_now() - timedelta(minutes=minutes_ago))
                   .isoformat(timespec="seconds"))
    return tid

check("a forgotten timer is capped, not believed", lambda: (
    (lambda t: (db.set_status(c, t, "done"),
                db.task(c, t).actual_minutes == MAX_DOING_STRETCH)[1])(timed(14 * 60)),
    "an overnight task banked its whole night"))

check("a normal stretch is untouched", lambda: (
    (lambda t: (db.set_status(c, t, "done"),
                abs(db.task(c, t).actual_minutes - 37) <= 1)[1])(timed(37)),
    "a short stretch was altered"))

check("overrun is visible while it runs", lambda: (
    db.task(c, timed(9 * 60)).overrun and not db.task(c, timed(5)).overrun,
    "overrun misreported"))

check("accuracy buckets by size and needs two samples", lambda: (
    estimate_hint(estimate_accuracy(db.tasks(c)), "day_plus") == "",
    "reported a verdict from too little data"))

# --- text measured in columns, not codepoints ---------------------------------
from space.text import cols, fit, pad, ellipsis            # noqa: E402

WIDE = ["评分引擎上线", "🚀🔥💡✅🎯", "اپلای ابراد را تمام کن", "plain ascii"]

check("ellipsis never exceeds its column width", lambda: (
    all(cols(ellipsis(s, n)) <= n for s in WIDE for n in (1, 5, 10, 20)),
    "a trimmed string still overflows"))

check("fit never splits a wide character", lambda: (
    all(cols(fit(s, n)) <= n for s in WIDE for n in range(1, 12)),
    "fit produced more columns than asked for"))

check("pad reaches the column width exactly", lambda: (
    all(cols(pad(ellipsis(s, 12), 12)) == 12 for s in WIDE), "padding is off"))

check("zero-width characters cost nothing", lambda: (
    cols("a\u200cb") == 2 and cols("e\u0301") == 1, "combining marks counted"))

print("\n" + (f"{len(fails)} FAILURE(S)" if fails else "all edges clean"))
for f in fails:
    print(" -", f)
raise SystemExit(1 if fails else 0)
