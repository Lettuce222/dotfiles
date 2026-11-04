function hub2 --description '窓口（claude -n orchestrator）と claude agents の 2 ペインの window を開く'
    # 小さな窓口の構成。左に窓口の Claude Code、右に claude agents の一覧を置く。
    # 窓口の決まりはスキル agents-orchestrator に、スレッドの決まりは agents-thread に書く。
    # 今の hub（hub.fish、agent-hub/）とは tmux session も Claude のセッション名も分ける
    set -l session hub2
    set -l name orchestrator
    set -l dir (test -n "$AGENT_HUB2_HOME"; and echo $AGENT_HUB2_HOME; or echo $HOME/hub)
    if not test -d $dir
        mkdir -p $dir; and chmod 700 $dir
    end

    if not tmux has-session -t "=$session" 2>/dev/null
        # 非対話の fish では conf.d の mise・direnv が動かないので、起動前に環境を取り込む。
        # スレッドとセッション間でメッセージを送り合うので、permission mode を auto で揃える
        set -l env_file ~/.config/tmux/scripts/agent-hub/agent-env.fish
        set -l prefix
        test -f $env_file; and set prefix source (string escape -- $env_file)\;
        set -l left fish -c (string join ' ' -- $prefix \
            claude -n $name --permission-mode auto (string escape -- /agents-orchestrator))
        set -l right fish -c (string join ' ' -- $prefix claude agents --permission-mode auto)

        set -l pane (tmux new-session -d -P -F '#{pane_id}' -s $session -n $name -c $dir $left)
        or begin
            echo "hub2: tmux session を作れませんでした" >&2
            return 1
        end
        tmux split-window -h -d -l 45% -t $pane -c $dir $right
        tmux select-pane -t $pane
    end

    if set -q TMUX
        tmux switch-client -t "=$session"
    else
        tmux attach-session -t "=$session"
    end
end
