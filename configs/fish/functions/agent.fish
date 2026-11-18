function agent --description 'このマシンのメインの coding agent CLI を起動する'
    set -l provider (sh "$HOME/.config/dotfiles-agent/select-cli.sh")
    or return
    if test (count $argv) -eq 1; and test "$argv[1]" = --which
        printf '%s\n' $provider
        return
    end

    if not command -q $provider
        printf 'agent: %s が PATH にありません。./install.sh で導入できます。\n' $provider >&2
        return 127
    end
    command $provider $argv
end
