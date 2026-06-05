#!/usr/bin/env bash
# Claude Code hook: prefix a state emoji to the current tmux window name.
# Usage: update-tmux-window-title.sh <emoji>

set -u

# Only run inside tmux.
[ -n "${TMUX_PANE:-}" ] || exit 0

state="${1:-}"
[ -n "$state" ] || exit 0

window_id=$(tmux display-message -p -t "$TMUX_PANE" '#I' 2>/dev/null) || exit 0
current=$(tmux display-message -p -t "$TMUX_PANE" '#W' 2>/dev/null) || exit 0

# Strip any existing leading state emoji so emojis don't stack.
stripped=$(printf '%s' "$current" | sed -E 's/^(🟡|🔴|🟢) ?//')

# Fall back to the pane path basename when the stripped name is empty
# (e.g., automatic-rename produced something we already consumed).
if [ -z "$stripped" ]; then
  stripped=$(tmux display-message -p -t "$TMUX_PANE" '#{b:pane_current_path}' 2>/dev/null)
fi

tmux rename-window -t "$window_id" "${state} ${stripped}" 2>/dev/null || true
exit 0
