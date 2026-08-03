# Configuration workflow

## Per-machine設定

機械固有の値はcommitせず、local設定へ分離する。

- Fish: `configs/fish/conf.d/*.local.fish`
- Fish function: `configs/fish/functions/local/*`
- Claude Code: `configs/claude/settings.local.json`

新しいlocal設定パターンを追加するときは`.gitignore`も更新する。

## 新しいアプリ設定

1. `configs/{app}/`に設定を置く。
2. `install.sh`のsymlink loopが対象を拾うことを確認する。
3. `claude`、`agent`、`hammerspoon`、`herdr`は特殊扱いなので専用処理を確認する。
4. `install.sh`を再実行し、冪等性とlink先を検証する。

## OS固有処理

- Homebrew、cask、`defaults write`: macOS側だけで実行する。
- aptとLinux固有処理: Ubuntu側だけで実行する。
- symlink、miseなど共通化できる処理は共有する。
