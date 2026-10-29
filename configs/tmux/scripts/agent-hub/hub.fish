#!/usr/bin/env fish

# 窓口（hub）の Claude Code がいる tmux window へ移動する。無ければ起動する。

set -l hub_command claude -n hub --permission-mode auto \
    --append-system-prompt-file (status dirname)/hub-rules.md
set -l hub_dir (ghq root)

# tmux の外から呼ばれたら、hub session を用意して attach する
if not set -q TMUX
    if not tmux has-session -t hub 2>/dev/null
        set -l window_id (tmux new-session -d -P -F '#{window_id}' -s hub -n hub -c $hub_dir $hub_command)
        tmux set-option -w -t $window_id @agent-hub 1
    end
    exec tmux attach-session -t hub
end

# window 名は Claude の状態絵文字で変わるので、window option の印で探す
for line in (tmux list-windows -a -F '#{window_id} #{@agent-hub}')
    set -l fields (string split ' ' -- $line)
    if test "$fields[2]" = 1
        tmux switch-client -t $fields[1]
        exit
    end
end

set -l window_id (tmux new-window -P -F '#{window_id}' -n hub -c $hub_dir $hub_command)
tmux set-option -w -t $window_id @agent-hub 1
