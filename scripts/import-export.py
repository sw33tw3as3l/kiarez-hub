#!/usr/bin/env python3
"""Load a supabase-export.json into the local SQLite database.

Idempotent: rows are keyed by their original UUID, so re-running replaces
rather than duplicates. Run from the repo root:

    python3 scripts/import-export.py supabase-export.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from space import db  # noqa: E402

GOAL_COLS = ["id", "title", "description", "target_date", "position",
             "archived", "created_at"]
TASK_COLS = ["id", "title", "description", "status", "category", "due_date",
             "due_time", "position", "created_at", "goal_id", "outcome",
             "effort", "next_action"]


def rows(records, cols):
    for r in records:
        out = []
        for c in cols:
            v = r.get(c)
            if c == "archived":
                v = 1 if v else 0
            elif c == "position":
                v = v or 0
            elif c == "created_at" and not v:
                v = db.now()
            out.append(v)
        yield out


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "supabase-export.json")
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 1

    data = json.loads(src.read_text())
    conn = db.connect()

    # Goals first — tasks reference them.
    conn.executemany(
        f"insert or replace into goals ({','.join(GOAL_COLS)}) "
        f"values ({','.join('?' * len(GOAL_COLS))})",
        rows(data.get("goals", []), GOAL_COLS),
    )
    conn.executemany(
        f"insert or replace into tasks ({','.join(TASK_COLS)}) "
        f"values ({','.join('?' * len(TASK_COLS))})",
        rows(data.get("tasks", []), TASK_COLS),
    )
    conn.commit()

    g = conn.execute("select count(*) from goals").fetchone()[0]
    t = conn.execute("select count(*) from tasks").fetchone()[0]
    print(f"imported into {db.db_path()}: {g} goals, {t} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
