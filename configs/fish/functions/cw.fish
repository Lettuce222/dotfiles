function cw --description 'ghq から作業ディレクトリを追加してメインの agent を起動する'
    if test (count $argv) -eq 0
        agent
        return
    end
    set -l provider (agent --which)
    or return
    if not contains -- $provider claude codex
        printf 'cw: %s の追加ディレクトリ用オプションは未設定です。対象リポジトリで agent を起動してください。\n' $provider >&2
        return 2
    end
    set -l repos
    for arg in $argv
        set -l repo (ghq list --full-path | grep -F -- "$arg" | head -n 1)
        if test -n "$repo"
            set -a repos --add-dir "$repo"
        else
            echo "Warning: repo '$arg' not found in ghq" >&2
        end
    end
    agent $repos
end
