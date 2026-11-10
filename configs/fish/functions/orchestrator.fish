function orchestrator --description '窓口（claude -n orchestrator）と案件の一覧の window を開く'
    # 小さな窓口の構成。左に窓口の Claude Code、右に案件の一覧（ケースボード）を置く。
    # worker とのやりとりは窓口に集約するので、claude agents のペインは置かない。
    # 窓口の決まりはスキル agents-orchestrator に、worker の決まりは agents-thread に書く。
    set -l session orchestrator
    set -l name orchestrator
    set -l dir (test -n "$AGENT_ORCHESTRATOR_HOME"; and echo $AGENT_ORCHESTRATOR_HOME; or echo $HOME/hub)
    if not test -d $dir
        mkdir -p $dir; and chmod 700 $dir
    end

    # 非対話の fish では conf.d の mise・direnv が動かないので、起動前に環境を取り込む。
    set -l env_file ~/.config/fish/agent-env.fish
    set -l prefix
    test -f $env_file; and set prefix source (string escape -- $env_file)\;

    if not tmux has-session -t "=$session" 2>/dev/null
        # worker とセッション間でメッセージを送り合うので、permission mode を auto で揃える
        set -l left fish -c (string join ' ' -- $prefix \
            claude -n $name --permission-mode auto (string escape -- /agents-orchestrator))

        set -l pane (tmux new-session -d -P -F '#{pane_id}' -s $session -n $name -c $dir $left)
        or begin
            echo "orchestrator: tmux session を作れませんでした" >&2
            return 1
        end
        tmux set-option -p -t $pane @orchestrator_role main
    end

    # window の名前は Claude Code の hook が状態の絵文字を付けて変えるので、先頭の window で指す
    set -l window "=$session:^"

    # 前の構成の claude agents のペインが残っていれば閉じる（ケースボードが場所を引き継ぐ）。
    for line in (tmux list-panes -t $window -F '#{pane_id} #{pane_start_command}')
        if string match -q -- '*claude agents*' $line
            tmux kill-pane -t (string split -m1 ' ' -- $line)[1]
        end
    end

    # 案件の一覧は右に置く。前からある session にも足す（無いときだけ）。
    # 表示が落ちてペインが閉じても、次に orchestrator を実行すれば戻る。
    set -l cases_py ~/.claude/skills/agents-orchestrator/scripts/cases.py
    if test -f $cases_py
        and not tmux list-panes -s -t "=$session" -F '#{@orchestrator_role}' | string match -q cases
        set -l board fish -c (string join ' ' -- $prefix python3 (string escape -- $cases_py) board)
        set -l main_pane (tmux display-message -p -t "$window.{left}" '#{pane_id}')
        set -l board_pane (tmux split-window -h -d -l 45% -P -F '#{pane_id}' -t $main_pane -c $dir $board)
        and tmux set-option -p -t $board_pane @orchestrator_role cases
    end

    tmux select-pane -t "$window.{left}"

    if set -q TMUX
        tmux switch-client -t "=$session"
    else
        tmux attach-session -t "=$session"
    end
end
