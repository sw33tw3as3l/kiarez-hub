# kiarez space

A local task board. Python 3 standard library only — `curses`, `sqlite3`,
`socket`. No dependencies, no server, no network.

- `space/model.py` — the domain and every rule. `can_start()` is the single
  gate that both the TUI and CLI call; don't duplicate its logic. `Tree`
  holds the walk/path/descendants helpers.
- `space/db.py` — SQLite. `roll_forward()` runs at startup; `set_status()`
  doubles as the clock (time accrues while a task is in `doing`).
- `space/theme.py` — the palette. `init()` writes real RGB into colour slots
  when `can_change_color()`, else falls back to ANSI. All `C_*` pair ids live
  here; `ui.py` re-exports them.
- `space/fx.py` — animation and texture: boot glitch, sweeps, eighth-block
  bars, the breathing caret. Everything aborts on a keypress and respects
  `SPACE_NO_FX`.
- `space/ui.py` — curses primitives, framed panels, the field editor, the
  reactive one-line prompt.
- `space/app.py` — the five views.
- `space/cli.py` — scriptable commands.
- `space/review.py` — the daily questions and the Sunday weekly. Two answers
  a day: `days.shipped` is what you did (it keeps its original name) and
  `days.missed` is what you didn't. `pending()`
  is what the reminder script and the board both ask. `review_day()` is the
  writable day — yesterday until 04:00, then today — because the question is
  asked at midnight, when the day being reported on has just ended. Nothing
  older is ever writable, by design.
- `space/track.py` — Hyprland focus tracker. Banks seconds, checks (focus
  gained), interactions (title changes while focused) and the longest stretch,
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
- Ship vs Support is on every task and drives the day strip and Review.
- Unfinished tasks roll to today and increment `rolls`.
- No third-party dependencies. The point is that it starts instantly.

Gotchas already paid for:
- `curses.addnstr`'s limit counts bytes; screen positions are columns. `put()`
  trims by column, then passes the byte length. Don't "simplify" it back.
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
- `App.alive()` decides whether the main loop animates or blocks. Keep it
  cheap and keep it honest: an idle board must block.
- **Run `python3 scripts/smoke.py` before committing any UI change.** Importing
  a module proves nothing about a curses app — a missing method only blows up
  on the frame that calls it. The smoke test drives the real TUI in a pty
  through every view and panel, with effects on and off, and fails on any
  traceback. It was written after a regex tidy-up silently deleted a method
  that `import space.app` was perfectly happy about.
