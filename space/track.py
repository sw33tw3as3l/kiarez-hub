"""Focus tracker: how many seconds each watched app held the keyboard.

Listens to Hyprland's event socket, so there is no polling and no extra
package — the compositor tells us the moment focus changes. Seconds are
banked per (day, app) and only for apps on the watchlist.

Run it with `space-track`, or `space-track --once` to print what it sees.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import date

from . import db

FLUSH_EVERY = 60          # seconds of accumulation before writing

# A window can hold focus for hours while nobody is at the keyboard. Two
# guards, because "focused" and "being used" are different things:
#
#   · the session tells us when it locks. hypridle here locks after five idle
#     minutes, so on the lock transition those five minutes are deducted —
#     they were already banked as focus time and they were not.
#   · where no session manager answers, a single unbroken stretch stops
#     counting past MAX_STRETCH. That is a backstop, not the main mechanism.
MAX_STRETCH = 20 * 60
IDLE_BEFORE_LOCK = int(os.environ.get("SPACE_IDLE_BEFORE_LOCK", 5 * 60))
SESSION_POLL = 30         # seconds between session-state checks


def socket_path() -> str:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not sig:
        sys.exit("HYPRLAND_INSTANCE_SIGNATURE is not set — run this inside "
                 "your Hyprland session")
    return f"{runtime}/hypr/{sig}/.socket2.sock"


# Chat apps put the unread count in the window title, so every arriving
# message looks like you moving around inside the app. Strip counters and
# notification markers before deciding a title actually changed.
NOISE = re.compile(r"\(\d+\)|\[\d+\]|^\s*[•●*]\s*|\s+")


def clean_title(title: str) -> str:
    return NOISE.sub(" ", title).strip().lower()


def session_state() -> tuple[bool, bool]:
    """(locked, active) from logind. (False, True) when it can't be asked."""
    session = os.environ.get("XDG_SESSION_ID", "self")
    try:
        out = subprocess.run(
            ["loginctl", "show-session", session, "-p", "LockedHint", "-p", "Active"],
            capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return False, True
    values = dict(line.split("=", 1) for line in out.stdout.splitlines()
                  if "=" in line)
    return values.get("LockedHint") == "yes", values.get("Active", "yes") == "yes"


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
        self.watched = {app: label for app, label, _ in db.watchlist(conn)}
        self.current = active_class()
        self.title = ""
        now = time.monotonic()
        self.since = now              # last time anything was banked
        self.stretch_start = now      # when this unbroken focus stretch began
        self.stretch_counted = 0.0    # seconds credited within this stretch
        self.pending: dict[tuple[str, str], dict] = {}
        self.last_flush = now
        self.locked, self.session_live = session_state()
        self.last_poll = now
        if self.current in self.watched:
            # Starting up with it already focused is itself a check.
            self.slot(self.current)["opens"] += 1

    def slot(self, app: str) -> dict:
        key = (date.today().isoformat(), app)
        if key not in self.pending:
            self.pending[key] = {"seconds": 0.0, "opens": 0, "switches": 0,
                                 "longest": 0.0, "hours": {}}
        return self.pending[key]

    def poll_session(self) -> None:
        """Watch for the screen locking; unwind the idle time that preceded it."""
        now = time.monotonic()
        if now - self.last_poll < SESSION_POLL:
            return
        self.last_poll = now
        locked, live = session_state()

        if locked and not self.locked:
            # The session just locked, which here means five idle minutes have
            # already gone by. Those minutes were banked as focus. Take them
            # back — including from rows already written out.
            self.bank()
            self.refund(min(self.stretch_counted, IDLE_BEFORE_LOCK))
        if not locked and self.locked:
            self.reset_stretch()       # back at the keyboard; start clean

        self.locked, self.session_live = locked, live

    def refund(self, seconds: float) -> None:
        """Remove time that turned out not to be time at the keyboard."""
        if seconds < 1 or self.current not in self.watched:
            return
        slot = self.slot(self.current)
        take = min(slot["seconds"], seconds)
        slot["seconds"] -= take
        slot["longest"] = max(0.0, slot["longest"] - seconds)
        hour = time.localtime().tm_hour
        slot["hours"][hour] = max(0.0, slot["hours"].get(hour, 0) - take)
        left = seconds - take
        if left >= 1:                  # the rest is already in the database
            db.refund_usage(self.conn, date.today().isoformat(), self.current,
                            round(left))
        self.stretch_counted = max(0.0, self.stretch_counted - seconds)

    def reset_stretch(self) -> None:
        now = time.monotonic()
        self.since = self.stretch_start = now
        self.stretch_counted = 0.0

    def bank(self) -> None:
        """Credit the time the outgoing window held focus.

        Only what was plausibly spent at the keyboard: nothing accrues while
        the session is locked or inactive, and a single unbroken stretch is
        capped, so a window left in front overnight cannot bank the night.
        """
        now = time.monotonic()
        elapsed = now - self.since
        self.since = now
        if self.current not in self.watched or elapsed < 1:
            return
        if self.locked or not self.session_live:
            return
        room = MAX_STRETCH - self.stretch_counted
        if room <= 0:
            return
        elapsed = min(elapsed, room)
        self.stretch_counted += elapsed
        slot = self.slot(self.current)
        slot["seconds"] += elapsed
        slot["longest"] = max(slot["longest"], self.stretch_counted)
        hour = time.localtime().tm_hour
        slot["hours"][hour] = slot["hours"].get(hour, 0) + elapsed

    def flush(self) -> None:
        for (day, app), v in self.pending.items():
            db.add_usage(self.conn, day, app, round(v["seconds"]),
                         opens=v["opens"], switches=v["switches"],
                         stretch=round(v["longest"]))
            for hour, secs in v["hours"].items():
                db.add_usage_hour(self.conn, day, hour, app, round(secs))
        db.beat(self.conn)
        self.pending.clear()
        self.last_flush = time.monotonic()
        self.watched = {app: label for app, label, _ in
                        db.watchlist(self.conn)}   # pick up edits

    def focus(self, app: str, title: str = "") -> None:
        same_app = app == self.current
        self.bank()
        if not same_app:
            self.reset_stretch()
        if app in self.watched:
            if not same_app:
                self.slot(app)["opens"] += 1          # you went to it again
            elif title and clean_title(title) != self.title:
                self.slot(app)["switches"] += 1       # you moved around inside it
        self.current, self.title = app, clean_title(title)
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
                    self.poll_session()  # did the screen lock while we waited?
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
        watched = {a for a, _, _ in db.watchlist(conn)}
        print(f"focused: {app}  {'(watched)' if app in watched else '(not watched)'}")
        print(f"socket:  {socket_path()}")
        for a, label, color in db.watchlist(conn):
            print(f"watching {label:12} {color:7} {a}")
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
