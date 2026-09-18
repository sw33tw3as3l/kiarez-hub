"""Focus tracker: how many seconds each watched app held the keyboard.

Listens to Hyprland's event socket, so there is no polling and no extra
package — the compositor tells us the moment focus changes. Seconds are
banked per (day, app) and only for apps on the watchlist.

Run it with `space-track`, or `space-track --once` to print what it sees.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import date

from . import db

FLUSH_EVERY = 60          # seconds of accumulation before writing
IDLE_AFTER = 15 * 60      # a window focused this long with no switch stops counting


def socket_path() -> str:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not sig:
        sys.exit("HYPRLAND_INSTANCE_SIGNATURE is not set — run this inside "
                 "your Hyprland session")
    return f"{runtime}/hypr/{sig}/.socket2.sock"


def active_class() -> str:
    """Whatever is focused right now — used once, at startup."""
    try:
        out = subprocess.run(["hyprctl", "activewindow", "-j"],
                             capture_output=True, text=True, timeout=5)
        return (json.loads(out.stdout) or {}).get("class", "")
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


class Tracker:
    """Turns focus events into four numbers per app per day.

    seconds  — how long it held the keyboard
    opens    — how many separate times you went to it ("checks")
    switches — title changes while it stayed focused; in a chat app that is
               you hopping between conversations, which is interaction rather
               than the window merely sitting there
    longest  — the longest unbroken stretch
    """

    def __init__(self, conn):
        self.conn = conn
        self.watched = dict(db.watchlist(conn))
        self.current = active_class()
        self.title = ""
        self.since = time.monotonic()
        self.pending: dict[tuple[str, str], dict] = {}
        self.last_flush = time.monotonic()
        if self.current in self.watched:
            # Starting up with it already focused is itself a check.
            self.slot(self.current)["opens"] += 1

    def slot(self, app: str) -> dict:
        key = (date.today().isoformat(), app)
        if key not in self.pending:
            self.pending[key] = {"seconds": 0.0, "opens": 0, "switches": 0,
                                 "longest": 0.0, "hours": {}}
        return self.pending[key]

    def bank(self) -> None:
        """Credit the time the outgoing window held focus."""
        elapsed = time.monotonic() - self.since
        self.since = time.monotonic()
        if self.current not in self.watched or elapsed < 1:
            return
        if elapsed > IDLE_AFTER:
            # Focused but untouched for a quarter of an hour: almost certainly
            # you walked away. Count the threshold, not the whole gap.
            elapsed = IDLE_AFTER
        slot = self.slot(self.current)
        slot["seconds"] += elapsed
        slot["longest"] = max(slot["longest"], elapsed)
        hour = time.localtime().tm_hour
        slot["hours"][hour] = slot["hours"].get(hour, 0) + elapsed

    def flush(self) -> None:
        for (day, app), v in self.pending.items():
            db.add_usage(self.conn, day, app, round(v["seconds"]),
                         opens=v["opens"], switches=v["switches"],
                         stretch=round(v["longest"]))
            for hour, secs in v["hours"].items():
                db.add_usage_hour(self.conn, day, hour, app, round(secs))
        self.pending.clear()
        self.last_flush = time.monotonic()
        self.watched = dict(db.watchlist(self.conn))     # pick up edits

    def focus(self, app: str, title: str = "") -> None:
        same_app = app == self.current
        self.bank()
        if app in self.watched:
            if not same_app:
                self.slot(app)["opens"] += 1          # you went to it again
            elif title and title != self.title:
                self.slot(app)["switches"] += 1       # you moved around inside it
        self.current, self.title = app, title
        if time.monotonic() - self.last_flush >= FLUSH_EVERY:
            self.flush()

    def run(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path())
        sock.settimeout(FLUSH_EVERY)
        buf = b""
        try:
            while True:
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    self.bank()          # keep the running total honest
                    self.flush()
                    continue
                if not chunk:
                    break                # compositor went away
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    event, _, payload = line.decode(errors="replace").partition(">>")
                    if event == "activewindow":
                        app, _, title = payload.partition(",")
                        self.focus(app, title)
                    elif event in ("closewindow", "focusedmon"):
                        self.focus(active_class())
        finally:
            self.bank()
            self.flush()
            sock.close()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    conn = db.connect()

    if "--once" in argv:
        app = active_class()
        watched = dict(db.watchlist(conn))
        print(f"focused: {app}  {'(watched)' if app in watched else '(not watched)'}")
        print(f"socket:  {socket_path()}")
        for a, label in db.watchlist(conn):
            print(f"watching {label:12} {a}")
        return 0

    tracker = Tracker(conn)
    print(f"tracking {len(tracker.watched)} apps → {db.db_path()}", flush=True)
    while True:
        try:
            tracker.run()
        except (ConnectionError, FileNotFoundError, OSError) as exc:
            print(f"lost the compositor socket ({exc}) — retrying in 10s",
                  file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            tracker.bank()
            tracker.flush()
            return 0
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
