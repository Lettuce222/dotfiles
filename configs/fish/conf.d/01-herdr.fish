# Auto-start Herdr workspace
# - Only in interactive terminal
# - Not if already inside Herdr (panes export HERDR_ENV=1)
# - Not inside the explicitly started tmux fallback
if status is-interactive
    and not set -q HERDR_ENV
    and not set -q TMUX
    and type -q herdr
    herdr
end
