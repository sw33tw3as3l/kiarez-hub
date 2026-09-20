"""Does the board survive — and stay readable at — small terminal sizes?

Walks every view at seven sizes from 200x40 down to 24x8 and fails on any
traceback. Curses is unforgiving about writes past the edge, and the usual
development window is wide enough to hide all of it.

    python3 scripts/sizes.py
"""
import pty, os, time, select, sys, json
import pathlib, tempfile, subprocess
REPO = str(pathlib.Path(__file__).resolve().parent.parent)

def run(lines, cols, keys, db):
    env = dict(os.environ, TERM="xterm-256color", LINES=str(lines),
               COLUMNS=str(cols), KIAREZ_SPACE_DB=db, SPACE_NO_FX="1")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("python3", ["python3", "-c",
                   f"import sys;sys.path.insert(0,{REPO!r});"
                   "from space.app import run;run()"], env)
    os.set_blocking(fd, False); buf = b""
    def pump(t):
        nonlocal buf
        end = time.time() + t
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.03)
            if r:
                try: buf += os.read(fd, 65536)
                except OSError: return
    pump(1.0)
    for ch in keys:
        os.write(fd, ch.encode()); pump(0.10)
    os.write(fd, b"q"); pump(0.4)
    try:
        os.kill(pid, 9); os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    return buf.decode(errors="replace")

if len(sys.argv) > 1:
    db = sys.argv[1]
else:
    db = os.path.join(tempfile.mkdtemp(), "sizes.db")
    # A crowded board, because an empty one fits anywhere and proves nothing:
    # a long estimate scale, a deep tree, rotting work and a week of usage all
    # compete for the same rows.
    sys.path.insert(0, REPO)
    from space import db as store                                  # noqa: E402
    from space.model import duration_key, today, add_days          # noqa: E402
    conn = store.connect(db)
    parent = None
    for i in range(1, 9):
        parent = store.add_node(conn, f"level-{i}", parent)
    for mins in (5, 10, 20, 25, 40, 50, 75, 100, 150, 200, 300, 600):
        key = duration_key(mins)
        store.add_estimate(conn, key, key, mins)
        for i in range(3):
            t = store.capture(conn, f"{key}-{i}", node_id=parent, day=today(),
                              estimate=key, outcome="x",
                              next_action="y", status="done")
            store.update_task(conn, t, doing_seconds=mins * 90)
    for i in range(6):
        t = store.capture(conn, f"rotting {i}", node_id=parent, day=today(),
                          estimate="5m", outcome="x",
                          next_action="y")
        store.update_task(conn, t, rolls=6)
    store.capture(conn, "a thought")
    for i in range(7):
        for app, secs in (("org.telegram.desktop", 3000), ("kitty", 5000),
                          ("google-chrome", 1500), ("com.anthropic.Claude", 900)):
            store.add_usage(conn, add_days(today(), -i), app, secs, opens=12)
    conn.close()
bad = 0
for lines, cols in [(24, 80), (20, 60), (14, 44), (10, 34), (8, 24), (40, 200), (60, 100)]:
    out = run(lines, cols, "12345" + "c" + "x" + "\r" + "n\x1b" + "w" + "hi\r\r", db)
    if "Traceback" in out:
        bad += 1
        err = out[out.find("Traceback"):]
        line = [l for l in err.split("\n") if l.strip().startswith(("_curses", "curses.error", "ValueError", "IndexError", "TypeError", "AttributeError"))]
        print(f"FAIL  {lines}x{cols}: {(line or err.split(chr(10))[-4:])[0][:120]}")
    else:
        print(f"ok    {lines}x{cols}")


def screen(view, lines, cols):
    env = dict(os.environ, TERM="xterm-256color", LINES=str(lines),
               COLUMNS=str(cols), KIAREZ_SPACE_DB=db)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("python3", ["python3", f"{REPO}/scripts/_snap_view.py", view], env)
    os.set_blocking(fd, False)
    out, end = b"", time.time() + 4
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    text = out.decode(errors="replace")
    return text.split("\x1b[?1049l")[-1].split("\n")


# A crash is the loud failure. The quiet one is a section running long and
# writing over the status rail, which looks like corruption and hides whether
# anything is being recorded.
print()
for view in ("today", "calendar", "inbox", "tree", "review"):
    for lines, cols in ((24, 80), (20, 60), (30, 100)):
        rows = [r for r in screen(view, lines, cols) if r.strip()]
        # Anchored on the corner glyph, not on a label: the labels are copy
        # and copy changes, and a test that breaks when a word is shortened
        # tells you nothing about the layout it was written to protect.
        rail = next((r for r in rows if r.lstrip().startswith("◣")), None)
        # The rail is drawn last, so it always survives — what gives a long
        # section away is its text sitting in the gaps between the rail's
        # pieces. Anything from a section on that row is a failure.
        debris = [m for m in ("Needs a decision", "n=", "→", "open ·", "↓ ")
                  if rail and m in rail]
        if rail and not debris:
            print(f"ok    {view} rail clean at {cols}x{lines}")
        else:
            bad += 1
            print(f"FAIL  {view} rail has section debris at {cols}x{lines}: "
                  f"{debris} in {(rail or '(missing)')[:70]!r}")

print("\nsizes with failures:", bad)
raise SystemExit(1 if bad else 0)
