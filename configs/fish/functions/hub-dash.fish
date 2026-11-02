function hub-dash --description 'hub の状況と資料を見るローカルの web ダッシュボードを起動してブラウザで開く'
    # すでに起動していればブラウザで開くだけにする。止めるときは Ctrl-C
    # ポートは AGENT_HUB_DASH_PORT（既定 8765）、ほかの引数は dash.py に渡す（--interval など）
    python3 ~/.config/tmux/scripts/agent-hub/dash.py --open $argv
end
