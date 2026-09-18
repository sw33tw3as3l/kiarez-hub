#!/usr/bin/env bash
# Fires one notification a day, at SPACE_REVIEW_AT (default 21:30), if the
# day's question is still unanswered. Clicking it opens the review.
#
# Started from Hyprland alongside the tracker. Sleeps almost all the time;
# it is a clock, not a daemon doing work.
set -uo pipefail

AT="${SPACE_REVIEW_AT:-21:30}"
REVIEW="$HOME/.local/bin/space-review"
TERMINAL="${SPACE_TERMINAL:-kitty}"

notify() {
  local title="kiarez space" body="How did today go? One question."
  if command -v dunstify >/dev/null; then
    # dunstify blocks until the notification is acted on or expires, and
    # prints the chosen action — so a click can open the review directly.
    if [ "$(dunstify --action='open,Answer now' --urgency=normal \
              --appname='kiarez space' "$title" "$body")" = "open" ]; then
      setsid "$TERMINAL" -e "$REVIEW" >/dev/null 2>&1 &
    fi
  else
    notify-send --app-name='kiarez space' "$title" "$body — run space-review"
  fi
}

while true; do
  # Seconds until the next occurrence of AT, today or tomorrow.
  now=$(date +%s)
  target=$(date -d "today $AT" +%s)
  [ "$target" -le "$now" ] && target=$(date -d "tomorrow $AT" +%s)
  sleep $(( target - now ))

  # Only interrupt if there is actually something to answer.
  if "$REVIEW" --check; then
    notify
  fi
  sleep 60          # don't re-fire inside the same minute
done
