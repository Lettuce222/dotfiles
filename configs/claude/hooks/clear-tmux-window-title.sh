#!/usr/bin/env bash
# Claude Code hook: strip the leading state emoji from the tmux window name
# when no other Claude process is running in any other pane of the same window.

set -u

[ -n "${TMUX_PANE:-}" ] || exit 0

window_id=$(tmux display-message -p -t "$TMUX_PANE" '#I' 2>/dev/null) || exit 0
session=$(tmux display-message -p -t "$TMUX_PANE" '#S' 2>/dev/null) || exit 0
current_pane=$(tmux display-message -p -t "$TMUX_PANE" '#{pane_id}' 2>/dev/null) || exit 0

other_pane_pids=$(tmux list-panes -t "${session}:${window_id}" \
  -F '#{pane_id} #{pane_pid}' 2>/dev/null \
  | awk -v cur="$current_pane" '$1 != cur { print $2 }')

other_claude_running=0
queue="$other_pane_pids"
while [ -n "$queue" ]; do
  next=""
  for pid in $queue; do
    args=$(ps -o args= -p "$pid" 2>/dev/null || true)
    if [[ "$args" =~ /claude($|[[:space:]]) ]]; then
      other_claude_running=1
      break 2
    fi
    kids=$(pgrep -P "$pid" 2>/dev/null || true)
    next="$next $kids"
  done
  queue="$next"
done

if [ "$other_claude_running" -eq 0 ]; then
  current=$(tmux display-message -p -t "$TMUX_PANE" '#W' 2>/dev/null) || exit 0
  stripped=$(printf '%s' "$current" | sed -E 's/^(🟡|🔴|🟢) ?//')
  if [ -z "$stripped" ]; then
    stripped=$(tmux display-message -p -t "$TMUX_PANE" '#{b:pane_current_path}' 2>/dev/null)
  fi
  tmux rename-window -t "$window_id" "$stripped" 2>/dev/null || true
fi

exit 0
