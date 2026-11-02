#!/usr/bin/env fish

# 窓口（hub）の Claude Code がいる tmux window へ移動する。無ければ起動する。
# tmux の中からでも外からでも、同じ 1 つの hub に行き着くようにする。

# worker の報告先になるセッション名。spawn.fish と同じ変数を読む
set -l hub_name (test -n "$AGENT_HUB_NAME"; and echo $AGENT_HUB_NAME; or echo hub)
# fish 経由で起動し、agent-env.fish で作業場所の環境を取り込む。
# 起動直後に hub-rules.md の「起動したとき」の手順を実行させる
set -l script_dir (path resolve -- (status dirname))
set -l hub_command fish -c (string join ' ' -- \
    source (string escape -- $script_dir/agent-env.fish)\; \
    claude -n (string escape -- $hub_name) --permission-mode auto \
    --append-system-prompt-file (string escape -- $script_dir/hub-rules.md) \
    (string escape -- '「起動したとき」の手順を実行してください。'))
# 議事録や GTD のリストを置く個人用の作業場所。dotfiles では管理しない
set -l hub_dir (test -n "$AGENT_HUB_HOME"; and echo $AGENT_HUB_HOME; or echo $HOME/hub)
# 議事録の原文を置くので、新しく作るときは自分だけが読めるようにする
if not test -d $hub_dir
    mkdir -p $hub_dir; and chmod 700 $hub_dir
end

# window 名は Claude の状態絵文字で変わるので、window option の印で探す
set -l window_id
for line in (tmux list-windows -a -F '#{window_id} #{@agent-hub}' 2>/dev/null)
    set -l fields (string split ' ' -- $line)
    if test "$fields[2]" = 1
        set window_id $fields[1]
        break
    end
end

# 無ければ、どこから呼ばれても専用の tmux session "hub" の中に作る
if test -z "$window_id"
    if tmux has-session -t '=hub' 2>/dev/null
        set window_id (tmux new-window -d -P -F '#{window_id}' -t '=hub:' -n hub -c $hub_dir \
            -e AGENT_HUB_NAME=$hub_name $hub_command)
    else
        set window_id (tmux new-session -d -P -F '#{window_id}' -s hub -n hub -c $hub_dir \
            -e AGENT_HUB_NAME=$hub_name $hub_command)
    end
    test -n "$window_id"; or begin
        echo "hub: tmux window を作れませんでした" >&2
        exit 1
    end
    tmux set-option -w -t $window_id @agent-hub 1
    or begin
        echo "hub: window $window_id がすぐに閉じました。claude の起動に失敗しています" >&2
        exit 1
    end
end

tmux select-window -t $window_id
if set -q TMUX
    tmux switch-client -t $window_id
else
    exec tmux attach-session -t $window_id
end
