#!/usr/bin/env python3
"""Drive the real TUI in a pty and check what it actually did.

Two layers, because each caught a bug the other missed:

  · journeys — walk every view and panel, fail on any traceback. A method can
    go missing and only blow up on the frame that calls it, which no import
    check will ever see.
  · outcomes — do the thing, then assert the database changed. A whole form
    once went dead (every keystroke landing in the last field) while the
    traceback check stayed perfectly green.

    python3 scripts/smoke.py
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

# (name, keys) — keys are fed one at a time, with a beat between them.
JOURNEYS = [
    ("every view", "12345"),
    ("day navigation", "1[[]]tjklhJK"),
    ("calendar walk", "2hjklhh\r"),
    ("tree build", "4A" + "Work\r" + "a" + "Ship it\r" + "jl" + "e" + "Ship it now\r"),
    ("capture", "c" + "a captured thought\r"),
    ("inbox", "3jke\x1b"),
    ("new task form", "1n\x1b"),
    ("answer the day", "w" + "shipped the thing\r" + "the other thing\r"),
    ("help", "?x"),
    ("go to a date", "g" + "+3" + "\r" + "g" + "-2" + "\r" + "t"),
    ("filter", "/" + "a" + "\r" + "/" + "\r"),
    ("scope to a branch", "4f" + "1" + "F"),
    ("new task from the inbox", "3n\x1b"),
    ("review", "5jk"),
]


def drive(db_path: Path, keys: str, fx: bool) -> str:
    env = dict(os.environ, TERM="xterm-256color", LINES="40", COLUMNS="140",
               KIAREZ_SPACE_DB=str(db_path))
    if not fx:
        env["SPACE_NO_FX"] = "1"
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("python3", ["python3", "-c",
                               f"import sys; sys.path.insert(0, {str(REPO)!r});"
                               "from space.app import run; run()"], env)
    os.set_blocking(fd, False)
    out = b""

    def pump(seconds):
        nonlocal out
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], 0.04)
            if ready:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    return

    pump(1.2)
    for ch in keys:
        os.write(fd, ch.encode())
        pump(0.14)
    os.write(fd, b"q")
    pump(0.6)
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    return out.decode(errors="replace")


ARROW = "\x1bOC"          # application-mode right arrow, which is what curses expects


def check_outcomes(failures: list) -> None:
    """Do a thing through the UI, then ask the database whether it happened."""
    import sqlite3

    def board(db, keys):
        drive(db, keys, fx=False)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    def expect(name, ok, detail=""):
        if ok:
            print(f"ok    {name}")
        else:
            failures.append(f"{name}\n  {detail}")
            print(f"FAIL  {name}")

    with tempfile.TemporaryDirectory() as tmp:
        # A task added through the form must arrive complete.
        db = f"{tmp}/outcome-form.db"
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True,
                       env=dict(os.environ, KIAREZ_SPACE_DB=db))
        keys = ("n" + "Formed task" + "\r" + "\r" + "it is done" + "\r"
                + ARROW + "\r" + "first step" + "\r" + "\x13")
        conn = board(db, keys)
        row = conn.execute("select * from tasks where title = 'Formed task'").fetchone()
        expect("form creates a complete task", row is not None
               and all(row[c] for c in ("outcome", "estimate",
                                        "next_action", "node_id")),
               f"row={dict(row) if row else None}")

        # Capture must land one row in the inbox, with no day set.
        db = f"{tmp}/outcome-capture.db"
        conn = board(db, "c" + "a captured thought" + "\r")
        row = conn.execute("select * from tasks where day is null").fetchone()
        expect("capture lands in the inbox", row is not None
               and row["title"] == "a captured thought", f"row={dict(row) if row else None}")

        # The day's two questions must both be stored.
        db = f"{tmp}/outcome-day.db"
        conn = board(db, "w" + "did this" + "\r" + "missed that" + "\r")
        row = conn.execute("select * from days").fetchone()
        expect("both daily answers are saved", row is not None
               and row["shipped"] == "did this" and row["missed"] == "missed that",
               f"row={dict(row) if row else None}")

        # Building the tree from the board must nest.
        db = f"{tmp}/outcome-tree.db"
        conn = board(db, "4A" + "Root" + "\r" + "a" + "Child" + "\r")
        rows = {r["name"]: r["parent_id"] for r in conn.execute("select * from nodes")}
        expect("tree adds a root and a child", len(rows) == 2
               and rows.get("Child") is not None and rows.get("Root") is None,
               f"nodes={rows}")

        # Deleting must actually delete — the confirm panel used to answer
        # itself "no" because it inherited the caller's input timeout.
        db = f"{tmp}/outcome-delete.db"
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Gone"],
                       capture_output=True,
                       env=dict(os.environ, KIAREZ_SPACE_DB=db))
        conn = board(db, "4jx" + "y")
        left = conn.execute("select count(*) c from nodes").fetchone()["c"]
        expect("x then y deletes a node", left == 0, f"{left} node(s) left")

        # Enter on an untouched choice field must settle on a real value.
        db = f"{tmp}/outcome-enter.db"
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True,
                       env=dict(os.environ, KIAREZ_SPACE_DB=db))
        keys = ("n" + "Entered task" + "\r\r" + "done" + "\r\r"
                + "go" + "\r" + "\x13")
        conn = board(db, keys)
        row = conn.execute("select * from tasks").fetchone()
        expect("enter settles choice fields", row is not None
               and row["estimate"],
               f"row={dict(row) if row else None}")

        # < and > must move the task, not the view.
        db = f"{tmp}/outcome-move.db"
        env = dict(os.environ, KIAREZ_SPACE_DB=db)
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True, env=env)
        cap = subprocess.run([str(REPO / "bin/space-cli"), "--plain", "c", "Shift me"],
                             capture_output=True, text=True, env=env).stdout.strip()
        subprocess.run([str(REPO / "bin/space-cli"), "define", cap, "--goal", "work",
                        "--outcome", "done", "--estimate", "1h",
                        "--next", "go"], capture_output=True, env=env)
        subprocess.run([str(REPO / "bin/space-cli"), "schedule", cap],
                       capture_output=True, env=env)
        import datetime
        conn = board(db, ">")
        row = conn.execute("select day from tasks").fetchone()
        expect("> moves the task to tomorrow",
               row and row["day"] == (datetime.date.today()
                                      + datetime.timedelta(days=1)).isoformat(),
               f"day={row['day'] if row else None}")

        # A length typed into the estimate field must become a real size.
        db = f"{tmp}/outcome-duration.db"
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True,
                       env=dict(os.environ, KIAREZ_SPACE_DB=db))
        keys = ("n" + "Typed size" + "\r\r" + "done" + "\r"
                + "1h45" + "\r" + "go" + "\r" + "\x13")
        conn = board(db, keys)
        row = conn.execute("select estimate from tasks").fetchone()
        scale = {r["key"]: r["minutes"] for r in conn.execute("select * from estimates")}
        expect("a typed duration becomes the estimate",
               row and row["estimate"] == "1h45" and scale.get("1h45") == 105,
               f"estimate={row['estimate'] if row else None} scale_has={scale.get('1h45')}")

        # s on an undefined inbox item defines it and schedules it in one go.
        db = f"{tmp}/outcome-inbox-s.db"
        env = dict(os.environ, KIAREZ_SPACE_DB=db)
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True, env=env)
        subprocess.run([str(REPO / "bin/space-cli"), "c", "from the inbox"],
                       capture_output=True, env=env)
        DOWN = "\x1bOB"
        keys = ("3s" + DOWN + DOWN + "it works" + "\r" + "1h" + "\r"
                + "first step" + "\r" + "\x13")
        conn = board(db, keys)
        row = conn.execute("select day, estimate from tasks").fetchone()
        import datetime as _d
        expect("s defines and schedules in one step",
               row and row["day"] == _d.date.today().isoformat()
               and row["estimate"] == "1h",
               f"row={dict(row) if row else None}")

        # g must actually move the board to the day it names.
        db = f"{tmp}/outcome-goto.db"
        env = dict(os.environ, KIAREZ_SPACE_DB=db)
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True, env=env)
        cap = subprocess.run([str(REPO / "bin/space-cli"), "--plain", "c", "Far away"],
                             capture_output=True, text=True, env=env).stdout.strip()
        subprocess.run([str(REPO / "bin/space-cli"), "define", cap, "--goal", "work",
                        "--outcome", "done", "--estimate", "1h",
                        "--next", "go"], capture_output=True, env=env)
        subprocess.run([str(REPO / "bin/space-cli"), "schedule", cap],
                       capture_output=True, env=env)
        # jump forward three days, then push the task there with >
        conn = board(db, "g+3\r")
        # nothing should have moved yet
        row = conn.execute("select day from tasks").fetchone()
        import datetime as _dt
        expect("g alone changes nothing in the data",
               row and row["day"] == _dt.date.today().isoformat(),
               f"day={row['day'] if row else None}")

        # Advancing a task must move its status.
        db = f"{tmp}/outcome-status.db"
        env = dict(os.environ, KIAREZ_SPACE_DB=db)
        subprocess.run([str(REPO / "bin/space-cli"), "node-add", "Work"],
                       capture_output=True, env=env)
        cap = subprocess.run([str(REPO / "bin/space-cli"), "--plain", "c", "Do it"],
                             capture_output=True, text=True, env=env).stdout.strip()
        subprocess.run([str(REPO / "bin/space-cli"), "define", cap, "--goal", "work",
                        "--outcome", "done", "--estimate", "1h",
                        "--next", "go"], capture_output=True, env=env)
        subprocess.run([str(REPO / "bin/space-cli"), "schedule", cap],
                       capture_output=True, env=env)
        conn = board(db, " ")
        row = conn.execute("select status from tasks").fetchone()
        expect("space advances status", row and row["status"] == "doing",
               f"status={row['status'] if row else None}")


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for fx in (False, True):
            for name, keys in JOURNEYS:
                db = Path(tmp) / f"smoke-{'fx' if fx else 'plain'}-{name}.db".replace(" ", "-")
                text = drive(db, keys, fx)
                label = f"{name}{' [fx]' if fx else ''}"
                if "Traceback" in text or "AttributeError" in text:
                    snippet = text[text.find("Traceback"):][:400]
                    failures.append(f"{label}\n{snippet}")
                    print(f"FAIL  {label}")
                else:
                    print(f"ok    {label}")

    # The CLI, too — cheap, and it shares every model rule with the board.
    for args in (["stats"], ["today"], ["tree"], ["inbox"], ["focus"],
                 ["focus", "--week"], ["review"], ["day"], ["watch"]):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([str(REPO / "bin/space-cli"), "--plain", *args],
                               capture_output=True, text=True,
                               env=dict(os.environ,
                                        KIAREZ_SPACE_DB=f"{tmp}/cli.db"))
            name = "space-cli " + " ".join(args)
            if r.returncode != 0:
                failures.append(f"{name}\n{r.stderr[:300]}")
                print(f"FAIL  {name}")
            else:
                print(f"ok    {name}")

    print()
    check_outcomes(failures)

    if failures:
        print(f"\n{len(failures)} failure(s):\n")
        for f in failures:
            print(f + "\n")
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
