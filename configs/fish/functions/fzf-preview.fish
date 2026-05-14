function fzf-preview
    set -l description "fzf search files with preview"

    # batコマンドの存在確認
    if not command -v bat > /dev/null
        echo "Error: 'bat' command is not installed." >&2
        echo "Please install bat: brew install bat" >&2
        return 1
    end

    # 実行したディレクトリを記録
    set -l target_dir (pwd)

    # batを使用してプレビュー表示
    set -l preview_cmd 'bat --style=numbers --color=always --line-range :500 {}'

    # fzfでファイル検索＋プレビュー
    # stdinがパイプかターミナルかを判定してfzfの動作を調整
    set -l selected_file
    if isatty stdin
        # 通常の実行（ターミナルから直接実行）
        set selected_file (fd -t f --hidden --exclude .git | \
            fzf --preview $preview_cmd \
                --preview-window=right:60%:wrap \
                --height=80% \
                --border \
                --prompt="File > " \
                --header="Press ENTER to select, ESC to cancel" \
                --bind 'ctrl-u:preview-page-up' \
                --bind 'ctrl-d:preview-page-down' \
                --bind 'ctrl-/:change-preview-window(down|hidden|)' \
                --ansi)
    else
        # パイプ経由で実行される場合（例: fzf-preview | emacs）
        # ターミナルを直接開いてfzfを実行
        set selected_file (find $target_dir -type f -not -path '*/.git/*' -not -path '*/.git' | \
            fzf --preview $preview_cmd \
                --preview-window=right:60%:wrap \
                --height=80% \
                --border \
                --prompt="File > " \
                --header="Press ENTER to select, ESC to cancel" \
                --bind 'ctrl-u:preview-page-up' \
                --bind 'ctrl-d:preview-page-down' \
                --bind 'ctrl-/:change-preview-window(down|hidden|)' \
                --ansi < /dev/tty > /dev/tty 2>&1)
    end

    # ファイルが選択された場合、そのパスを標準出力に出力（パイプで次のコマンドに渡される）
    if test -n "$selected_file"
        echo $selected_file
    end
end
