#!/usr/bin/env bash
# Strip the leading 🟢 from the currently active tmux window name.
# Intended to be wired to tmux's session-window-changed hook so the idle
# indicator clears as soon as the user focuses the window. 🔴 and 🟡 are
# left untouched.

set -u

[ -n "${TMUX:-}" ] || exit 0

window_id=$(tmux display-message -p '#{window_id}' 2>/dev/null) || exit 0
current=$(tmux display-message -p '#{window_name}' 2>/dev/null) || exit 0

stripped=$(printf '%s' "$current" | sed -E 's/^🟢 ?//')

if [ "$current" = "$stripped" ]; then
  exit 0
fi

if [ -z "$stripped" ]; then
  stripped=$(tmux display-message -p '#{b:pane_current_path}' 2>/dev/null)
fi

tmux rename-window -t "$window_id" "$stripped" 2>/dev/null || true
exit 0
