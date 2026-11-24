#!/bin/sh
# Makes a GTD folder of sample items, through gtd.py, to try lazygtd without the real hub:
#   scripts/demo-home.sh /tmp/lazygtd-demo && lazygtd --gtd-home /tmp/lazygtd-demo
# About as many items and kinds as a working week has: projects with steps, waiting with who,
# follow-up and watch, due dates near and past, agents and the user, answers of the orchestrator
# unread and replies waiting, long titles and long Markdown. Everything is made up: the people,
# the teams and the links (example.com).
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
# The date n days from today.
day() { python3 -c "import datetime; print(datetime.date.today() + datetime.timedelta(days=$1))"; }
answer() { printf '%s\n' "$2" | python3 "$gtd" reply "$1" --body-file - >/dev/null; }
step() { python3 "$gtd" step add "$1" --title="$2" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

run init

# ---------------------------------------------------------------- inbox
run add --title='名刺の整理' --source 'メモ'
run add --title='会議の議題を 3 つ集める' --source 'Slack'
run add --title='新しいノート PC の初期設定を済ませる' --source 'メモ'
run add --title='勉強会の資料を読む（第 4 回: テストの書き方）' --source 'メール'
run add --title='経費の精算（11 月分のタクシー 2 件）'
run add --title='チームの振り返りで出た「レビューの待ち時間が長い」をどう扱うか考える。ほかのチームのやり方も聞いてみる' --source '振り返り'
run add --title='ライブラリの更新のお知らせを読む' --source 'メール'
run add --title='来期の目標の下書きに手を付ける'

# ---------------------------------------------------------------- next (me)
long='## 背景

月に一度、**開発の流れ**を数字で見る。いまは手で集めていて、1 回に半日かかる。

- 指標は 5 つ。`gtd.py json` のように、機械で読める形で出す
- 集める先は 3 か所（リポジトリ・チケット・リリースの記録）
- 詳しくは [指標の定義](https://example.com/metrics) と [前回のまとめ](https://example.com/review-10)

## 指標

| 指標 | 今 | 目標 | 集め方 |
| --- | --- | --- | --- |
| リードタイム | 3 日 | 1 日 | マージまでの時間の中央値 |
| デプロイの回数 | 週 4 回 | 毎日 | リリースの記録 |
| 変更の失敗率 | 12% | 5% | 戻したリリースの割合 |
| 戻すまでの時間 | 6 時間 | 1 時間 | 障害の記録 |
| レビューの待ち | 20 時間 | 4 時間 | 最初のレビューまで |

## 手順の案

1. 集める処理を 1 本にまとめる
2. 週に 1 回、自動で動かす
3. 結果をダッシュボードに出す

```sh
python3 collect.py --since 2026-10-01 --until 2026-10-31 \
  --out metrics.json
jq ".lead_time.median" metrics.json
```

> 小さく始めて、毎週見る。完ぺきな数字より、続く仕組みを先に作る。

### 気になること

- 祝日をどう扱うか（営業日で数えるか）
- リポジトリごとに分けるか、まとめるか'
run add --title='計測の仕組みを下書きする' --list next --actor me --due "$(day 1)" --body "$long"
run add --title='1on1 のメモをまとめる' --list next --actor me --due "$(day 0)"
run add --title='採用の書類を 2 件読む' --list next --actor me --due "$(day -2)"
run add --title='発表のスライドの最後の 3 枚を直す' --list next --actor me --due "$(day 3)"
run add --title='ドキュメントの古いリンクを直す' --list next --actor me
run add --title='新しく入った人のための手順書を見直し、足りないところ（権限の申請、開発環境、最初の 1 週間の進め方）を書き足す' --list next --actor me --due "$(day 6)"
run add --title='予算の見積もりに返事をする' --list next --actor me --due "$(day -1)"

# ---------------------------------------------------------------- next (agents)
a1=$(id add --title='サンプルデータを 1 か所にまとめる' --list next --actor agent --worker research-sample)
mkdir -p "$dir/items/$a1"
printf '# README\n\n手順\n' >"$dir/items/$a1/README.md"
printf '# report\n\n結果\n' >"$dir/items/$a1/report.md"
printf '# notes\n\nメモ\n' >"$dir/items/$a1/notes.md"
run add --title='テストの遅いものを 10 件洗い出す' --list next --actor agent --worker chore-slow-tests
run add --title='依存ライブラリを最新に上げる PR を作る' --list next --actor agent --worker impl-deps-bump --due "$(day 2)"
run add --title='エラーの多い画面を調べる' --list next --actor agent
run add --title='週報の下書きを作る' --list next --actor agent --worker draft-weekly --due "$(day 0)"

# ---------------------------------------------------------------- あなたの番 (handback)
h1=$(id add --title='下書きを確かめてほしい: お知らせのメール' --list next --actor agent --worker draft-notice)
run handback "$h1" '下書きを読んで、送ってよいか返事をください'
h2=$(id add --title='設計の案を 2 つから選んでほしい' --list next --actor agent --worker design-cache)
run handback "$h2" '案 A（作り直す）と案 B（今のものを直す）のどちらで進めるか、返事をください'
h3=$(id add --title='PR のレビューの指摘への返事を確かめる' --list next --actor agent --worker review-reply)
run handback "$h3" '返事の文面を読んで、直すところがあれば返事に書いてください'

# ---------------------------------------------------------------- 窓口 (talk)
t1=$(id add --title='設定の置き場所を決める' --list next --actor me)
run say "$t1" --text='configs/x に置く案でよいですか'
answer "$t1" '#### 案

- `configs/x` に置く。ほかの設定と同じ場所なので探しやすい
- 移すときは [手順](https://example.com/move) のとおりに'
t2=$(id add --title='来週の予定の組み方' --list next --actor me)
run say "$t2" --text='火曜と木曜の午後をまとめて空けたい'
answer "$t2" '火曜の午後は空けられます。木曜は定例があるので、15 時からなら空きます。'
t3=$(id add --title='勉強会の担当を決める' --list next --actor me)
run say "$t3" --text='12 月の担当を誰にするか、候補を出してほしい'
t4=$(id add --title='古いブランチを消してよいか' --list next --actor me)
run say "$t4" --text='3 か月動いていないブランチを消してよいか確かめたい'

# ---------------------------------------------------------------- projects and steps
p1=$(id add --title='計測を始める' --list project --outcome '5 つの指標が毎週見える' --short 計測)
s=$(step "$p1" '指標を決める'); run done "$s"
s=$(step "$p1" 'データの置き場所を決める'); run done "$s"
step "$p1" '集める処理を書く' >/dev/null
step "$p1" 'ダッシュボードを作る' >/dev/null
step "$p1" 'チームに見せて直す' >/dev/null

p2=$(id add --title='手順書を新しくする' --list project --outcome '新しく入った人が 1 日で開発を始められる' --short 手順書)
step "$p2" '今の手順書の古いところを洗い出す' >/dev/null
step "$p2" '書き直す' >/dev/null
step "$p2" '新しく入った人に試してもらう' >/dev/null

p3=$(id add --title='リリースを毎日にする' --list project --outcome 'リリースの手作業が無くなり、毎日出せる' --short リリース)
s=$(step "$p3" 'リリースの手順を書き出す'); run done "$s"
step "$p3" '手作業の部分を自動にする' >/dev/null
step "$p3" '戻す手順を試す' >/dev/null
step "$p3" '毎日のリリースを 2 週間続ける' >/dev/null

p4=$(id add --title='勉強会を立ち上げる' --list project --outcome '月に 1 回、チームの外の人も来る勉強会が続く' --short 勉強会)
step "$p4" '題目の案を集める' >/dev/null
step "$p4" '最初の回の日を決める' >/dev/null

# ---------------------------------------------------------------- waiting
run add --title='レビューの返事' --list waiting --who 'レビューする人' --follow-up "$(day -3)" --then '返事が来たら直す' --watch https://example.com/pull/101
run add --title='権限の申請' --list waiting --who '情報システムの窓口' --follow-up "$(day 2)" --then '通ったら手順書を直す'
run add --title='見積もりの回答' --list waiting --who '架空の取引先' --follow-up "$(day 5)" --then '金額を予算の表に入れる'
run add --title='デザインの確認' --list waiting --who 'デザインのチーム' --follow-up "$(day 0)" --watch https://example.com/pull/202 --watch https://example.com/pull/203
run add --title='ライブラリの不具合の報告への返事' --list waiting --who 'OSS のメンテナー' --follow-up "$(day 14)" --watch https://example.com/issues/77
run add --title='会議室の予約の返事' --list waiting --who '総務' --follow-up "$(day 1)"

# ---------------------------------------------------------------- someday
run add --title='本を読む: 『チームの仕事の進め方』' --list someday
run add --title='キーボードを新しくする' --list someday
run add --title='自分用のメモの仕組みを見直す' --list someday
run add --title='社外の勉強会で話す' --list someday
run add --title='ターミナルの設定を整理する' --list someday
run add --title='古い写真を整理する' --list someday
run add --title='英語の練習を週 1 回にする' --list someday

# ---------------------------------------------------------------- reference
ref='## よく使うリンク

- [開発の手順](https://example.com/dev)
- [リリースの手順](https://example.com/release)
- [障害のときの連絡先](https://example.com/oncall)

| 種類 | 置き場所 |
| --- | --- |
| 設計の記録 | `docs/decisions/` |
| 手順 | `docs/howto/` |'
run add --title='手順書のリンク集' --list reference --link https://example.com/docs --body "$ref"
run add --title='チームの決めごと' --list reference --link https://example.com/rules
run add --title='よく使うコマンドのメモ' --list reference --body '```sh
git log --oneline -20
go test ./...
```'
run add --title='年間の予定' --list reference
run add --title='用語集' --list reference --link https://example.com/glossary

# ---------------------------------------------------------------- done
for t in '先週の週報を出す' '机の上を片付ける' 'パスワードを変える' '定例の議事録を出す' '発表の練習をする' 'PR を 3 件レビューする'; do
  i=$(id add --title="$t" --list next --actor me)
  run done "$i"
done

# ---------------------------------------------------------------- ages
# Items came on different days: the n-th item of a list came n*3 days ago, at most 70.
python3 "$gtd" json | python3 -c '
import json, sys
items = json.load(sys.stdin)["items"]
seen = {}
for it in items:
    n = seen.get(it["list"], 0)
    seen[it["list"]] = n + 1
    print(it["id"], min(n * 3, 70))
' | while read -r i n; do
  run set "$i" "since=$(day "-$n")"
done

run record --by user >/dev/null 2>&1 || true
echo "$dir"
