# kiarez space

A task board that runs in your terminal. Four views — day board, calendar,
long-term, goals — over a single SQLite file. Python standard library only:
nothing to install, no server, no browser, no network.

Replaces the previous Next.js + Supabase web version; the old code is still
in this repository's git history.

## Run it

```bash
./bin/space
```

Put it on your PATH once:

```bash
./scripts/install.sh
```

Then `space` opens the board and `space-cli` scripts against it.

## Keys

| Key | Does |
| --- | --- |
| `1`–`4`, `Tab` | Board / Calendar / Long-term / Goals |
| `j` `k` | move down / up |
| `h` `l` | move between To Do / Doing / Done |
| `J` `K` | reorder a task inside its column |
| `space` | advance status (todo → doing → done) |
| `n` / `g` | new task / new goal |
| `e`, `Enter` | edit |
| `x` | delete (asks first) |
| `[` `]` | previous / next day |
| `t` | jump to today |
| `?` | help |
| `q` | quit |

In a form: type to edit, `←`/`→` change a choice, `Enter` next field,
`Ctrl-S` or `F2` save, `Esc` cancel.

## The rules it enforces

A task is not accepted until it has all four:

- a **goal** it belongs to
- an **outcome** — the definition of done
- an **effort** size
- a **next action** — the first physical step

Anything half a day or bigger is refused on the day board; it belongs in
Long-term, split into smaller pieces. This is the same rule the web version
enforced, moved into `space/model.py` where both the TUI and the CLI use it.

## Scripting it

```bash
space-cli today                  # the day board
space-cli ls --status doing      # filter by status, category, date, goal
space-cli ls --json              # machine-readable
space-cli done 4f2a              # any unambiguous id prefix, like git
space-cli goals
space-cli stats
space-cli export > backup.json
```

`--plain` drops the ANSI color, for piping.

## Data

`~/.kiarez-space/data.db`, or wherever `KIAREZ_SPACE_DB` points.

```bash
./scripts/backup.sh              # timestamped JSON + db copy, keeps the last 20
```

`scripts/import-export.py` loads a `supabase-export.json` into the local
database. It already ran once for the migration — 18 goals and 195 tasks —
and is idempotent if you ever need it again.
