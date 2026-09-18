"""Helper for track-test.py: a tracker pointed at a fake socket."""
import os, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import space.track as tr
from space import db
tr.socket_path = lambda: os.environ["FAKE_SOCK"]
tr.active_class = lambda: "org.telegram.desktop"
tr.session_state = lambda: (False, True)
tr.FLUSH_EVERY = 2
t = tr.Tracker(db.connect(os.environ["KIAREZ_SPACE_DB"]))
t.run()
