#!/usr/bin/env python3
"""The board refuses to open while the day's question is owed.

Only inside the window where a question is actually due — after midnight and
before the four o'clock close. A board that demanded an answer about a day you
are still living would teach you to type anything to get past it, so the test
checks the quiet case too.

    python3 scripts/lock-test.py
"""

import os
import pty
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from space import db                                            # noqa: E402
from space.model import add_days, today                         # noqa: E402
from space.review import owed                                   # noqa: E402


def board(dbp, keys, out, lines=30, cols=100):
    env = dict(os.environ, TERM="xterm-256color", LINES=str(lines),
               COLUMNS=str(cols), KIAREZ_SPACE_DB=dbp, SPACE_NO_FX="1", OUT=out)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("python3", ["python3", f"{REPO}/scripts/_lock_child.py", keys], env)
    os.set_blocking(fd, False)
    end = time.time() + 8
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                os.read(fd, 65536)
            except OSError:
                break
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    return Path(out).read_text() if Path(out).exists() else ""


def main() -> int:
    fails = []

    def expect(name, ok, detail=""):
        print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
        if not ok:
            fails.append(name)

    tmp = tempfile.mkdtemp()
    dbp, out = f"{tmp}/lock.db", f"{tmp}/screen.txt"
    conn = db.connect(dbp)
    node = db.add_node(conn, "Work")
    db.capture(conn, "yesterday's work", node_id=node, day=add_days(today(), -1),
               estimate="1h", outcome="x", next_action="y", status="done")
    conn.close()

    # Today is never owed: the day is not over.
    conn = db.connect(dbp)
    db.log_day(conn, add_days(today(), -1), "answered it", "")
    expect("nothing is owed once yesterday is answered",
           owed(conn) is None, "the board would lock with nothing outstanding")
    conn.execute("delete from days")
    conn.commit()
    expect("yesterday is owed while unanswered",
           owed(db.connect(dbp)) == add_days(today(), -1),
           "an unanswered yesterday was not owed")
    conn.close()

    # Inside the window, with no answer, the board shows the lock instead.
    screen = board(dbp, "", out)
    expect("the board opens locked", "LOCKED" in screen,
           f"got: {screen[:80]!r}")

    # Backing out of the questions leaves it locked and records nothing.
    Path(out).unlink(missing_ok=True)
    screen = board(dbp, "x\x1b", out)
    row = db.day_log(db.connect(dbp), add_days(today(), -1))
    expect("escaping keeps it locked", "LOCKED" in screen and not row.answered,
           f"answered={row.answered}")

    # Answering opens it.
    Path(out).unlink(missing_ok=True)
    screen = board(dbp, "x" + "did this" + "\r" + "missed that" + "\r", out)
    row = db.day_log(db.connect(dbp), add_days(today(), -1))
    expect("answering opens the board",
           row.did == "did this" and row.not_done == "missed that"
           and "KIAREZ" in screen,
           f"row={row}, screen={screen[:60]!r}")

    # Locked out of the board with no visible way to answer is the worst
    # this screen can do, so every size has to keep that line.
    for lines, cols in ((30, 100), (24, 80), (14, 50), (10, 40), (8, 30), (6, 24)):
        conn = db.connect(dbp)
        conn.execute("delete from days")
        conn.commit()
        conn.close()
        Path(out).unlink(missing_ok=True)
        screen = board(dbp, "", out, lines, cols)
        shown = "LOCKED" in screen and ("q quits" in screen or "q to quit" in screen)
        expect(f"a way out is visible at {cols}x{lines}", shown,
               f"screen={screen[:70]!r}")

    print("\n" + ("FAILED" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
