# kiarez space

A task board in your terminal, built around one question: **was today real?**

Python standard library only — `curses`, `sqlite3`. Nothing to install, no
server, no browser, no network.

```bash
space           # the board
space-track     # focus tracker (run once, in the background)
space-cli       # scripting
```

## The model

**A tree of things you care about.** Nest as deep as you like:

```
PayCheck
  Scoring
    Ship the grade endpoint
  Reduce churn
Health
  Gym 3x a week
```

A **branch is an area**, a **leaf is a goal** — and that is derived, not
stored, so a goal becomes an area the moment you nest something under it and
nothing has to be migrated. Nothing in the tree ever closes: no target dates,
no completion, no progress bars. A task can hang off any node, branch or leaf,
because the right place for a task is wherever you were thinking when you
wrote it down. Counts roll up: a branch shows the totals for everything
beneath it.

**Capture is free. Committing is not.** Press `c` anywhere and type one line;
it lands in the Inbox with no fields to fill. A task only has to be *defined*
before you can start it:

| Field | Why |
| --- | --- |
| goal | which node of the tree it serves |
| outcome | how you'll know it's done |
| next action | the first physical step |
| kind | **Ship** or **Support** |
| estimate | checked against what it actually took |

Trying to start an undefined task refuses and says what's missing. Friction
sits at the moment of commitment, not the moment of capture.

**Ship vs Support** is the real-work test. Ship means someone other than you
could notice it happened. Support is tooling, config, research, process —
work that only makes shipping easier later. Support isn't bad; a week that is
all support is.

**Days roll forward.** Anything unfinished moves to today automatically and
its roll count goes up. Nothing is lost, and nothing quietly rots on an old
date — but the Review view knows exactly what you keep pushing.

## The five views

1. **Today** — three columns, plus the strip that judges the day: ship ratio,
   distraction minutes, and what you said shipped.
2. **Calendar** — the month. `✓` = you logged something that shipped, `·` =
   you logged nothing. Both are honest answers; a blank day is neither.
3. **Inbox** — captured, not yet on a day. `s` schedules, `e` defines.
4. **Tree** — the whole forest, foldable, with counts rolled up.
5. **Review** — what the board would rather you didn't see: where the last
   seven days went, how far off your estimates are, and every task that has
   been untouched for two weeks or rolled forward three times.

## Keys

| Key | Does |
| --- | --- |
| `1`–`5`, `Tab` | switch view |
| `c` | capture — one line, no fields, from anywhere |
| `j` `k` `h` `l` | move · `J` `K` reorder |
| `space` | advance status — refuses to start an undefined task |
| `e`, `Enter` | define / edit |
| `s` `S` | schedule onto the open day / send back to inbox |
| `w` | log what shipped today |
| `a` `A` | in Tree: add a child / add a root |
| `m` `x` | in Tree: move (reparent) / delete a node and its subtree |
| `[` `]` `t` | previous day / next day / today |
| `?` `q` | help / quit |

In a form: type to edit, `←`/`→` change a choice, `Enter` next field,
`Ctrl-S` or `F2` save, `Esc` cancel.

## Focus tracking

`space-track` listens to Hyprland's event socket and records how long watched
apps hold the keyboard. No polling, no extra packages, no screenshots — just
seconds per app per day.

```bash
space-cli watch                              # what's watched
space-cli watch --add org.telegram.desktop --label Telegram
space-cli focus                              # where today went
hyprctl clients -j | grep class              # find an app's class
```

Telegram and Chrome are watched by default. Time is only recorded for apps on
the watchlist, and a window focused for more than 15 minutes without a switch
stops counting — that's you walking away, not you working.

To start it with your session, see `scripts/space-track.service` (nothing in
this repo installs it for you).

## Scripting

```bash
space-cli c "something I thought of"      # capture
space-cli today
space-cli inbox
space-cli tree
space-cli node-add Scoring --parent paycheck
space-cli node-mv scoring --parent health        # or --root
space-cli define 4f2a --goal "grade endpoint" --outcome "..." \
                      --kind ship --estimate 1h --next "..."
space-cli ls --goal paycheck --deep              # the whole subtree
space-cli start 4f2a          # refuses if undefined
space-cli done 4f2a
space-cli shipped "the grade endpoint is live"
space-cli focus
space-cli review
space-cli ls --json
```

Task ids take any unambiguous prefix, like git. `--plain` drops the color.

## Data

`~/.kiarez-space/data.db`, or wherever `KIAREZ_SPACE_DB` points.

```bash
./scripts/backup.sh     # timestamped JSON + db copy, keeps the last 20
```
