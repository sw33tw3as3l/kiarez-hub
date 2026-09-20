#!/usr/bin/env bash
# Watch a GitHub repository's activity feed and notify when anyone touches it.
#
# The same feed the /activity page shows — pushes, branch creations and
# deletions, force-pushes, merges — for private repositories too, via the gh
# CLI's credentials. Nothing is polled harder than it changes: a repository a
# team pushes to a few times a day does not need to be asked every minute.
#
#   SPACE_WATCH_REPO=owner/name   which repository (default below)
#   SPACE_WATCH_EVERY=300         seconds between checks
set -uo pipefail

REPO="${SPACE_WATCH_REPO:-AriaHemmati/PayCheck}"
EVERY="${SPACE_WATCH_EVERY:-300}"
STATE_DIR="$HOME/.kiarez-space"
STATE="$STATE_DIR/repo-watch.$(printf '%s' "$REPO" | tr '/' '_').id"
URL="https://github.com/$REPO/activity"
mkdir -p "$STATE_DIR"

command -v gh >/dev/null || { echo "gh is not installed" >&2; exit 1; }

# id<TAB>one-line description, newest first.
fetch() {
  gh api "repos/$REPO/activity?per_page=20" \
     --jq '.[] | "\(.id)\t\(.actor.login) \(.activity_type|sub("_";" ")) \(.ref|sub("refs/heads/";""))"' \
     2>/dev/null
}

announce() {
  local count="$1" summary="$2"
  local title="$REPO"
  local body
  if [ "$count" -eq 1 ]; then body="$summary"
  else body="$count new · $summary"
  fi
  if command -v dunstify >/dev/null; then
    # dunstify blocks until the notification is acted on or expires, so the
    # wait goes in a subshell — otherwise the watcher stops watching for as
    # long as its own notification is on screen, and never records what it
    # just saw.
    (
      if [ "$(dunstify --action='open,Open activity' --appname='github' \
                --urgency=normal "$title" "$body")" = "open" ]; then
        setsid xdg-open "$URL" >/dev/null 2>&1
      fi
    ) &
  else
    notify-send --app-name='github' "$title" "$body"
  fi
}

while true; do
  lines="$(fetch)"
  if [ -n "$lines" ]; then
    newest="$(printf '%s\n' "$lines" | head -1 | cut -f1)"
    seen="$(cat "$STATE" 2>/dev/null || true)"

    if [ -z "$seen" ]; then
      # First run: remember where we are rather than announcing history.
      printf '%s' "$newest" > "$STATE"
    elif [ "$newest" != "$seen" ]; then
      fresh="$(printf '%s\n' "$lines" | awk -F'\t' -v seen="$seen" \
                 '$1 == seen {exit} {print}')"
      count="$(printf '%s\n' "$fresh" | grep -c . || true)"
      if [ "${count:-0}" -gt 0 ]; then
        announce "$count" "$(printf '%s\n' "$fresh" | head -1 | cut -f2-)"
      fi
      printf '%s' "$newest" > "$STATE"
    fi
  fi
  sleep "$EVERY"
done
