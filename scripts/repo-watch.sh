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

log() { printf '%s  %s\n' "$(date '+%F %T')" "$*"; }

# id<TAB>one-line description, newest first. Prints nothing and fails when the
# API does — gh writes its error body to STDOUT, so a 404 or an expired token
# looks exactly like data unless the exit status is checked. It used to be
# written into the state file as the newest id, which then made the next
# successful poll announce everything it could see.
fetch() {
  local out
  out="$(gh api "repos/$REPO/activity?per_page=20" \
          --jq '.[] | "\(.id)\t\(.actor.login) \(.activity_type|sub("_";" ")) \(.ref|sub("refs/heads/";""))"' \
          2>/dev/null)" || return 1
  # Every line must start with a numeric id, or it is not the feed.
  printf '%s\n' "$out" | grep -qE '^[0-9]+\s' || return 1
  printf '%s\n' "$out"
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

log "watching $REPO every ${EVERY}s"
failures=0

while true; do
  if ! lines="$(fetch)"; then
    # Silence has to mean "nothing happened", never "I stopped working" —
    # so a run of failures says so once, rather than looking like calm.
    failures=$(( failures + 1 ))
    log "cannot read $REPO (attempt $failures)"
    if [ "$failures" -eq 3 ]; then
      log "saying so out loud"
      announce 1 "cannot read this repository — check: gh auth status"
    fi
    sleep "$EVERY"
    continue
  fi
  if [ "$failures" -ge 3 ]; then
    log "reading $REPO again after $failures failures"
    announce 1 "back in touch with this repository"
  fi
  failures=0

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
        log "$count new: $(printf '%s\n' "$fresh" | head -1 | cut -f2-)"
        announce "$count" "$(printf '%s\n' "$fresh" | head -1 | cut -f2-)"
      fi
      printf '%s' "$newest" > "$STATE"
    fi
  fi
  sleep "$EVERY"
done
