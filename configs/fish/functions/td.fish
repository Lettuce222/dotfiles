function td --description 'Create tmux session with current directory name and switch to it'
    set -l session_name (basename (pwd) | string replace -a '.' '_')

    if set -q TMUX
        if tmux has-session -t $session_name 2>/dev/null
            tmux switch-client -t $session_name
        else
            tmux new-session -d -s $session_name -c (pwd)
            tmux switch-client -t $session_name
        end
    else
        if tmux has-session -t $session_name 2>/dev/null
            tmux attach-session -t $session_name
        else
            tmux new-session -s $session_name -c (pwd)
        end
    end
end
