"""Helper for lock-test.py: the board, driven by scripted keys."""
import curses
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import space.review as review                                   # noqa: E402

# Tests need to stand on a particular day — a Sunday, to reach the weekly.
if os.environ.get("FAKE_YESTERDAY"):
    review.yesterday = lambda when=None: os.environ["FAKE_YESTERDAY"]

from space import db, ui                                        # noqa: E402
from space.app import App                                       # noqa: E402

captured = []


def main(stdscr):
    ui.init_colors()
    app = App(stdscr, db.connect())
    keys = [ord(c) for c in (sys.argv[1] if len(sys.argv) > 1 else "")]

    class Proxy:
        def __init__(self, win):
            self._w = win

        def __getattr__(self, name):
            return getattr(self._w, name)

        def getch(self, *a):
            if keys:
                return keys.pop(0)
            h, w = self._w.getmaxyx()
            captured.extend(
                self._w.instr(y, 0, (w - 1) * 4).decode(errors="replace").rstrip()
                for y in range(h))
            return ord("q")

    app.stdscr = Proxy(stdscr)
    app.run()


curses.wrapper(main)
pathlib.Path(os.environ["OUT"]).write_text(
    "\n".join(line for line in captured if line.strip()))
