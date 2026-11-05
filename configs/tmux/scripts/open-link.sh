#!/usr/bin/env bash
# tmux のマウスバインドから呼ばれ、ペイン内の OSC 8 ハイパーリンクを開く。
#   file:// のリンク → tmux display-popup の中で nvim で開く（ディレクトリも nvim で開く）
#   それ以外の URL   → OS の既定の opener（macOS: open, Linux: xdg-open）
#
# usage: open-link.sh <client-name> <url>
set -eu

client=$1
url=$2

message() {
  tmux display-message -c "$client" "$1"
}

# %XX を元のバイトに戻す。bash の printf %b は \xHH を解釈する。
percent_decode() {
  local s=${1//\\/\\\\}
  s=$(printf '%s' "$s" | sed -E 's/%([0-9A-Fa-f]{2})/\\x\1/g')
  printf '%b' "$s"
}

case $url in
  file://*)
    rest=${url#file://}
    # file://localhost/path と file://<自ホスト名>/path も受け付ける。
    case $rest in
      /*) ;;
      localhost/* | "$(hostname)"/* | "$(hostname -s)"/*) rest=/${rest#*/} ;;
      *)
        message "open-link: 別ホストの file URL は開けません: $url"
        exit 0
        ;;
    esac

    line=
    case $rest in
      *'#L'[0-9]*)
        line=${rest##*#L}
        line=${line%%[!0-9]*}
        ;;
    esac
    rest=${rest%%#*}
    rest=${rest%%\?*}
    path=$(percent_decode "$rest")

    if [ -d "$path" ]; then
      dir=$path
    elif [ -e "$path" ]; then
      dir=$(dirname -- "$path")
    else
      message "open-link: ファイルがありません: $path"
      exit 0
    fi

    set -- nvim
    [ -n "$line" ] && set -- "$@" "+$line"
    set -- "$@" -- "$path"
    tmux display-popup -c "$client" -E -w 90% -h 90% -d "$dir" \
      -T " $(basename -- "$path") " "$@"
    ;;
  *)
    if command -v open >/dev/null 2>&1 && [ "$(uname -s)" = Darwin ]; then
      open "$url"
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$url" >/dev/null 2>&1 &
    else
      message "open-link: URL を開くコマンドがありません: $url"
    fi
    ;;
esac
