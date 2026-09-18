# kiarez space

A local task board. Python 3 standard library only — `curses`, `sqlite3`,
`socket`. No dependencies, no server, no network.

- `space/model.py` — the domain and every rule. `can_start()` is the single
  gate that both the TUI and CLI call; don't duplicate its logic.
- `space/db.py` — SQLite. `roll_forward()` runs at startup; `set_status()`
  doubles as the clock (time accrues while a task is in `doing`).
- `space/ui.py` — curses primitives, the field editor, the one-line prompt.
- `space/app.py` — the five views.
- `space/cli.py` — scriptable commands.
- `space/track.py` — Hyprland focus tracker.

Rules that matter:
- **Capture is free, starting is not.** Anything can be created with a title
  alone. `can_start()` decides when it may move to `doing`.
- Areas are permanent. They have no completion, no target date, no progress.
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
