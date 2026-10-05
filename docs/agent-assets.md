# AI agent assets

Claude CodeとCodexで共有できる資産は`configs/agent/`を単一ソースにする。

## 配置

- `configs/agent/AGENTS.md`
  - `~/.claude/CLAUDE.md`
  - `~/.codex/AGENTS.md`
- `configs/agent/skills/<name>/`
  - `~/.claude/skills/<name>`
  - `~/.codex/skills/<name>`
- `configs/agent/hooks/*.sh`
  - 各runtimeの`hooks/`

Claude Code固有ファイルは`configs/claude/`に置く。Codexの`config.toml`はproxy、project trust、業務固有設定を含むため管理しない。

## なぜ個別symlinkか

`~/.claude/skills/`と`~/.codex/skills/`には、system skillや別の方法で導入したskillが同居する。ディレクトリ全体をsymlinkせず、dotfiles管理対象だけを個別にlinkする。

`~/.claude/`と`~/.codex/`のhistory、sessions、cacheなどの動的ファイルは管理しない。

## Hookの配線

共有hook scriptの配置と発火設定は分ける。

- Claude Code: `configs/claude/settings.json`
- Codex: 管理対象外の`~/.codex/config.toml`

### textlint

`textlint-markdown.sh`はClaude Codeの`PostToolUse`（`Write|Edit`）で、書き込まれた`*.md`をtextlintにかける。指摘があればexit 2でagentへ返し、書き直させる。

- ルール設定とnpm依存: `configs/textlint/`（`~/.config/textlint`へsymlink）
- npm依存のinstall: `install.sh`の`install_textlint`（`npm ci`）
- 未installの機械ではhookは何もしない

`textlint-mcp.sh`はClaude Codeの`PreToolUse`（全MCP tool）で、tool inputのうち本文らしいkey（`body`、`description`、`comment`、`text`など）の日本語をtextlintにかける。指摘があればexit 2で送信を止める。特定のserviceやtool名には依存させない。コードが入る`content`は対象外にする。`AGENTS.md`の「まず.mdに下書きする」ルールを機械的に担保するためのhook。
