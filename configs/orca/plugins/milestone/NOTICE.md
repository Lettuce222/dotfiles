# Milestone (local)

Orca の右サイドバーに、フォーカス中のワークスペースで Claude Code が進めているタスクを、ゴールとマイルストーンとして出す plugin。見るだけで、セッションには何も送らない。

## 出典

[andoshin11/orca-milestone](https://github.com/andoshin11/orca-milestone) の v0.9.0（コミット `637620c`、2026-11-13）から、表示に要る部分だけを持ってきて手を入れたもの。著作権表示と許諾の文は同じフォルダの [LICENSE](LICENSE)（MIT、Copyright (c) 2026 andoshin11）にある。持ってきた各ファイルの先頭にも、元のファイルと除いた部分を書いた。

## 持ってきたもの

| ファイル | 元 | 手を入れたところ |
| --- | --- | --- |
| `main.mjs` | `main.mjs` | `next.send` の受け口を外した |
| `src/launch-hook.mjs` | `src/launch-hook.mjs` | Claude Code に `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` とタスクの指示だけを足す。`next` のブロックの指示、`--settings` の PermissionRequest フック、Codex の MCP を外した |
| `src/claude-sessions.mjs` | `src/claude-sessions.mjs` | 未回答の AskUserQuestion・許可待ちの呼び出しを読む関数を外した |
| `src/orca-cli.mjs` | `src/orca-cli.mjs` | カードの元（`offersOf`）を外した。CLI には `worktree ps` と `terminal list` だけを頼む。Orca 1.4.262 では worker が `Orca Helper.app` の中で動くので、CLI を上のアプリのバンドルからも探すようにした |
| `src/model.mjs`、`src/render.mjs` | 同名 | カード（次の作業、質問、許可）を外した |
| `src/milestone-worker.mjs` | 同名 | Codex の進捗、カード、端末への送信、「このターンの残りも許可」、再開を外した |
| `panel/` | `panel/` | `next.mjs` とカードのスタイルを外した |
| `test/` | `test/` | 残したコードのテストを持ってきた。`main.test.mjs` は書き直し、見るだけであることを確かめるテストを足した |

## 持ってこなかったもの

- `src/permission-hook.mjs`、`src/turn-grant.mjs`、`src/dangerous.mjs`、`src/risk.mjs`: 許可をまとめて返す仕組み。許可は `~/.claude/settings.json` のフックとユーザーだけが決める。
- `src/next-actions.mjs`、`panel/next.mjs`、`src/restart.mjs`: `orca terminal send` でセッションに打ち込む仕組み。
- `src/progress-server.mjs`、`src/codex-progress.mjs`: Codex 用。
- iPhone・Apple Watch の連携（[agent-status-panel](https://github.com/andoshin11/agent-status-panel)）は元から別のリポジトリで、使わない。

## 使い方

Orca 1.4.248 以上で、開発フォルダーとして読み込む。カタログやインストールは使わないので、自動更新は無い。中身を変えたら `orca plugin dev reload` で読み直す。

```sh
orca plugin dev load ~/.config/orca/plugins/milestone --approve <fingerprint>
orca plugin dev unload ~/.config/orca/plugins/milestone
```

テストは Node 24 以上で `node --test test/` を実行する。依存は無い。
