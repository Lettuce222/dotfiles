# Configuration workflow

## Per-machine設定

機械固有の値はcommitせず、local設定へ分離する。

- Fish: `configs/fish/**/*.local.fish`（補完はファイル名がコマンド名と一致する必要があるため、`conf.d/*.local.fish`内で読み込む）
- Fish function: `configs/fish/functions/local/*`
- `orchestrator` で独自の `gh` ラッパーを優先する場合は、実行ファイルを含むディレクトリを `AGENT_GH_WRAPPER_DIR` で指定する。
- Claude Code: `configs/claude/settings.local.json`（下の「Claude Codeのuser設定」を参照）
- mise: `configs/mise/config.toml`（下の「miseの設定」を参照）
- Gitのglobalのignore: `configs/git/ignore`（下の「Gitのglobalのignore」を参照）

## メインの coding agent CLI

原本は Git 管理外の `configs/agent/cli.local`。インストーラーが `~/.config/dotfiles-agent-cli`
から原本へのシンボリックリンクを張る。選択値が空なら、対話端末で Claude Code（既定）、
Codex、その他から選び、原本に保存する。Enter のみ、または非対話実行では `claude` が既定。
旧パスに通常の設定ファイルがあれば、原本に移す。両方にファイルがあれば
原本を使い、旧ファイルは `~/.config/dotfiles-agent-cli.bak.*/choice` に退避する。

選択を固定するには、原本に `claude`、`codex`、または PATH 上の単一のコマンド名
（例 `aider`）を1行で書く。環境変数
`DOTFILES_AGENT` はその実行時だけ優先する（例: `env DOTFILES_AGENT=codex ./install.sh --links-only`）。
すでに CLI が入っていれば `./install.sh --links-only` で反映できる。
CLI の導入も必要なら `./install.sh` を実行する。

fish では `agent --which` で確認し、`agent` で起動する。CLI 固有の引数は
`agent` にそのまま渡せる。`cw <ghqのリポジトリ名>` は見つけたディレクトリを
`--add-dir` で追加する。Codex の `--add-dir` は追加の書き込み範囲も指定する。
`orchestrator` は選択中の CLI を窓口として今のターミナルで開く。
「その他」のコマンドは `install.sh` では導入しないので、別途インストールして PATH に追加する。
`agent` と `orchestrator` から起動できる。追加のリポジトリが必要な場合はそのリポジトリで `agent` を起動する。

Claude を選ぶと Claude の設定とスキルを反映する。Codex を選ぶと
`${CODEX_HOME:-~/.codex}/AGENTS.md` と `~/.agents/skills/` に共通資産を配置する。
同名の手持ちの Codex 指示・スキルがあれば、配置先をスキップして表示する。
切り替え後も、以前の CLI の設定・セッションは利用できる。

## Claude Codeのuser設定

Claude Codeがuser scopeで読む設定ファイルは`~/.claude/settings.json`だけで、`~/.claude/settings.local.json`は読まない。`claude plugin enable`、`/config`、`/model`も`~/.claude/settings.json`へ書き込む。symlinkにすると、その書き込みが追跡しているファイルに入ってしまう。

そこで`install.sh`は、追跡している`configs/claude/settings.json`とgitignore済みの`configs/claude/settings.local.json`を合成し、`~/.claude/settings.json`を通常のファイルとして書き出す。合成ではobjectをkeyごとにまとめ、配列は重複を除いて連結し、それ以外の値はlocalを優先する。

- 設定を変えたら、`configs/claude/`のどちらかを編集し、`./install.sh`を再実行する。
- 共通の設定は`settings.json`に、マシン固有の設定（plugin、marketplace、hookなど）は`settings.local.json`に書く。
- `install.sh`は前回書き出した内容を`~/.claude/settings.json.generated`に残す。`claude plugin enable`などで`~/.claude/settings.json`が変わっていたら、上書きする前に`settings.json.bak.<日時>`へ退避して警告する。必要な変更は`settings.local.json`へ移す。

新しいlocal設定パターンを追加するときは`.gitignore`も更新する。

### local設定に置くもの

- Git: ローカルの絶対パスや鍵のファイル名など、マシン固有のgit設定（`user.signingkey`、`gpg.ssh.allowedSignersFile`など）は、追跡しない`~/.gitconfig`に書く。`~/.config/git`はディレクトリごと`configs/git`へのsymlinkなので、`git config --file ~/.config/git/config`で書くとリポジトリに入る。`git config --global`は、`~/.gitconfig`があればそこへ書く。共有してよい設定だけを`configs/git/config`に置く。
- 試している段階のツール（Orcaなど）: 追跡しているファイルに書かず、`configs/fish/conf.d/*.local.fish`などgitignore済みのlocal設定に置く。正式に採用すると決めてから、追跡するファイルへ移す。

## Gitのglobalのignore

`~/.config/git`はディレクトリごと`configs/git`へのsymlinkなので、gitがglobalのignoreとして読む`~/.config/git/ignore`は`configs/git/ignore`になる。このファイルには、ほかのツールが行を書き足す。Claude Codeは、作業用のフォルダ`.claude/.cc-writes/`がgitで無視されていないと、`git config --global core.excludesfile`が指すファイル（設定が無ければ`~/.config/git/ignore`）の末尾に`**/.claude/.cc-writes/`を書き足す。

gitが読むglobalのignoreは1つだけなので、`configs/git/ignore`はgitignoreし、この機械だけのファイルにする。dotfilesで管理するruleは`configs/git/ignore.shared`に書く。`install.sh`（`--links-only`も）は、`ignore.shared`の中身を`configs/git/ignore`の先頭の区切り（`# >>> dotfiles`から`# <<< dotfiles`まで）に書き、区切りの外の行はそのまま残す。

- ruleを足すときは`configs/git/ignore.shared`を編集し、`./install.sh --links-only`を実行する。
- `configs/git/ignore`の区切りの中は、次の`install.sh`で書き直される。この機械だけのruleは区切りの外に書く。
- `core.excludesFile`は設定しない。設定すると、Claude Codeはそのファイルへ書き足す。

## miseの設定

`~/.config/mise`はディレクトリごと`configs/mise`へのsymlinkにしている。dotfilesで管理するmiseの設定は`configs/mise/config.local.toml`に書く。

`configs/mise/config.toml` は Git 管理外で、マシン固有の設定に使う。mise は
`[settings]` をキーごとに読み込み、両方にあるキーは `config.local.toml` を優先する。

- 設定を変えるときは`configs/mise/config.local.toml`を直接編集する。`mise use -g`は`config.toml`へ書くので、そのツールはdotfilesに入らない。
- tmux は `aqua:tmux/tmux-builds` のビルド済み配布を使う。既存の asdf プラグインに依存せず、Mac と Ubuntu ともにローカルでの C ビルドを省ける。

## リンクと設定だけを反映する

`./install.sh --links-only`は、symlinkの配置と`configs/git/ignore`の生成を行う。Claudeを選んだときは`~/.claude/settings.json`も生成する。ネットワークアクセスやパスワードを必要としない。`./install.sh --dry-run`は同じ判定をして、予定だけを出す。

- `--dry-run` は選択を尋ねず、未設定のときは既定の選択で計画を表示する。
- 何度実行しても同じ結果になる。リンク先がすでに正しいものは触らない。
- 通常は別の場所を指すsymlinkを張り替え、symlinkでない既存のファイルやディレクトリは`skip:`で知らせる。旧CLI選択ファイルは上記の手順で移行する。
- `~/.claude/settings.json`は、合成の結果と違い、かつ前回の生成（`settings.json.generated`）から変わっていないときだけ書き換え、変わるJSONのpathを`+`（追加）、`-`（削除）、`~`（値の変更）で1行ずつ出す。`claude plugin enable`などで変わっていたら上書きせず、`skip:`の行と差分を出す。退避して作り直すには引数なしの`./install.sh`を使う。
- 最後に、変えたこと（`link`、`relink`、`mkdir`、`chmod +x`、`write`、`rewrite`など）を1行ずつ出す。何も変わらなければ`変更なし`と出す。
- worktreeからの実行は、引数なしのときと同じく断る。
- Claudeの`~/.claude/hooks`が壊れたsymlinkなら、`hooks.bak.*/link`に退避してhooksを配置し直す。

テスト: `python3 -m unittest tests/test_install_links_only.py`

## tmuxのリンクのクリック

tmuxの中でOSC 8のリンクをクリックすると、`configs/tmux/scripts/open-link.sh`が開く。`file://`のMarkdown（`.md`）はpopupの[leaf](https://leaf.rivolink.mg/)で、ほかのテキストのファイルはpopupのnvimで、フォルダはFinder（Linuxでは`xdg-open`）で、画像などテキストでないファイルとそれ以外のURLは既定のアプリで開く。フォルダをFinderで開くのは、画像をGitHubなどへドラッグして使うため。leafはmise（`github:rivolink/leaf`）で入れる。入っていないマシンでは`.md`もnvimで開く。leafは行を指定して開けないので、`#L<行>`は無視する。

テスト: `python3 -m unittest tests/test_open_link.py`

## dotfilesで作るコマンド

自前のコマンドのソースは`tools/<name>/`に置く。`configs/`の下はフォルダごと`~/.config`へsymlinkされるので、設定でないソースは置かない。

- 引数なしの`install.sh`が、miseのgoで`~/.local/bin/<name>`にビルドする（`install_lazygtd`）。ビルドに失敗しても警告だけを出し、ほかのセットアップを続ける。
- `--links-only`と`--dry-run`はビルドしない。コードを変えたら、`go build -C tools/<name> -o ~/.local/bin/<name> .`か引数なしの`./install.sh`で作り直す。
- 実行ファイルはコミットしない。

## 新しいアプリ設定

1. `configs/{app}/`に設定を置く。
2. `install.sh`のsymlink loopが対象を拾うことを確認する。
3. `claude`、`agent`、`hammerspoon`は特殊扱いなので専用処理を確認する。
4. `install.sh`を再実行し、冪等性とlink先を検証する。

## OS固有処理

- Homebrew、cask、`defaults write`: macOS側だけで実行する。
- aptとLinux固有処理: Ubuntu側だけで実行する。
- symlink、miseなど共通化できる処理は共有する。
