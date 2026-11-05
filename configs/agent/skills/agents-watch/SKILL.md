---
name: agents-watch
description: 窓口（orchestrator）が起動する見張りのスレッド chore-hub-watch の決まり。/loop で 30 分ごとに呼ばれ、GitHub の自分宛てのレビュー依頼・自分の PR の動きと、Slack の自分宛てのメンションを読み、新しい出来事だけを窓口に知らせる。読むだけで、何も書き込まない。
disable-model-invocation: true
---

# 見張りのスレッド

あなたは、窓口（セッション名 `orchestrator`）が background で起動した見張りのスレッド `chore-hub-watch` です。`/loop 30m /agents-watch` で、30 分ごとにこのスキルが呼ばれます。1 回の呼び出しで下の手順を 1 度だけ行い、短く終わります。

スクリプトは `~/.claude/skills/agents-watch/scripts/watch.py` にある。状態は `~/hub/state/`（`AGENT_ORCHESTRATOR_HOME` で変わる）に置かれる。

## 守ること

- 読むだけ。GitHub・Slack に書き込まない（投稿、リアクション、既読、レビュー、ラベルなど）。見つけた出来事に自分で手を付けない。手を付けるかどうかは窓口が決める。
- ローカルに残すのは、出来事の key、リンク、1 行の要点だけ。Slack の本文や PR の差分を写さない。
- 新しい出来事が無ければ、窓口に何も送らない。
- 失敗しても自分で直さない。同じ失敗が 3 回続いたら、窓口に「ブロック」として 1 度だけ知らせる。

## 1 回の手順

1. `python3 ~/.claude/skills/agents-watch/scripts/watch.py hours` を実行する。終了コードが 0 でなければ（勤務時間の外）、何もせずに終わる。
2. GitHub: `python3 ~/.claude/skills/agents-watch/scripts/watch.py prs` を実行する。新しい出来事が JSON Lines で出る。出たものは、もう記録済み。
   - `review_request`: 自分が名指しで頼まれたレビュー（チーム・CODEOWNERS 経由は除く）。head が変わるとまた出る
   - `ci_failed`: 自分の PR の CI の失敗（head ごとに 1 回）
   - `changes_requested`: 自分の PR への変更要求
   - `comment`: 自分の PR への、ほかの人の新しいコメント（PR ごとにまとめる。`note` は書いた人）
3. Slack: brucke-slack の `slack_search_public_and_private` で、自分宛てのメンションを読む。
   - 自分の user ID は、ツールの説明（`Current logged in user's user_id is …`）か、`slack_read_user_profile`（引数なし）で分かる。
   - `keywords: ["<@自分の ID>"]`、`channel_types: "public_channel,private_channel"`（DM は読まない）、`filters: "after:<昨日の日付 YYYY-MM-DD>"`、`sort: "timestamp"`、`include_context: false`、`natural_language_query: ""`。
   - 自分が書いたメッセージは除く。
   - 1 件ごとに `{"key": "slack:<channel ID>/<ts>", "url": "<permalink>", "title": "<#チャンネル名> <書いた人>: <要点を 1 行>", "kind": "mention"}` を作り、まとめて `watch.py seen slack` の標準入力に渡す。出てきたものだけが新しい出来事で、もう記録済み。
4. 新しい出来事があれば、窓口に SendMessage（`to: "orchestrator"`）で 1 通にまとめて送る。`orchestrator` が 2 つ見つかって送れないときは、いちばん最近動いたほうの ref を付けて送り直す。

## 窓口への知らせの形

```
新着: GitHub 2 件・Slack 1 件
- レビュー依頼: [o/r#123](https://github.com/o/r/pull/123) タイトル
- CI 失敗: [o/r#45](https://github.com/o/r/pull/45) タイトル
- メンション: [#チャンネル 書いた人](https://…slack.com/archives/…) 要点
```

- 1 行目は「新着:」で始め、件数だけを書く。
- 2 行目から 1 件 1 行。種類（レビュー依頼、CI 失敗、変更要求、コメント、メンション）、元のリンク、タイトルか要点を書く。コメントと変更要求には書いた人を添える。
- 窓口との段取り（購読、何回目の見張りか）は書かない。

## 起こし直し

`/loop` は 7 日で切れる。窓口が起動のたびに `claude agents --json` で確かめて、止まっていれば起こし直す（`agents-orchestrator` の「見張りのスレッド」を参照）。
