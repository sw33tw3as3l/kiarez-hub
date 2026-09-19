# kiarez space

A task board in your terminal, built around one question: **was today real?**

Python standard library only — `curses`, `sqlite3`. Nothing to install, no
server, no browser, no network.

Neon on a dark ground: hot magenta and electric cyan carry the chrome, mint
is success, amber is work in progress, red is what it costs you. In a
terminal that allows it (kitty does) the exact hex values are written into
colour slots rather than approximated. Effects are short and skippable —
`SPACE_NO_FX=1` turns every animation off.

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
| estimate | checked against what it actually took, per size |

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
   seven days went, how far off your estimates are *per size*, and every task
   that has been untouched for two weeks or rolled forward three times.

### Estimating

Time accrues while a task sits in Doing, and one unbroken stretch counts at
most four hours (`SPACE_MAX_DOING_MINUTES`) — a task left running overnight
is a forgotten timer, not a long day, and without the cap a single lapse
poisons the history for good. While a task is over the cap the day strip says
"stopped counting" rather than quietly inventing hours.

Accuracy is kept per size and reported as a **median**, so one bad sample
can't redefine what an hour means to you:

```
15m       →    15m   1.0×   ██████              n=5
30m       →    51m   1.7×   ██████████▎         n=5
1h        →   1h37   1.6×   █████████▊          n=5
2h        →   4h02   2.0×   ████████████▏       n=5
```

The form tells you this while you are choosing, which is the only moment it
can change anything: standing on "1h" reads *your 1h tasks actually take
1h37 (1.6×, optimistic, n=5)*.

## Keys

| Key | Does |
| --- | --- |
| `1`–`5`, `Tab` | switch view |
| `c` | capture — one line, no fields, from anywhere |
| `/` | filter the board; the panel counts matches as you type, empty clears |
| `j` `k` `h` `l` | move · `J` `K` reorder |
| `space` | advance status — refuses to start an undefined task |
| `e`, `Enter` | define / edit |
| `s` `S` | schedule onto the open day / send back to inbox |
| `w` | log what shipped today |
| `a` `A` | in Tree: add a child / add a root |
| `m` `x` | in Tree: move (reparent) / delete a node and its subtree |
| `[` `]` `t` | previous day / next day / today |
| `<` `>` | move the selected task to another day |
| `g` | go to a date — `2026-12-25`, or `+3` / `-7` days from today |
| `?` `q` | help / quit |

In a form: type to edit, `←`/`→` change a choice — every option is on screen
as a chip, so nothing is arrowed through blind — `Enter` next field, `Ctrl-S`
or `F2` save, `Esc` cancel (which asks first if you've typed anything).

Things move when there's a reason to: the title resolves out of noise on
launch, the caret breathes, prompts answer back as you type, finishing
something sends a wave of light across the footer — magenta for a ship, mint
for support — and the distraction figure pulses once it passes an hour. An
idle board blocks on input and costs nothing; it only animates while
something on screen is actually moving.

## Focus tracking

`space-track` listens to Hyprland's event socket and records four numbers per
watched app per day. No polling, no extra packages, no screenshots.

Four apps are tracked out of the box, each with a colour: **Telegram (red)**,
Chrome (yellow), Claude (green), Terminal (green). Red means time spent
against you — it's what the day strip counts as distraction. Everything else
is simply time accounted for.

| Number | Means |
| --- | --- |
| focused | how long it held the keyboard |
| checks | how many separate times you went to it |
| longest | the longest unbroken stretch |
| interactions | title changes while it stayed focused — in a chat app, moving between conversations |

Time alone undercounts the damage: forty 3-minute checks and one 2-hour
session are the same number of minutes and nothing like the same day.

```bash
space-cli focus                              # every watched app today
space-cli focus --week                       # a row per app, a column per day
space-cli focus --app telegram               # the full picture, by hour
space-cli focus --app telegram --days 30
space-cli watch                              # the list and its colours
space-cli watch --add code --label Editor --color green
hyprctl clients -j | grep class              # find an app's class
```

```
Telegram — 2026-09-18
  focused      1h30
  checks       24    (separate times you went to it)
  longest      22m   (single unbroken stretch)
  interactions 40    (moves between chats/views inside it)
  per check    3m
```

Time is only recorded for apps on the watchlist, and only while you are
actually there. "Focused" and "in front of you" are not the same thing, so:

- **A locked screen counts for nothing.** When the session locks, the idle
  minutes that preceded the lock are deducted from what was already banked —
  hypridle locks after five idle minutes here, so five minutes come back off
  (`SPACE_IDLE_BEFORE_LOCK` to match a different timeout).
- **A single unbroken stretch caps at 20 minutes** where no session manager
  answers. A window left in front overnight cannot bank the night.
- **Unread counters in window titles are ignored**, so an arriving message
  isn't mistaken for you switching chats.

It starts with your Hyprland session via `~/.config/hypr/custom/execs.lua`.
`scripts/space-track.service` is there if you'd rather systemd supervise it.

## The daily questions

Two questions a day, always the same two, asked with the day's facts on screen
above them — finished tasks, ship count, screen time, Telegram checks. The
facts are the point: it is hard to type "good day" underneath 23 Telegram
checks and nothing shipped.

1. **What important things did you do today?**
2. **What important things did you not do today?**

The second is the one that does the work. What you did is already on the
board; what you didn't is recorded nowhere else, and is usually what the day
actually cost.

```bash
space-review            # or press w on the board
space-cli day           # read the answers back
```

- **The day stays answerable until 04:00**, then locks for good. The question
  arrives at midnight, when the day you're reporting on has just ended — so
  the boundary sits where the sleep does, not where the calendar does. An
  unanswered day stays blank forever; a journal you can backfill records what
  you wish had happened.
- **"nothing" is a real answer**, stored as such, and visible in the calendar.
- **Both answers show in the Calendar.** Each day is marked `✓` if you did
  something, `·` if you answered "nothing", and `!` if there was something you
  didn't do. Put the cursor on any day and both answers are spelled out below
  the month.
- No streaks, no score, no guilt — the numbers already do that job honestly.

A notification fires at **00:00** (`SPACE_REVIEW_AT` to change it) if the day
is still unanswered, and clicking it opens the review. If you miss it, the
board says so the next time you open it. Neither one blocks you.

**Sundays** add three more questions, where a week of data makes the answers
real: what actually moved, what you kept avoiding (the tool already knows —
it lists what you keep rolling forward), and the one thing you'll change.

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

## Checking it still works

```bash
python3 scripts/smoke.py     # the UI, in a real pseudo-terminal
python3 scripts/edges.py     # the data layer, in about a second
python3 scripts/sizes.py     # every view from 200x40 down to 24x8
python3 scripts/track-test.py  # the tracker, against a fake compositor
```

The smoke test walks every view, form and prompt with effects on and off,
runs every CLI command, and then — the part that matters — does things and
asks the database whether they happened. A form can go completely dead
without raising anything.

## Data

`~/.kiarez-space/data.db`, or wherever `KIAREZ_SPACE_DB` points.

```bash
./scripts/backup.sh     # timestamped JSON + db copy, keeps the last 20
```
