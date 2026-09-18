#!/usr/bin/env python3
"""Drive the real TUI in a pty and fail on any traceback.

Importing a module proves almost nothing about a curses app: a method can go
missing and only blow up on the frame that calls it. This walks every view,
opens every panel, and answers the day's questions, then greps the output for
a traceback. Run it before committing anything that touches the UI.

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

    if failures:
        print(f"\n{len(failures)} failure(s):\n")
        for f in failures:
            print(f + "\n")
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
