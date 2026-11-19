# Hub (local)

Orca の右サイドバーに、このマシンの全部の Claude Code のセッション（`claude --bg` の worker、窓口などの対話のセッション、Orca のワークスペースのエージェント）を、ゴールと進み具合とともに出す plugin。今は見るだけで、セッションには何も送らない（段 1）。

## 出典

[andoshin11/orca-milestone](https://github.com/andoshin11/orca-milestone) の v0.9.0（コミット `637620c`、2026-11-13）を、同じリポジトリの `../milestone/`（Milestone (local)）を経て持ってきて手を入れたもの。著作権表示と許諾の文は同じフォルダの [LICENSE](LICENSE)（MIT、Copyright (c) 2026 andoshin11）にある。持ってきた各ファイルの先頭にも、元のファイルと除いた部分を書いた。

## 持ってきたもの

| ファイル | 元 | 手を入れたところ |
| --- | --- | --- |
| `main.mjs` | `main.mjs` | `next.send` の受け口を外し、`report.open` の受け口と `claude` の CLI を足した |
| `src/launch-hook.mjs` | `src/launch-hook.mjs` | Milestone (local) と同じ（タスクの指示と `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` だけ） |
| `src/claude-sessions.mjs` | `src/claude-sessions.mjs` | Milestone (local) と同じ |
| `src/orca-cli.mjs` | `src/orca-cli.mjs` | Milestone (local) と同じ |
| `src/hub-worker.mjs` | `src/milestone-worker.mjs` | `claude agents --json --all` とジョブの状態（`~/.claude/jobs/<id>/state.json`）を読み、全部のセッションを 1 つの一覧にする。hub の worker の `report.md` を開く |
| `src/hub-render.mjs` | `src/render.mjs` | 行とタスクの書き方を写し、「あなたの番」「動いている」「待っている」「済んだ」の節にした |
| `panel/` | `panel/` | `next.mjs` とカードのスタイルを外した。行から `report.md` を開けるようにした |
| `test/` | `test/` | 残したコードのテストを持ってきた。`main.test.mjs` は書き直し、`hub.test.mjs` を足した |

新しく書いたもの: `src/claude-agents.mjs`（`claude agents` とジョブの状態を読む）、`src/hub-model.mjs`（一覧の組み立て）。

## 持ってこなかったもの

- `src/permission-hook.mjs`、`src/turn-grant.mjs`、`src/dangerous.mjs`、`src/risk.mjs`: 許可をまとめて返す仕組み。許可は `~/.claude/settings.json` の hook とユーザーだけが決める。
- `src/next-actions.mjs`、`panel/next.mjs`、`src/restart.mjs`: `orca terminal send` でセッションに打ち込む仕組み。段 2 で、窓口と同じ安全の仕組みを通す形で作り直す予定。
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
