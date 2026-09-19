#!/usr/bin/env bash
# Fires one notification a day, at SPACE_REVIEW_AT (default 00:00), if the
# day's question is still unanswered. Clicking it opens the review.
#
# Midnight is when the day you are reporting on has just ended, which is why
# the reviewable day runs to 04:00 — see DAY_ENDS_AT in space/review.py.
#
# Started from Hyprland alongside the tracker. Sleeps almost all the time;
# it is a clock, not a daemon doing work.
set -uo pipefail

AT="${SPACE_REVIEW_AT:-00:00}"
REVIEW="$HOME/.local/bin/space-review"
TERMINAL="${SPACE_TERMINAL:-kitty}"

notify() {
  local title="kiarez space" body="How did the day go? One question."
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

# The day locks a few hours after the question is asked, and a notification
# that lands while you are asleep or away is a notification that never
# happened — the first real night proved it, with a permanently blank day.
# So after the first one, keep checking until the window closes, and only
# speak up when the session is actually unlocked. A locked screen means
# nobody is there to answer, and buzzing at them achieves nothing.
RETRY_EVERY="${SPACE_REVIEW_RETRY:-900}"

session_unlocked() {
  [ "$(loginctl show-session "${XDG_SESSION_ID:-self}" -p LockedHint --value \
       2>/dev/null)" != "yes" ]
}

while true; do
  # Seconds until the next occurrence of AT, today or tomorrow.
  now=$(date +%s)
  target=$(date -d "today $AT" +%s)
  [ "$target" -le "$now" ] && target=$(date -d "tomorrow $AT" +%s)
  sleep $(( target - now ))

  # Which day this round is about. Everything below is tied to it, so when
  # the window rolls over to the next day the loop ends instead of quietly
  # becoming an all-day nag about a day that is not due yet.
  day="$("$REVIEW" --day)"

  # Only interrupt if there is actually something to answer.
  "$REVIEW" --check --for "$day" && notify

  # Then keep an eye on it until that day's window closes, catching you
  # whenever you come back to the keyboard rather than only at midnight.
  while "$REVIEW" --check --for "$day"; do
    sleep "$RETRY_EVERY"
    "$REVIEW" --check --for "$day" || break
    session_unlocked && notify
  done
  sleep 60          # don't re-fire inside the same minute
done
