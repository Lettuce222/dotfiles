# dotfiles

macOS（仕事）と Ubuntu（プライベート）両方で使う個人用 dotfiles。`install.sh` が `configs/*` を `$HOME` 以下にシンボリックリンクで配置する。

## 設定を編集するときのルール

**必ず `configs/` 配下のソースを編集する。`~/.config/` 以下は symlink なので、そこを編集しても git で追跡されない。**

- ✅ `configs/{app}/...`
- ❌ `~/.config/{app}/...`

Claude Code の設定は例外で、ディレクトリではなく**個別ファイル単位**で `~/.claude/` に symlink される（`CLAUDE.md`, `settings.json`, `hooks/`, `commands/`, `skills/`）。`~/.claude/` 内の動的ファイル（history, sessions など）は管理対象外。

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
2. `install.sh` の symlink ループが拾うことを確認（`claude` と `hammerspoon` は特殊扱いなので注意）
3. `install.sh` は冪等に保つ（再実行で壊れない）

## Git ワークフロー

- main ブランチへ conventional commit (`feat:`, `fix:`, `chore:` ...)
- 設定変更は `./install.sh` で再リンクして動作確認してからコミット
