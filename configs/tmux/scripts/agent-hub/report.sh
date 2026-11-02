#!/bin/sh
# worker の報告を、ダッシュボードの受信箱が読むファイルに追記する
# Usage: sh report.sh <セッション名> <完了|要判断|ブロック>   （本文は標準入力から読む）
# 書き込み先: ${XDG_STATE_HOME:-~/.local/state}/agent-hub/reports/<セッション名>.md
set -eu

usage() {
    echo "usage: report.sh <セッション名> <完了|要判断|ブロック>  （本文は標準入力）" >&2
    exit 2
}

[ $# -eq 2 ] || usage
name=$1
kind=$2
case $name in
'' | .* | *[!A-Za-z0-9._-]*)
    echo "report: セッション名に使えない文字があります: $name" >&2
    exit 2
    ;;
esac
case $kind in
完了 | 要判断 | ブロック) ;;
*) usage ;;
esac

body=$(cat)
if [ -z "$body" ]; then
    echo "report: 本文が空です" >&2
    exit 2
fi

# 報告には議事録由来の文脈が入りうるので、自分だけが読めるようにする
umask 077
dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-hub/reports"
mkdir -p "$dir"
chmod 700 "$dir"
file="$dir/$name.md"

# 見出しの時刻が報告の ID になるので、同じ秒に重ねない
ts=$(date '+%Y-%m-%d %H:%M:%S')
while [ -f "$file" ] && grep -q "^## $ts " "$file"; do
    sleep 1
    ts=$(date '+%Y-%m-%d %H:%M:%S')
done

# 本文の行頭の ## は見出しと取り違えないよう、字下げしておく
{
    printf '\n## %s %s\n\n' "$ts" "$kind"
    printf '%s\n' "$body" | sed 's/^##/ ##/'
} >>"$file"
chmod 600 "$file"
echo "$file"
