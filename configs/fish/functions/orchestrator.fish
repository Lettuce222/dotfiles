function orchestrator --description 'メインの agent を窓口として今のターミナルで開く'
    set -l provider (agent --which)
    or return
    set -l assets ~/.config/dotfiles-agent
    set -l name orchestrator
    set -l dir "$AGENT_ORCHESTRATOR_HOME"
    test -n "$dir"; or set dir "$HOME/hub"
    if not test -d "$dir"
        mkdir -p "$dir"; and chmod 700 "$dir"
        or return
    end

    set -l launch
    switch $provider
        case claude
            # worker とメッセージを送り合うので permission mode を auto で揃える。
            set launch claude -n $name --permission-mode auto /agents-orchestrator
        case codex
            set -l prompt (string collect < "$assets/codex-orchestrator.md")
            or return
            set launch codex $prompt
        case '*'
            set launch command $provider
    end

    # 呼んだシェルの環境とディレクトリを変えないよう、子の fish で起動する。環境は親から受け継ぎ、
    # 窓口のディレクトリの mise・direnv は agent-env.fish で取り込む（非対話の fish では conf.d が動かない）。
    set -l script cd (string escape -- "$dir")\;
    set -l env_file ~/.config/fish/agent-env.fish
    test -f "$env_file"; and set -a script source (string escape -- "$env_file")\;
    fish --no-config -c (string join ' ' -- $script (string escape -- $launch))
end
