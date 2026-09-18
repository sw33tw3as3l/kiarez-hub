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
ok = secs >= 4 and beat is not None and beat < 4
print("PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
