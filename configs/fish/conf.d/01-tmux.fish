# Auto-start tmuxinator workspace (ws)
# - Only in interactive terminal
# - Not if already inside tmux
# - Not in screen/tmux TERM types
if status is-interactive
    and not set -q TMUX
    and not string match -q "screen*" $TERM
    if type -q tmuxinator
        tmuxinator start ws
    else
        tmux new-session -A -s ws
    end
end
