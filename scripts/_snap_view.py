"""Helper for sizes.py: draw one view and print the screen back."""
import curses, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from space import db
from space.app import App
from space.ui import init_colors

view = sys.argv[1]


def main(stdscr):
    init_colors()
    app = App(stdscr, db.connect())
    app.view = view
    app.draw()
    h, w = stdscr.getmaxyx()
    return [stdscr.instr(y, 0, (w - 1) * 4).decode(errors="replace").rstrip()
            for y in range(h)]


print("\n".join(curses.wrapper(main)))
