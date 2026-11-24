#!/bin/sh
# Makes a GTD folder of sample items, through gtd.py, to try lazygtd without the real hub:
#   scripts/demo-home.sh /tmp/lazygtd-demo && lazygtd --gtd-home /tmp/lazygtd-demo
# The folder must not exist yet (the script never writes into a folder it did not make).
set -eu
dir=${1:?usage: demo-home.sh <new folder>}
gtd=${LAZYGTD_GTD_PY:-$HOME/.claude/skills/agents-orchestrator/scripts/gtd.py}
if [ -e "$dir" ]; then
  echo "demo-home.sh: $dir already exists" >&2
  exit 1
fi
export GTD_HOME="$dir"
run() { python3 "$gtd" "$@" >/dev/null; }
id() { python3 "$gtd" "$@" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

run init
run add --title='名刺の整理' --list inbox --source 'メモ'
run add --title='会議の議題を 3 つ集める' --list inbox
body='## 背景

- 指標は **5 つ**。`gtd.py json` で数える
- 表:

| 指標 | 今 | 目標 |
| --- | --- | --- |
| リードタイム | 3 日 | 1 日 |
| 変更の失敗率 | 12% | 5% |

```sh
python3 gtd.py json | jq .counts
```

> 引用: 小さく始める'
a=$(id add --title='計測の仕組みを下書きする' --list next --actor me --due 2026-11-25 --body "$body")
b=$(id add --title='サンプルデータを 1 か所にまとめる' --list next --actor agent --worker research-sample)
mkdir -p "$dir/items/$b"
printf '# README\n\n手順\n' >"$dir/items/$b/README.md"
printf '# report\n\n結果\n' >"$dir/items/$b/report.md"
p=$(id add --title='計測を始める' --list project --outcome '5 つの指標が毎週見える' --short 計測)
s1=$(id add --title='指標を決める' --list done)
s2=$(id add --title='データの置き場所を決める' --list next --project "$p")
s3=$(id add --title='ダッシュボードを作る' --list planned --project "$p")
run set "$p" "steps+=$s1" "steps+=$s2" "steps+=$s3"
run add --title='レビューの返事' --list waiting --who 'レビューする人' --follow-up 2026-11-20 --then '返事が来たら直す'
run add --title='本を読む' --list someday
run add --title='手順書のリンク集' --list reference --link https://example.com/docs
h=$(id add --title='下書きを確かめてほしい' --list next --actor agent --worker draft-x)
run handback "$h" '下書きを読んで、送ってよいか返事をください'
r=$(id add --title='設定の置き場所を決める' --list next --actor me)
run say "$r" --text='configs/x に置く案でよいですか'
printf '#### 案\n\n- configs/x に置く\n' | python3 "$gtd" reply "$r" --body-file - >/dev/null
run record --by user >/dev/null 2>&1 || true
echo "$dir"
