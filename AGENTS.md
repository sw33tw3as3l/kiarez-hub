# kiarez space

A local task board. Python 3 standard library only — `curses`, `sqlite3`,
`socket`. No dependencies, no server, no network.

- `space/model.py` — the domain and every rule. `can_start()` is the single
  gate that both the TUI and CLI call; don't duplicate its logic. `Tree`
  holds the walk/path/descendants helpers.
- `space/db.py` — SQLite. `roll_forward()` runs at startup; `set_status()`
  doubles as the clock (time accrues while a task is in `doing`).
- `space/ui.py` — curses primitives, the field editor, the one-line prompt.
- `space/app.py` — the five views.
- `space/cli.py` — scriptable commands.
- `space/review.py` — the daily question and the Sunday weekly. `pending()`
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
  since multibyte characters make a column count too short.
