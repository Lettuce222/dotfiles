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
