# dotfiles

macOS (Apple Silicon) 用の個人設定ファイル群。

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

# install.shの実行
cd "$(ghq root)/github.com/Lettuce222/dotfiles" && ./install.sh
```

## 含まれる設定

- fish: シェル
- git: バージョン管理
- gh: GitHub CLI
- ghostty: ターミナル
- hammerspoon: ウィンドウマネージャー
- karabiner: キーボードカスタマイズ
- lazygit: Git TUI
- mise: ランタイムマネージャー
- nvim: エディタ
- tmux: ターミナルマルチプレクサ
