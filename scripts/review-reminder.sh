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
  local day="${1:-the day}"
  local title="kiarez space"
  local body="How did $day go? Two questions, about a minute."
  if command -v dunstify >/dev/null; then
    # dunstify blocks until the notification is acted on or expires, so the
    # wait goes in a subshell; otherwise every retry interval is measured
    # from when you dismissed the last one rather than from when it was sent.
    (
      if [ "$(dunstify --action='open,Answer now' --urgency=normal \
                --appname='kiarez space' "$title" "$body")" = "open" ]; then
        setsid "$TERMINAL" -e "$REVIEW" >/dev/null 2>&1
      fi
    ) &
  else
    notify-send --app-name='kiarez space' "$title" "$body — run space-review"
  fi
}

# A notification that lands while you are asleep is a notification that never
# happened, so it keeps trying until the day is answered — but the window is
# now the whole day, and a fixed quarter-hour retry across a day is ninety-six
# interruptions, which is how a reminder gets muted forever. So it backs off:
# fifteen minutes, then half an hour, an hour, two, and four thereafter —
# about six in a day. It also only speaks while the session is unlocked, since
# buzzing at a locked screen achieves nothing.
RETRY_FIRST="${SPACE_REVIEW_RETRY:-900}"
RETRY_MAX="${SPACE_REVIEW_RETRY_MAX:-14400}"
RETRY_TIMES="${SPACE_REVIEW_RETRY_TIMES:-4}"   # after these, the lock can argue

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
  "$REVIEW" --check --for "$day" && notify "$day"

  # Then keep an eye on it until that day's window closes, catching you
  # whenever you come back to the keyboard rather than only at midnight.
  wait_for="$RETRY_FIRST"
  tries=0
  while [ "$tries" -lt "$RETRY_TIMES" ] && "$REVIEW" --check --for "$day"; do
    sleep "$wait_for"
    "$REVIEW" --check --for "$day" || break
    if session_unlocked; then
      notify "$day"
      tries=$(( tries + 1 ))
    fi
    wait_for=$(( wait_for * 2 ))
    [ "$wait_for" -gt "$RETRY_MAX" ] && wait_for="$RETRY_MAX"
  done
  sleep 60          # don't re-fire inside the same minute
done
