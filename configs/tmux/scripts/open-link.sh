#!/usr/bin/env bash
# tmux のマウスバインドから呼ばれ、ペイン内の OSC 8 ハイパーリンクを開く。
#   file:// の Markdown（.md）        → tmux display-popup の中で leaf で開く（leaf が無ければ nvim）
#   file:// のテキスト               → tmux display-popup の中で nvim で開く
#   file:// のディレクトリ           → OS の既定の opener（macOS なら Finder）
#   file:// のテキストでないファイル  → OS の既定の opener（画像ならプレビューなど）
#   それ以外の URL                    → OS の既定の opener（macOS: open, Linux: xdg-open）
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

# OS の既定の opener に渡す（macOS: open, Linux: xdg-open）。
system_open() {
  if [ "$(uname -s)" = Darwin ]; then
    open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 &
  else
    message "open-link: 開くコマンドがありません: $1"
  fi
}

# コマンドの絶対パスを出す。見つからなければ偽。
# このスクリプトは tmux の run-shell から、tmux サーバーが起動したときの PATH で動く。
# mise activate は PATH にツールごとの install のフォルダを足す作りなので、tmux サーバーより
# あとに mise で入れたツールはその PATH に無い。PATH に無ければ mise に聞く（グローバルの設定を
# 読むよう $HOME で聞く）。popup も tmux サーバーの環境で動くので、見つけた絶対パスで起動する。
find_tool() {
  local mise
  command -v "$1" 2>/dev/null && return 0
  mise=$(command -v mise 2>/dev/null || echo "$HOME/.local/bin/mise")
  [ -x "$mise" ] || return 1
  "$mise" -C "$HOME" which "$1" 2>/dev/null
}

# file(1) が binary と判定したら真。file がなければテキスト扱い。
is_binary() {
  command -v file >/dev/null 2>&1 || return 1
  [ "$(file -b --mime-encoding -- "$1")" = binary ]
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
      # フォルダは Finder（Linux ならファイルマネージャ）で開く。画像をドラッグして使えるように。
      system_open "$path"
      exit 0
    elif [ -e "$path" ]; then
      # 画像や PDF などテキストでないファイルは既定のアプリ（プレビューなど）で開く。
      if [ -s "$path" ] && is_binary "$path"; then
        system_open "$path"
        exit 0
      fi
      dir=$(dirname -- "$path")
    else
      message "open-link: ファイルがありません: $path"
      exit 0
    fi

    leaf=
    case $path in
      # leaf が入っていないマシンでは nvim で開く。
      *.md | *.markdown) leaf=$(find_tool leaf) || leaf= ;;
    esac

    if [ -n "$leaf" ]; then
      # leaf は行を指定して開けないので #L は使わない。--watch で書き換えに追従する。
      set -- "$leaf" --watch -- "$path"
    else
      nvim=$(find_tool nvim) || nvim=nvim
      set -- "$nvim"
      [ -n "$line" ] && set -- "$@" "+$line"
      set -- "$@" -- "$path"
    fi
    tmux display-popup -c "$client" -E -w 90% -h 90% -d "$dir" \
      -T " $(basename -- "$path") " "$@"
    ;;
  *)
    system_open "$url"
    ;;
esac
