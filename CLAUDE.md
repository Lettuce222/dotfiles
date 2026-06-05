# dotfiles

macOS（仕事）と Ubuntu（プライベート）両方で使う個人用 dotfiles。`install.sh` が `configs/*` を `$HOME` 以下にシンボリックリンクで配置する。

## 設定を編集するときのルール

**必ず `configs/` 配下のソースを編集する。`~/.config/` 以下は symlink なので、そこを編集しても git で追跡されない。**

- ✅ `configs/{app}/...`
- ❌ `~/.config/{app}/...`

AI コーディングエージェントの設定は例外で、ディレクトリ丸ごとではなく**個別ファイル/個別ディレクトリ単位**で symlink される。`~/.claude/` 内・`~/.codex/` 内の動的ファイル（history, sessions など）は管理対象外。

### AI エージェント設定の構成（Claude Code / Codex 共有）

- **`configs/agent/`** … Claude Code と Codex で**共有**する資産。ツール非依存なのでここを単一ソースにする。
  - `AGENTS.md` … グローバル指示。`~/.claude/CLAUDE.md` と `~/.codex/AGENTS.md` の**両方**がここを指す（Claude は `CLAUDE.md`、Codex は `AGENTS.md` という名前で読むだけで中身は同一）。
  - `skills/<name>/` … skill。`~/.claude/skills/<name>` と `~/.codex/skills/<name>` の両方に個別 symlink。SKILL.md 形式は両ツール共通。
  - `hooks/*.sh` … 共有 hook スクリプト。両ツールの `hooks/` に配置。ただし**発火の配線**は別（Claude は `configs/claude/settings.json`、Codex は `~/.codex/config.toml`＝業務固有のため管理対象外）。
- **`configs/claude/`** … Claude Code 固有のファイルのみ（`settings.json`, `settings.local.json`, `statusline.sh`, `file-suggestion.sh`）。
- **`~/.codex/config.toml`** … flugel プロキシや project trust など業務/マシン固有のため symlink せず管理対象外。

skill を個別 symlink するのは、`~/.claude/skills/` や `~/.codex/skills/`（`.system` 含む）に dotfiles 管理外の skill が同居しているため。ディレクトリ丸ごと symlink するとそれらを壊す。

## Multi-OS 対応

macOS と Ubuntu の両方で動く必要があるため、OS 固有の処理は `install.sh` 内で分岐させる:
- Homebrew / cask / `defaults write` は macOS 専用
- apt 系・Linux 固有処理は Ubuntu 専用
- 共通化できるもの（symlink、mise）は共通ロジックに寄せる

OS を限定する変更を入れるときは、もう片方の OS で壊れないか確認する。

## Per-machine 設定（git 管理外）

機械固有の値はコミットせず、以下のパターンに分離する:
- Fish: `configs/fish/conf.d/*.local.fish`、`configs/fish/functions/local/*`
- 新しいアプリで同様の分離が必要になったら `.gitignore` を更新する

## 新しいアプリ設定を追加するとき

1. `configs/{app}/` に設定を置く
2. `install.sh` の symlink ループが拾うことを確認（`claude` / `agent` / `hammerspoon` は特殊扱いで汎用ループから除外されているので注意）
3. `install.sh` は冪等に保つ（再実行で壊れない）

## Git ワークフロー

- main ブランチへ conventional commit (`feat:`, `fix:`, `chore:` ...)
- 設定変更は `./install.sh` で再リンクして動作確認してからコミット
