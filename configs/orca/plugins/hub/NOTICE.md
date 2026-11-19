# Hub (local)

Orca の右サイドバーに、開いているワークスペースのゴールとタスク（orca-milestone と同じ見た目）と、このマシンの全部の Claude Code のセッション（`claude --bg` の worker、窓口などの対話のセッション、Orca のワークスペースのエージェント）の一覧を出す plugin。開いているワークスペースのエージェントには、orca-milestone と同じカード（次の作業・質問・許可）で答えられる。worker には、行の ✎ から指示を送れる（`claude --bg --resume`）。

## 出典

[andoshin11/orca-milestone](https://github.com/andoshin11/orca-milestone) の v0.9.0（コミット `637620c`、2026-11-13）を、同じリポジトリの `../milestone/`（Milestone (local)）を経て持ってきて手を入れたもの。著作権表示と許諾の文は同じフォルダの [LICENSE](LICENSE)（MIT、Copyright (c) 2026 andoshin11）にある。持ってきた各ファイルの先頭にも、元のファイルと除いた部分を書いた。

## 持ってきたもの

| ファイル | 元 | 手を入れたところ |
| --- | --- | --- |
| `main.mjs` | `main.mjs` | `report.open`・`ask.answer`・`session.send` の受け口と `claude` の CLI を足した |
| `src/launch-hook.mjs` | `src/launch-hook.mjs` | タスクの指示と `next` のブロックの指示（「電話のボタン」を「サイドバーのボタン」に直した）。Codex の MCP は外した |
| `src/claude-sessions.mjs` | `src/claude-sessions.mjs` | そのまま |
| `src/orca-cli.mjs` | `src/orca-cli.mjs` | CLI の場所の探し方を Orca 1.4.262 の Helper に合わせた |
| `src/next-actions.mjs` | `src/next-actions.mjs` | 「このターンの残りも許可」、再開のカード、Codex の許可のメニューを外した。外に出る呼び出し（gh の書き込み、MCP の書き込み）には「許可」のカードを出さない。preview の付いた質問（窓口の承認の問い）にはカードを出さない |
| `src/risk.mjs`・`src/dangerous.mjs` | 同じ名前 | そのまま |
| `panel/next.mjs` | `panel/next.mjs` | そのまま |
| `src/hub-worker.mjs` | `src/milestone-worker.mjs` | `claude agents --json --all` とジョブの状態（`~/.claude/jobs/<id>/state.json`）を読み、全部のセッションを 1 つの一覧にする。hub の worker の `report.md` を開く |
| `src/hub-render.mjs` | `src/render.mjs` | 開いているワークスペースとカードはそのまま、ほかは「あなたの番」「動いている」「待っている」「済んだ」の節にした |
| `src/hub-model.mjs` | `src/model.mjs` | 開いているワークスペースの組み立てを写し、全部のセッションの一覧を足した |
| `panel/` | `panel/` | 行から `report.md` を開けるようにし、worker のカードと指示の入力欄（`act.mjs`）を足した。中身を `#view` に描くようにした |
| `test/` | `test/` | 残したコードのテストを持ってきた（jsdom に頼るものは除いた）。`main.test.mjs` は書き直し、`hub.test.mjs` を足した |

新しく書いたもの: `src/claude-agents.mjs`（`claude agents` とジョブの状態を読む）、`src/asks.mjs`（worker が `asks.py` で書く依頼を読む）、`src/deliver.mjs`（worker に `claude --bg --resume` で文を届ける）、`panel/act.mjs`。

## 持ってこなかったもの

- `src/permission-hook.mjs`、`src/turn-grant.mjs`: 「このターンの残りも許可」。PermissionRequest の hook で許可を返すので、hook が確認を求めた呼び出し（外に出す文面など）を、人が読まずに通してしまう。許可のカードは、ターミナルの確認のメニューに 1 か Esc を送るものだけにした（人がそのメニューで押すのと同じ）。
- `src/restart.mjs`: 古い指示のセッションを起動し直すカード。要らない。
- `src/progress-server.mjs`、`src/codex-progress.mjs`: Codex 用。
- iPhone・Apple Watch の連携（[agent-status-panel](https://github.com/andoshin11/agent-status-panel)）は元から別のリポジトリで、使わない。

## 使い方

Orca 1.4.248 以上で、フォルダーからインストールする。開発フォルダー（`orca plugin dev load`）にはしない。開発フォルダーのプラグインは `orca plugin dev request` で外からパネルの受け口を呼べるため。

```sh
orca plugin install ~/.config/orca/plugins/hub --approve <fingerprint>
orca plugin update lettuce222.hub-local --approve <fingerprint>   # フォルダーを写し直す
orca plugin uninstall lettuce222.hub-local
```

テストは Node 24 以上で `node --test test/` を実行する。依存は無い。
