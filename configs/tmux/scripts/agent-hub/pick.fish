#!/usr/bin/env fish

# hub と worker の window を一覧し、選んだ window へ移動する（tmux popup から呼ぶ）

set -l rows
for line in (tmux list-windows -a -F '#{window_id}	#{@agent-hub}	#{@agent-hub-worker}	#{window_name}	#{pane_current_path}')
    set -l f (string split \t -- $line)
    if test "$f[2]" = 1; or test -n "$f[3]"
        set -a rows (string join \t -- $f[1] $f[4] (string replace -r -- '^'(string escape --style=regex -- $HOME)'(?=/|$)' '~' $f[5]))
    end
end

if test (count $rows) -eq 0
    echo "hub も worker も見つかりません"
    sleep 1
    exit 0
end

set -l picked (printf '%s\n' $rows | fzf --delimiter \t --with-nth 2.. --reverse --prompt 'agent> ')
or exit 0
tmux switch-client -t (string split \t -- $picked)[1]
