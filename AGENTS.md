# kiarez space

A local task board. Python 3 standard library only — `curses` for the TUI,
`sqlite3` for storage. No framework, no server, no network calls, no
dependencies to install.

- `space/` — the program: `model.py` (domain rules), `db.py` (SQLite),
  `ui.py` (curses primitives and the field editor), `app.py` (the four
  views), `cli.py` (scriptable commands).
- `bin/` — launchers. `scripts/` — install, backup, one-time Supabase import.
- Data lives at `~/.kiarez-space/data.db`, overridable with `KIAREZ_SPACE_DB`.

Rules that matter:
- Every task needs a goal, an outcome (definition of done), an effort size,
  and a next action. `model.validate_task` is the single place that decides
  this — the TUI form and the CLI both call it.
- Half-day or bigger can't sit on the day board; it goes to Long-term.
- Don't add third-party dependencies. The point of this rewrite was that it
  starts instantly and has nothing to break.
