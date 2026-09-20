# kiarez space

A local task board. Python 3 standard library only — `curses`, `sqlite3`,
`socket`. No dependencies, no server, no network.

- `space/model.py` — the domain and every rule. `can_start()` is the single
  gate that both the TUI and CLI call; don't duplicate its logic. `Tree`
  holds the walk/path/descendants helpers.
- `space/db.py` — SQLite. `roll_forward()` runs at startup; `set_status()`
  doubles as the clock (time accrues while a task is in `doing`).
- `space/text.py` — measuring text in terminal columns. Imports nothing, so
  the CLI can use it too. Every layout decision goes through `cols`/`fit`/
  `pad`/`ellipsis`; `len()` is not a width.
- `space/theme.py` — the palette (Edgerunners: yellow signature, magenta
  motion, cyan structure, `#ff003c` cost). `init()` writes real RGB into colour slots
  when `can_change_color()`, else falls back to ANSI. All `C_*` pair ids live
  here; `ui.py` re-exports them.
- `space/fx.py` — animation and texture: boot glitch, sweeps, eighth-block
  bars, the breathing caret. Everything aborts on a keypress and respects
  `SPACE_NO_FX`.
- `space/ui.py` — curses primitives, framed panels, the field editor, the
  reactive one-line prompt.
- `space/app.py` — the five views.
- `space/cli.py` — scriptable commands.
- `space/review.py` — the daily questions and the Sunday weekly. **One day of
  grace**: `owed()` is yesterday while it is unanswered and nothing otherwise,
  so the board stays locked all day until you answer and today is never
  demanded. `review_day(conn=...)` is where an answer goes — yesterday while
  it is outstanding, today once it is settled — and it needs the connection,
  so pass it. Nothing older than yesterday is ever writable. An hour-of-the-
  morning cutoff was tried first and failed in production: two consecutive
  nights closed unanswered because the question arrives at midnight and the
  window shut before anyone was awake. `App.locked_out()` holds the board;
  `scripts/lock-test.py` covers it, sizes included, and smoke.py has to answer
  yesterday before it can drive anything. `weekly_owed()` is the same shape for
  the Sunday review, reachable from the board with `W` and offered
  automatically after the lock's daily answers — the reminder asks about it, so
  the board has to be able to satisfy it.
- `space/track.py` — Hyprland focus tracker. Records *keyboard focus*, not
  "app is open": nothing accrues while the session is locked or inactive, a
  lock transition refunds the idle minutes that preceded it (already-written
  rows included, via `db.refund_usage`), and one unbroken stretch caps at
  `MAX_STRETCH`. `clean_title()` strips unread counters so an arriving message
  isn't counted as an interaction. `db.beat()` each flush is what lets the
  board's status rail say whether anything is recording. Banks seconds, checks
  (focus gained), interactions (real title changes) and the longest stretch,
  plus an hourly breakdown, into `app_usage` / `app_usage_hours`. Each watched
  app carries a colour; `red` is the one with meaning — `usage_total(color=
  "red")` is what the day strip calls distraction.

Rules that matter:
- **Capture is free, starting is not.** Anything can be created with a title
  alone. `can_start()` decides when it may move to `doing`.
- **The tree is a forest of permanent nodes.** `nodes.parent_id` is the only
  structure; area-vs-goal is derived from having children (`Tree.is_leaf`) and
  is never stored, so nesting under a goal needs no migration. Tasks reference
  any node. `move_node()` refuses cycles; deleting cascades to the subtree and
  nulls the tasks' `node_id`.
- `tasks.kind` is retired. The column stays so old rows keep what they had,
  but nothing reads it and nothing requires it; `done_count()` replaced
  `ship_ratio()`.
- The estimate field is `kind="duration"`: chips plus free typing. A typed
  length is parsed live, canonicalised by `duration_key()`, and registered on
  save by `App.register_estimate()` — a one-off with no minutes behind it
  would be invisible to the accuracy table.
- A size removed from the scale stays on the tasks that carry it. The form
  offers it back via `estimate_field(keep=...)` so editing anything else about
  such a task does not silently change its estimate, and `App.estimate_hint`
  says the size has been retired rather than raising a KeyError on it.
- **The estimate scale is data.** It lives in the `estimates` table and
  `db.connect()` installs it via `model.load_scale()`, which mutates
  `ESTIMATES`/`ESTIMATE_KEYS`/`ESTIMATE_LABELS`/`ESTIMATE_MINUTES` **in place** —
  every module did `from .model import ...`, so rebinding would leave them
  pointing at the old scale. `cli.main()` connects before building the parser
  for the same reason. Old databases carry a CHECK on `tasks.estimate`;
  `_free_the_estimate_column()` rebuilds the table once to drop it.
- **The Doing clock is capped at `MAX_DOING_STRETCH`**, for the same reason the
  focus tracker caps a stretch. `estimate_accuracy()` reports a median per
  size, never a mean over everything; `Field.hint` may be a callable so the
  estimate field can speak about the option under the cursor.
- Unfinished tasks roll to today and increment `rolls`.
- No third-party dependencies. The point is that it starts instantly.

Three things run in the background, all started from
`~/.config/hypr/custom/execs.lua`: `space-track` (focus), `review-reminder.sh`
(the day's question) and `repo-watch.sh` (GitHub activity).

Gotchas already paid for:
- **`gh api --jq` writes its error body to STDOUT.** A 404 or an expired
  token looks exactly like data unless the exit status is checked — the repo
  watcher wrote the error JSON into its state file as the newest id, which
  would have made the next good poll announce everything it could see.
- **Scanning /proc for a daemon matches anything that merely mentions it.**
  Compare against argv basenames and skip your own pid, or the board reports a
  daemon as running because a shell command had its name in it.
- **`dunstify` blocks until its notification is dismissed or expires.** Any
  loop that notifies must do the waiting in a subshell, or it stops doing its
  job for as long as its own notification is on screen — the repo watcher
  never recorded what it had seen because it was still inside the call.
- **Three different units, all called "length".** `curses.addnstr`'s limit is
  BYTES, screen positions are COLUMNS, and `len()` is CODEPOINTS. A CJK
  character is 1 codepoint, 3 bytes and 2 columns. `put()` trims by column via
  `text.fit()` and hands addnstr the byte length; never pad with `str.ljust`,
  use `text.pad`.
- Ctrl-S is XOFF — `disable_flow_control()` clears IXON at startup, and F2 is
  a second save key.
- With argparse `parents=`, shared flags need `default=argparse.SUPPRESS` or
  the subparser overwrites the top-level value.
- Verifying the TUI: read the window back with `stdscr.instr()` (see git
  history) rather than parsing the escape stream — and read `(w-1)*4` bytes,
  since multibyte characters make a column count too short. A curses window
  is read-only, so scripted-key harnesses need a delegating proxy object
  rather than assigning over `getch`.
- Animated widgets set `stdscr.timeout(ms)` and must treat `getch() == -1` as
  "draw another frame". Every path out of them restores `timeout(-1)`, or the
  main loop starts spinning.
- **A query built by string concatenation needs its parameters built the same
  way.** `db.badge_counts()` assembles three counts, each optionally scoped to
  a branch; a single flat argument list guessed at the order and crashed the
  moment a scope was active. Each subquery carries its own parameters now.
- `space/glow.py` is the real light: a kitty graphics sprite placed below the
  text (`z` well under zero puts it under cell backgrounds too). Transmitted
  once with `a=t` and zlib, then only moved with `a=p` after an `a=d` — never
  re-sent. The sprite is square, so the placement box must be twice as wide in
  cells as it is tall. `forget()` on the way out or the image outlives the app.
- The fallback ambient light (`App.draw_light`) is a radial glow drawn **last**, as
  background colour on empty cells only. Two things it is easy to get wrong:
  a terminal cell is about twice as tall as it is wide, so horizontal distance
  must be halved or the "circle" is a wide oval; and the falloff wants to be
  linear, since squaring it shrinks the visible light to a third of its radius
  and loses the halo entirely. It is skipped once `_draw_ms` passes
  `LIGHT_BUDGET_MS` — decoration is the first thing that should go when a
  frame gets expensive. Every colour in `HEX` needs an entry in `FALLBACK`,
  or `init()` raises on a terminal that cannot redefine colours.
- **One frame, one set of reads.** `App.draw()` clears `_frame_cache` and every
  view reads tasks through `App.read_tasks()`; the chips are counted by
  `db.badge_counts()` in SQL. Before that, a three-thousand-task board built
  twelve thousand Task objects per redraw and took 66ms a frame, which is a
  third of the animation budget and felt like lag while typing. It is 20ms now.
  If you add a view, read through the cache.
- `App.alive()` decides whether the main loop animates or blocks. Keep it
  cheap and keep it honest: an idle board must block.
- **Never hang periodic work off events you happen to care about.** The
  tracker flushed on `activewindow` or on a socket timeout, so a compositor
  busy emitting events it ignores meant `recv` never timed out and banking
  stopped dead — for an hour, in production, with the process looking healthy.
  `Tracker.tick()` now runs on the loop itself. `scripts/track-test.py` holds
  the regression: a fake compositor that emits nothing but noise.
- **`bank()` must never discard elapsed time.** It advances `since` first, so
  anything it drops is gone — an `elapsed < 1` guard cost a second on every
  window switch, about a minute a day. Seconds accumulate as floats and are
  rounded once, at the flush. track-test.py drives a known focus sequence and
  asserts the recorded seconds match it exactly.
- **Run `scripts/smoke.py`, `scripts/edges.py`, `scripts/sizes.py` and
  `scripts/track-test.py` before committing.** sizes.py walks every view from 200x40 down to 24x8 — curses is
  unforgiving about writes past the edge and a wide development window hides
  all of it. Header, chips and the key hints are all width-degrading: chips
  shed their labels before their numbers, because losing the shortcut keys off
  the left edge is worse than losing their names. Neither an import nor a clean traceback check proves anything:
  a missing method only blows up on the frame that calls it, and a completely
  dead form raises nothing at all. smoke.py drives the real TUI in a pty
  through every view and panel with effects on and off, *and* asserts outcomes
  against the database (a task added through the form arrives complete, x-then-y
  really deletes, both daily answers are stored). edges.py covers the data layer
  in a second, no terminal needed.
- **A widget that waits for an answer must own the input timeout.** `confirm()`
  inherited its caller's and answered itself "no" within 90ms. Anything that
  blocks for a keypress sets `timeout(-1)` and restores the caller's cadence.
