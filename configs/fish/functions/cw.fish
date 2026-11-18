function cw --description 'ghq から作業ディレクトリを追加してメインの agent を起動する'
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
