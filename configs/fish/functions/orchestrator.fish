function orchestrator --description 'メインの agent を窓口にして案件の一覧を開く'
    set -l provider (agent --which)
    or return
    set -l assets ~/.config/dotfiles-agent
    set -l session orchestrator
    set -l name orchestrator
    set -l dir "$AGENT_ORCHESTRATOR_HOME"
    test -n "$dir"; or set dir "$HOME/hub"
    if not test -d "$dir"
        mkdir -p "$dir"; and chmod 700 "$dir"
        or return
    end

    # 非対話の fish では conf.d の mise・direnv が動かないので、起動前に環境を取り込む。
    set -l env_file ~/.config/fish/agent-env.fish
    set -l prefix
    test -f "$env_file"; and set prefix source (string escape -- "$env_file")\;

    set -l board_args board
    if test "$provider" = codex
        # Claude の窓口が動いていても、Codex は別セッションで開く。
        set session orchestrator-codex
        set -a board_args --no-workers
    end

    if not tmux has-session -t "=$session" 2>/dev/null
        set -l launch
        switch $provider
            case claude
                # worker とメッセージを送り合うので permission mode を auto で揃える。
                set launch claude -n $name --permission-mode auto /agents-orchestrator
            case codex
                set -l prompt (string collect < "$assets/codex-orchestrator.md")
                or return
                set launch codex (string escape -- "$prompt")
        end
        set -l left fish -c (string join ' ' -- $prefix $launch)

        set -l pane (tmux new-session -d -P -F '#{pane_id}' -s $session -n $name -c "$dir" $left)
        or begin
            echo "orchestrator: tmux session を作れませんでした" >&2
            return 1
        end
        tmux set-option -p -t $pane @orchestrator_role main
    end

    # window の名前は Claude Code の hook が状態の絵文字を付けて変えるので、先頭の window で指す
    set -l window "=$session:^"

    # 前の構成の claude agents のペインが残っていれば閉じる（ケースボードが場所を引き継ぐ）。
    if test "$provider" = claude
        for line in (tmux list-panes -t $window -F '#{pane_id} #{pane_start_command}')
            if string match -q -- '*claude agents*' "$line"
                tmux kill-pane -t (string split -m1 ' ' -- "$line")[1]
            end
        end
    end

    # 案件の一覧は右に置く。前からある session にも足す（無いときだけ）。
    # 表示が落ちてペインが閉じても、次に orchestrator を実行すれば戻る。
    set -l cases_py "$assets/skills/agents-orchestrator/scripts/cases.py"
    if test -f $cases_py
        and not tmux list-panes -s -t "=$session" -F '#{@orchestrator_role}' | string match -q cases
        set -l board fish -c (string join ' ' -- $prefix python3 (string escape -- "$cases_py") $board_args)
        set -l main_pane (tmux display-message -p -t "$window.{left}" '#{pane_id}')
        set -l board_pane (tmux split-window -h -d -l 45% -P -F '#{pane_id}' -t $main_pane -c "$dir" $board)
        and tmux set-option -p -t $board_pane @orchestrator_role cases
    end

    tmux select-pane -t "$window.{left}"

    if set -q TMUX
        tmux switch-client -t "=$session"
    else
        tmux attach-session -t "=$session"
    end
end
