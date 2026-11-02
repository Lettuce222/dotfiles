# Configuration workflow

## Per-machine設定

機械固有の値はcommitせず、local設定へ分離する。

- Fish: `configs/fish/**/*.local.fish`（補完はファイル名がコマンド名と一致する必要があるため、`conf.d/*.local.fish`内で読み込む）
- Fish function: `configs/fish/functions/local/*`
- Claude Code: `configs/claude/settings.local.json`（仕事用のpluginなど。下の「Claude Codeのuser設定」を参照）

## Claude Codeのuser設定

Claude Codeがuser scopeで読む設定ファイルは`~/.claude/settings.json`だけで、`~/.claude/settings.local.json`は読まない。`claude plugin enable`、`/config`、`/model`も`~/.claude/settings.json`へ書き込む。symlinkにすると、その書き込みが追跡しているファイルに入ってしまう。

そこで`install.sh`は、追跡している`configs/claude/settings.json`とgitignore済みの`configs/claude/settings.local.json`を合成し、`~/.claude/settings.json`を通常のファイルとして書き出す。合成ではobjectをkeyごとにまとめ、配列は重複を除いて連結し、それ以外の値はlocalを優先する。

- 設定を変えたら、`configs/claude/`のどちらかを編集し、`./install.sh`を再実行する。
- 共通の設定は`settings.json`に、マシン固有の設定（仕事用のplugin、marketplace、hookなど）は`settings.local.json`に書く。
- `install.sh`は前回書き出した内容を`~/.claude/settings.json.generated`に残す。`claude plugin enable`などで`~/.claude/settings.json`が変わっていたら、上書きする前に`settings.json.bak.<日時>`へ退避して警告する。必要な変更は`settings.local.json`へ移す。

新しいlocal設定パターンを追加するときは`.gitignore`も更新する。

## 新しいアプリ設定

1. `configs/{app}/`に設定を置く。
2. `install.sh`のsymlink loopが対象を拾うことを確認する。
3. `claude`、`agent`、`hammerspoon`は特殊扱いなので専用処理を確認する。
4. `install.sh`を再実行し、冪等性とlink先を検証する。

## OS固有処理

- Homebrew、cask、`defaults write`: macOS側だけで実行する。
- aptとLinux固有処理: Ubuntu側だけで実行する。
- symlink、miseなど共通化できる処理は共有する。
