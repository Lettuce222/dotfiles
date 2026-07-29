# dotfiles

macOS（仕事）と Ubuntu（プライベート）両方で使う個人用 dotfiles。`install.sh` が `configs/*` を `$HOME` 以下にシンボリックリンクで配置する。

## 編集時の契約

**必ず `configs/` 配下のソースを編集する。`~/.config/` 以下は symlink なので、そこを編集しても git で追跡されない。**

- AI agent資産は個別にsymlinkされる。配線と管理境界は [`docs/agent-assets.md`](docs/agent-assets.md) を参照。
- アプリ追加・per-machine設定・install規約は [`docs/configuration.md`](docs/configuration.md) を参照。

## Multi-OS 対応

- macOSとUbuntuの両方を壊さない。
- OS固有処理は`install.sh`で分岐し、共通のsymlink・mise処理は共有する。
- `install.sh`は冪等に保つ。

## Git ワークフロー

- main ブランチへ conventional commit (`feat:`, `fix:`, `chore:` ...)
- 設定変更は `./install.sh` で再リンクして動作確認してからコミット
