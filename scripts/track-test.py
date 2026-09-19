"""Tracker tests against a fake compositor.

The one that matters: a compositor that never stops emitting events the
tracker does not handle. Hanging the flush off events we do care about means
a busy stream of events we don't silently stops the clock — which is what it
did in production for an hour at a time while the process looked healthy.

    python3 scripts/track-test.py
"""
import os, socket, subprocess, sys, tempfile, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from space import db
from space.model import today

SC = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
sock_path, dbp = os.path.join(tmp, "s2.sock"), os.path.join(tmp, "busy.db")
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(sock_path); srv.listen(1)

child = subprocess.Popen([sys.executable, f"{SC}/_track_child.py"],
                         env=dict(os.environ, FAKE_SOCK=sock_path,
                                  KIAREZ_SPACE_DB=dbp),
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
conn, _ = srv.accept()
end = time.time() + 7
while time.time() < end:                   # events the tracker does not handle
    try:
        conn.send(b"windowtitle>>0x55,something\nworkspace>>2\n")
    except BrokenPipeError:
        break
    time.sleep(0.02)

c = db.connect(dbp)
secs = db.usage_detail(c, "org.telegram.desktop", today())["seconds"]
beat = db.last_beat(c)
child.kill()
print(f"7s of unrelated events -> banked {secs}s, "
      f"heartbeat age {'never' if beat is None else round(beat, 1)}s")
busy_ok = secs >= 4 and beat is not None and beat < 4
print("PASS" if busy_ok else "FAIL")


def focus_is_exact() -> bool:
    """Feed a known focus sequence and check the seconds recorded match.

    This is the claim the whole tracker rests on: time is counted while a
    window holds keyboard focus, and not otherwise. It caught a real loss —
    bank() advanced its clock and then dropped anything under a second, so
    every window switch quietly cost you one.
    """
    tmp2 = tempfile.mkdtemp()
    sock2, db2 = os.path.join(tmp2, "s2.sock"), os.path.join(tmp2, "focus.db")
    srv2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv2.bind(sock2); srv2.listen(1)
    kid = subprocess.Popen([sys.executable, f"{SC}/_track_child.py"],
                           env=dict(os.environ, FAKE_SOCK=sock2,
                                    KIAREZ_SPACE_DB=db2, FLUSH="1"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    link, _ = srv2.accept()
    plan = [("org.telegram.desktop", 4), ("kitty", 3),
            ("org.telegram.desktop", 2), ("google-chrome", 5)]
    for app, seconds in plan:
        link.send(f"activewindow>>{app},a window\n".encode())
        time.sleep(seconds)
    link.send(b"activewindow>>unwatched.app,x\n")
    time.sleep(2.5)

    conn2 = db.connect(db2)
    want = {}
    for app, seconds in plan:
        want[app] = want.get(app, 0) + seconds
    good = True
    print()
    for app in sorted(want):
        got = db.usage_detail(conn2, app, today())["seconds"]
        near = abs(got - want[app]) <= 1
        good = good and near
        print(f"  {app:24} focused {want[app]}s, recorded {got}s "
              f"{'ok' if near else 'MISMATCH'}")
    stray = db.usage_detail(conn2, "com.anthropic.Claude", today())["seconds"]
    print(f"  {'never focused':24} recorded {stray}s "
          f"{'ok' if stray == 0 else 'MISMATCH'}")
    kid.kill()
    return good and stray == 0


exact = focus_is_exact()
print("PASS" if exact else "FAIL")
raise SystemExit(0 if busy_ok and exact else 1)
