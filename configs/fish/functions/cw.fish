function cw --description "Claude Code with extra repo context (Vault + ghq repos)"
    set repos
    for arg in $argv
        set path (ghq list --full-path | grep $arg | head -1)
        if test -n "$path"
            set repos $repos "--add-dir" $path
        else
            echo "Warning: repo '$arg' not found in ghq" >&2
        end
    end
    claude $repos
end
