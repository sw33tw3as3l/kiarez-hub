"""Helper for lock-test.py: the board, as if it were half past midnight."""
"""Run the board as if it were 00:30 — the question is due."""
import curses, sys, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import space.review as review
from space.model import add_days, today
YESTERDAY = add_days(today(), -1)
review.review_day = lambda when=None: YESTERDAY      # pretend it is 00:30
import space.app as appmod
from space import db, ui

captured = []
def main(stdscr):
    ui.init_colors()
    app = appmod.App(stdscr, db.connect())
    typed = sys.argv[1] if len(sys.argv) > 1 else ""
    keys = [ord(c) for c in typed]
    class P:
        def __init__(s, w): s._w = w
        def __getattr__(s, n): return getattr(s._w, n)
        def getch(s, *a):
            if keys: return keys.pop(0)
            h, w = s._w.getmaxyx()
            captured.extend(s._w.instr(y,0,(w-1)*4).decode(errors="replace").rstrip()
                            for y in range(h))
            return ord("q")
    app.stdscr = P(stdscr)
    app.run()
curses.wrapper(main)
open(os.environ["OUT"], "w").write("\n".join(l for l in captured if l.strip()))
