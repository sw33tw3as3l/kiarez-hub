#!/usr/bin/env bash
# Timestamped backup of the board: a JSON dump plus a copy of the SQLite file.
# Keeps the 20 most recent; safe to run from cron.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
dest="${KIAREZ_SPACE_BACKUPS:-$HOME/.kiarez-space/backups}"
stamp="$(date +%Y-%m-%dT%H%M%S)"
mkdir -p "$dest"

"$repo/bin/space-cli" export > "$dest/board-$stamp.json"

db="${KIAREZ_SPACE_DB:-$HOME/.kiarez-space/data.db}"
[ -f "$db" ] && cp "$db" "$dest/data-$stamp.db"

# Trim old backups, newest first.
ls -1t "$dest"/board-*.json 2>/dev/null | tail -n +21 | xargs -r rm --
ls -1t "$dest"/data-*.db    2>/dev/null | tail -n +21 | xargs -r rm --

echo "backed up to $dest/board-$stamp.json"
