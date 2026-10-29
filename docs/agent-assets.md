# AI agent assets

AI agentはClaude Codeだけを管理する。指示、skill、hookは`configs/agent/`を単一ソースにする。

Codexの設定は管理しない。`install.sh`は、以前`~/.codex/`へ置いたdotfiles向けsymlinkだけを削除する。

## 配置

- `configs/agent/AGENTS.md`
  - `~/.claude/CLAUDE.md`
- `configs/agent/skills/<name>/`
  - `~/.claude/skills/<name>`
- `configs/agent/hooks/*.sh`
  - `~/.claude/hooks/`

`settings.json`などClaude Code本体の設定ファイルは`configs/claude/`に置く。

## なぜ個別symlinkか

`~/.claude/skills/`には、pluginや別の方法で導入したskillが同居する。ディレクトリ全体をsymlinkせず、dotfiles管理対象だけを個別にlinkする。

`~/.claude/`のhistory、sessions、cacheなどの動的ファイルは管理しない。

## Hookの配線

hook scriptの配置（`configs/agent/hooks/`）と発火設定（`configs/claude/settings.json`）は分ける。

### textlint

`textlint-markdown.sh`はClaude Codeの`PostToolUse`（`Write|Edit`）で、書き込まれた`*.md`をtextlintにかける。指摘があればexit 2でagentへ返し、書き直させる。

- ルール設定とnpm依存: `configs/textlint/`（`~/.config/textlint`へsymlink）
- npm依存のinstall: `install.sh`の`install_textlint`（`npm ci`）
- 未installの機械ではhookは何もしない

`textlint-mcp.sh`はClaude Codeの`PreToolUse`（全MCP tool）で、tool inputのうち本文らしいkey（`body`、`description`、`comment`、`text`など）の日本語をtextlintにかける。指摘があればexit 2で送信を止める。特定のserviceやtool名には依存させない。コードが入る`content`は対象外にする。`AGENTS.md`の「まず.mdに下書きする」ルールを機械的に担保するためのhook。

## 窓口（hub）とworker

`configs/tmux/scripts/agent-hub/`に、tmux上でClaude Codeを窓口とworkerに分けて動かす仕組みを置く。

- `prefix + a`（`hub.fish`）: 窓口のClaude（セッション名`hub`）へ移動する。無ければ起動する。
- `prefix + A`（`pick.fish`）: 窓口とworkerのwindowを一覧から選んで移動する。
- `spawn.fish`: 窓口が呼ぶ。`<repo>.worktrees/<task>`にworktreeを作り、workerを別windowで起動する。
- `hub-rules.md`、`worker-rules.md`: それぞれの`--append-system-prompt-file`に渡す役割定義。

窓口とworkerはどちらもauto modeで起動する。報告と追加指示はClaude Codeのセッション間メッセージ（`SendMessage`）でやり取りする。permission modeが異なるセッションからのメッセージはユーザー承認待ちになるため、modeを揃える。workerの作るPRは必ずdraftにする。
