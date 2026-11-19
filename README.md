# dotfiles

macOS (Apple Silicon) と Ubuntu 用の個人設定ファイル群。

## セットアップ

新しいMacで以下のスクリプトをターミナルにコピー&ペーストして実行してください。

```sh
# Homebrewのインストール
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Homebrewのパスを通す（Apple Silicon）
eval "$(/opt/homebrew/bin/brew shellenv)"

# gh, ghq のインストール
brew install gh ghq

# GitHub認証（ブラウザが開きます）
gh auth login

# dotfilesリポジトリの取得
ghq get Lettuce222/dotfiles

# リポジトリに移動
cd "$(ghq root)/github.com/Lettuce222/dotfiles"
```

macOS・Ubuntu ともに Rust 1.65 以上で、このマシン用のインストーラーをビルドします。
リポジトリを更新したときも、同じ手順でビルドし直せます。

```sh
cargo build --locked --release --manifest-path tools/installer/Cargo.toml
cp tools/installer/target/release/setup ./setup
./setup
```

`./setup` は、通常の端末に工程とプログレスバーを表示します。
生ログ表示は `./setup --plain`、失敗時のエージェント起動を止めるには `./setup --no-repair` を使えます。
初回は Claude Code（既定）、Codex、または別のコマンドを選べます。
fish で `agent` を実行すると起動し、`agent --which` で選択を確認できます。
マシンごとの切り替えは [設定ガイド](docs/configuration.md#メインの-coding-agent-cli) を参照してください。

## 含まれる設定

フォルダごとの役割とファイルの一覧は [`docs/overview.md`](docs/overview.md) を参照。

- fish: シェル
- git: バージョン管理
- gh: GitHub CLI
- ghostty: ターミナル
- hammerspoon: ウィンドウマネージャー
- karabiner: キーボードカスタマイズ
- lazygit: Git TUI
- mise: ランタイムマネージャー
- nvim: エディタ
- tmux: 明示的に起動する予備のターミナルマルチプレクサ
