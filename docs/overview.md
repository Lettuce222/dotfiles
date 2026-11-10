# dotfilesの全体像

dotfilesに何があり、どこへ置かれ、何をしているかを、全体から順に辿るための地図。上から読むと全体像、目次からフォルダへ飛ぶとそのフォルダの全ファイルの役割が分かる。決まりの細部は、各節の終わりのリンクから[`docs/agent-assets.md`](agent-assets.md)と[`docs/configuration.md`](configuration.md)へ進む。

## 目次

1. [全体像](#全体像)
2. [置き場所の対応](#置き場所の対応)
3. [普段の使われ方](#普段の使われ方)
4. フォルダごとの詳細
   - [リポジトリ直下](#リポジトリ直下)
   - [`configs/agent/`](#configsagent): Claude Codeの指示・skill・hook
   - [`configs/claude/`](#configsclaude): Claude Code本体の設定
   - [`configs/fish/`](#configsfish): シェル
   - [`configs/tmux/`](#configstmux): ターミナルマルチプレクサ
   - [`configs/nvim/`](#configsnvim): エディタ
   - [`configs/ghostty/`](#configsghostty): ターミナル
   - [`configs/git/`](#configsgit)、[`configs/gh/`](#configsgh)、[`configs/lazygit/`](#configslazygit): Git
   - [`configs/mise/`](#configsmise): ツールのインストール
   - [`configs/textlint/`](#configstextlint): AIが書く日本語のlint
   - [`configs/hammerspoon/`](#configshammerspoon): ウィンドウの配置
   - [`configs/karabiner/`](#configskarabiner): キーの割り当て
   - [`docs/`](#docs)、[`tests/`](#tests)、[`hooks/`](#hooks)
5. [変更の追い方](#変更の追い方)
6. [このページを保つ](#このページを保つ)

## 全体像

```text
dotfiles/
├── install.sh            セットアップの起点。configs/ を $HOME へ symlink し、ツールを入れる
├── configs/              設定の本体。アプリごとに 1 フォルダ
│   ├── agent/            Claude Code の指示・skill・hook（いちばん大きく、よく変わる）
│   ├── claude/           Claude Code 本体の settings.json・statusline
│   ├── fish/             シェル。abbr、関数、orchestrator コマンド
│   ├── tmux/             tmux.conf と、リンクを開く・PR を開くスクリプト
│   ├── nvim/             AstroNvim v5 の設定
│   ├── ghostty/          ターミナル
│   ├── git/ gh/ lazygit/ Git まわり
│   ├── mise/             CLI ツールの一覧（fzf、rg、gh、tmux、python …）
│   ├── textlint/         agent の hook が使う textlint のルールと npm 依存
│   ├── hammerspoon/      ウィンドウ配置（macOS）
│   └── karabiner/        キー配置（macOS）
├── docs/                 決まりの文書（このページ、agent-assets.md、configuration.md）
├── tests/                install.sh と tmux のリンクのテスト
└── hooks/pre-commit      gitleaks で秘密情報のコミットを止める
```

まとまりで見ると3層に分かれる。

| 層 | フォルダ | 役割 |
| --- | --- | --- |
| 基本 | `mise`、`fish`、`git`、`gh` | ツールを入れ、シェルとGitの動きを決める |
| 画面 | `ghostty`、`tmux`、`nvim`、`lazygit`、`hammerspoon`、`karabiner` | ターミナル、エディタ、ウィンドウ、キー |
| AIエージェント | `agent`、`claude`、`textlint` | Claude Codeの指示、外に出る文面の確認、窓口（orchestrator）とworker |

最近の変更の大半はAIエージェントの層に入っている（2026年10月20日以降のコミットで変わったファイルの数は、`configs/agent`と`configs/tmux`がそれぞれ100前後、`docs/agent-assets.md`が47、ほかは1桁から十数）。`configs/tmux`の多くは、のちに消した前の窓口（hub）の分。

## 置き場所の対応

`install.sh`がどこに何を置くか。`~/.config/`や`~/.claude/`の中はsymlinkなので、直すときは必ず左の列を編集する。

| ソース | 置き場所 | 置き方 |
| --- | --- | --- |
| `configs/<app>/`（下の3つ以外すべて） | `~/.config/<app>` | フォルダごとsymlink |
| `configs/hammerspoon/` | `~/.hammerspoon` | フォルダごとsymlink |
| `configs/agent/AGENTS.md` | `~/.claude/CLAUDE.md` | ファイルをsymlink |
| `configs/agent/skills/<name>/` | `~/.claude/skills/<name>` | skillごとにsymlink（ほかで入れたskillと同居させるため） |
| `configs/agent/hooks/*` | `~/.claude/hooks/` | ファイルごとにsymlinkし、実行ビットを付ける |
| `configs/claude/*.sh` | `~/.claude/` | ファイルごとにsymlink |
| `configs/claude/settings.json`と`settings.local.json` | `~/.claude/settings.json` | 合成して普通のファイルとして書き出す |
| `configs/git/ignore.shared` | `configs/git/ignore`の先頭の区切りの中 | 書き出す（`configs/git/ignore`はgitignore済み） |

`install.sh`の動き方は3つ。

- 引数なし: Homebrew、fish、ログインシェル、symlink、mise、textlint、アプリ、macOSのキーリピートまで全部。
- `--links-only`: symlinkと設定の生成だけ。ネットワークに出ず、symlinkでない本物のファイルは置き換えない。エージェントが反映に使う。
- `--dry-run`: `--links-only`の予定だけを出す。

どれもgitのworktreeからは実行を断る（symlinkが消えるworktreeを指さないように）。

追跡しない、そのマシンだけの設定は次のとおり。中身はコミットされない。

- `configs/fish/**/*.local.fish`、`configs/fish/functions/local/`
- `configs/claude/settings.local.json`（仕事用のpluginなど）
- `configs/mise/config.toml`（仕事用のMacではJamfが書く）
- `configs/git/ignore`（ほかのツールが行を書き足す）
- `configs/hammerspoon/layouts.yml`

詳しくは[`docs/configuration.md`](configuration.md)。

## 普段の使われ方

フォルダどうしは次のようにつながっている。

1. Ghostty（`configs/ghostty/`）を開くと、fish（`configs/fish/`）が起動する。`conf.d/00-init.fish`がmise・direnv・zoxideを有効にし、miseが`configs/mise/config.local.toml`のツール（fzf、rg、gh、tmux、lazygitなど）をPATHに載せる。
2. tmux（`configs/tmux/`）はprefixが`Ctrl-Space`。Ghosttyで押すとKarabiner（`configs/karabiner/`）が英数キーも送り、IMEをオフにする。`prefix g`でlazygit、`prefix e`でnvim、`prefix p`でPRのURLからworktreeを開く。
3. Claude Codeは`configs/claude/settings.json`で動きが決まる。tmuxのウィンドウ名に状態の印（🟡作業中、🔴確認待ち、🟢終わった）を付けるhook、外に出る文面を止めるhook、textlintのhookがここで配線される。hookの本体は`configs/agent/hooks/`にある。
4. `orchestrator`コマンド（`configs/fish/functions/orchestrator.fish`）でtmux session `orchestrator`を開く。左が窓口（`claude -n orchestrator`）、右が案件の一覧（`cases.py board`）。窓口は依頼ごとにbackgroundのworker（`claude --bg`）を起こし、見張りのworker`chore-hub-watch`が30分ごとにGitHubとSlackを読む。リポジトリを変えるworkerはそのリポジトリのworktreeで、ほかは`~/hub/workers/<worker名>/`で動く。決まりは`configs/agent/skills/`の`agents-orchestrator`・`agents-worker`・`agents-watch`の3つのskill。
5. 画面に出たリンク（OSC 8）をtmuxでクリックすると`configs/tmux/scripts/open-link.sh`が開く。`.md`はpopupのleaf、ほかのテキストはpopupのnvim、フォルダはFinder。
6. ウィンドウの配置はHammerspoon（`configs/hammerspoon/`）が`Alt`系のキーで行う。

## フォルダごとの詳細

### リポジトリ直下

| ファイル | 役割 |
| --- | --- |
| `install.sh` | セットアップの起点。Phase 1（sh）でHomebrew・fish・symlink・設定の生成、Phase 2（fish）でフォント・mise・textlint・アプリ（Slack、Ghostty、Raycastなど）・macOSのキーリピート |
| `CLAUDE.md` | このリポジトリで作業するエージェントへの決まり（`configs/`を編集する、両OSを壊さない、mainへ直接push、`./install.sh`で反映してから完了） |
| `README.md` | 新しいMacでのセットアップ手順と、含まれる設定の一覧 |
| `.gitignore` | local設定、バックアップ（`*.bak.*`）、`node_modules`などを除く |

### `configs/agent/`

Claude Codeに読ませる指示・skill・hook。dotfilesでいちばん大きく、最近の変更の大半がここ。決まりの全文は[`docs/agent-assets.md`](agent-assets.md)。

`configs/agent/AGENTS.md`は、どのリポジトリでも毎回読まれる指示（`~/.claude/CLAUDE.md`）。中身は4つだけで、Bashはzshで動くこと、周りのコードに合わせること、外に出す文面はまず`.md`に下書きしてtextlintを通すこと、会社や案件の文脈をdotfilesに置かないこと。

#### skill（`configs/agent/skills/`）

必要な作業のときだけ読み込まれる手順書。

| skill | いつ使うか | 付属のスクリプト |
| --- | --- | --- |
| `configs/agent/skills/agents-orchestrator/` | 窓口が起動時に読む。依頼を自分で作業せずworkerに任せる、承認の要る操作、案件の一覧の書き方 | `scripts/cases.py`: 案件の一覧の描画（`board`）、解けたWaitingの片付け（`sweep`）、1項目の解決（`resolve`） |
| `configs/agent/skills/agents-worker/` | 窓口が起こしたworkerが読む。報告の形（完了・要判断・送信の確認待ち・ブロック）、AskUserQuestionを使わないこと、署名つきのコミットの仕方（`git commit`を単独の1本で実行し、rebaseはユーザーに頼む） | なし |
| `configs/agent/skills/agents-thread/` | `agents-worker`の古い名前。名前を変える前に起動したworkerや古い依頼の`/agents-thread`のために互換の別名として残し、読み込むと`agents-worker`に従わせる。動いているworkerが片付いたら消す | なし |
| `configs/agent/skills/agents-watch/` | 見張りのworkerが30分ごとに読む。GitHubのレビュー依頼・自分のPRの動き、Slackのメンションを窓口へ知らせる | `scripts/watch.py`: `gh api graphql`で読むだけ。知らせ済みの記録 |
| `configs/agent/skills/commit-push/` | 未コミットの変更を意図ごとにコミットしてpushする | なし |
| `configs/agent/skills/gh-fix-ci/` | GitHub ActionsのPR checkの失敗を調べて直す | なし |
| `configs/agent/skills/grill-me/` | 計画や設計を質問で掘り下げる | なし |
| `configs/agent/skills/pr-review-comment/` | ほかの人のPRに1つのpending reviewで行コメントを付ける | `references/review-guide.md` |
| `configs/agent/skills/report-writing/` | 上長向けの進捗報告を空雨傘で書く | `scripts/md_to_gdocs.py`: Google Docsへ貼るための変換（fishの`md-gdocs`） |

#### hook（`configs/agent/hooks/`）

置くのはここ、いつ動くかは`configs/claude/settings.json`で決める。

| ファイル | いつ動くか | 何をするか |
| --- | --- | --- |
| `configs/agent/hooks/update-tmux-window-title.sh` | 依頼を送ったとき🟡、確認待ち🔴、終わったとき🟢 | tmuxのウィンドウ名の先頭に状態の印を付ける |
| `configs/agent/hooks/clear-tmux-window-title.sh` | セッションの終了 | 同じウィンドウにほかのClaudeがいなければ印を消す |
| `configs/agent/hooks/clear-green-tmux-window-title.sh` | tmuxでウィンドウを移ったとき（`tmux.conf`のhook） | 🟢だけを消す |
| `configs/agent/hooks/textlint-markdown.sh` | `.md`を書いた直後 | textlintにかけ、指摘があれば書き直させる |
| `configs/agent/hooks/textlint-mcp.sh` | MCPのtoolを呼ぶ前 | 送る本文の日本語をtextlintにかけ、指摘があれば止める |
| `configs/agent/hooks/external-post-guard.py` | MCPのtoolと、ghの書き込みの前 | リンクになっていないチケットID・PR番号、曜日のない日付を止める。通れば、承認の記録があれば通し、無ければ送り先と本文を見せて確認を出す |
| `configs/agent/hooks/approvals.py` | 窓口がユーザーの承認の直後に呼ぶ | 承認した操作を1回だけ通す記録を`~/hub/state/approvals/`に書く（30分で切れる）。workerに向けた記録は`--worker <worker名>`で書く（古い`--thread`も受け付ける） |
| `configs/agent/hooks/approval-gate.py` | 確認ダイアログの直前、とtoolの実行前 | workerではダイアログの代わりに断り、窓口で聞く流れに乗せる。承認の記録と一致すれば通す |
| `configs/agent/hooks/tmux-socket-guard.py` | Bashの実行前 | いつも使っているtmuxサーバーを止めるコマンドを止める |

#### テスト（`configs/agent/tests/`）

`configs/agent/tests/`にある。どれも`python3 -m unittest configs/agent/tests/<ファイル>`で動き、本物のtmuxサーバー・gh・claudeには触らない。

| テスト | 確かめるもの |
| --- | --- |
| `configs/agent/tests/test_approvals.py` | `approvals.py`と`approval-gate.py` |
| `configs/agent/tests/test_external_post_guard.py` | `external-post-guard.py` |
| `configs/agent/tests/test_tmux_socket_guard.py` | `tmux-socket-guard.py` |
| `configs/agent/tests/test_cases.py` | `cases.py` |
| `configs/agent/tests/test_agents_watch.py` | `watch.py` |
| `configs/agent/tests/test_md_to_gdocs.py` | `md_to_gdocs.py` |
| `configs/agent/tests/test_orchestrator.py` | `orchestrator`のペインの構成、workerがAskUserQuestionを使わないこと、workerのコミットの決まり、`agents-thread`が`agents-worker`に回すこと |

`~/hub/`（窓口の作業場所、リポジトリに紐づかないworkerの作業場所`~/hub/workers/`、案件の中身、承認の記録、見張りの状態）はdotfilesの外にあり、追跡しない。前の窓口（hub、hub-dash）は消してあり、中身はtag `hub-v1-20261104`で見られる。

### `configs/claude/`

Claude Code本体の設定。skillやhookの本体は`configs/agent/`に置く。

| ファイル | 役割 |
| --- | --- |
| `configs/claude/settings.json` | 共通の設定。`install.sh`が`settings.local.json`と合成して`~/.claude/settings.json`に書き出す。主な中身は次の一覧 |
| `configs/claude/statusline.sh` | ステータスラインにモデル、コンテキストの使用率のバー、トークン数、費用を出す |
| `configs/claude/file-suggestion.sh` | `@`のファイル候補を`fd`と`fzf`で出す |

`configs/claude/settings.json`の主な中身は次のとおり。

- permission: `defaultMode`は`auto`。`git add`・`commit`・`push`、`rg`、`ls`などは確認なしで許し、`printenv`・`env`・`export`など環境変数を読むものは禁止
- hook: 上の[hookの表](#hookconfigsagenthooks)の配線
- `language: Japanese`、`tui: fullscreen`、`autoMemoryEnabled: false`（覚えさせたいことはmemoryでなくskillや`CLAUDE.md`に書く）
- 環境変数: subagentのモデルを`sonnet`にする

### `configs/fish/`

シェル。`~/.config/fish`へsymlink。

| ファイル | 役割 |
| --- | --- |
| `configs/fish/config.fish` | ほぼ空。設定は`conf.d/`に分ける |
| `configs/fish/conf.d/00-init.fish` | 対話のときmise、direnv、zoxide、Homebrewを有効にする。`functions/local/`を関数の探し先に足す |
| `configs/fish/conf.d/env.fish` | `XDG_CONFIG_HOME`、`EDITOR=nvim`、fzfの既定 |
| `configs/fish/conf.d/abbreviations.fish` | abbr。`g`→git、`lg`→lazygit、`cl`→claude、`n`→nvim、`gps`→git push、Rails系など |
| `configs/fish/conf.d/fish_frozen_key_bindings.fish`、`configs/fish/conf.d/fish_frozen_theme.fish` | fish 4.3への移行でfishが作ったファイル。色のテーマ |
| `configs/fish/conf.d/local.fish.example` | local設定の雛形 |
| `configs/fish/agent-env.fish` | `orchestrator`が窓口を起動する前に読み込む。非対話のfishでもmise・direnv・ghtknの`gh`ラッパーを使えるようにする |

関数（`configs/fish/functions/`）は次のとおり。

| 関数 | 何をするか |
| --- | --- |
| `configs/fish/functions/orchestrator.fish` | 窓口と案件の一覧のtmux sessionを開く（[普段の使われ方](#普段の使われ方)の4） |
| `configs/fish/functions/cd.fish`、`configs/fish/functions/code.fish` | 引数なしなら`ghq list`をfzfで選んで移る、VS Codeで開く |
| `configs/fish/functions/cw.fish` | ghqのリポジトリを`--add-dir`で足してClaude Codeを起動 |
| `configs/fish/functions/td.fish` | 今のフォルダ名でtmux sessionを作って移る |
| `configs/fish/functions/review-pr.fish` | 自分宛てのレビュー依頼をfzfで選んでcheckout |
| `configs/fish/functions/create-pr.fish`、`configs/fish/functions/plan-issue.fish` | gooseのrecipe（`~/.goose/recipes/`、dotfilesの外）でPRや計画を作る。古い仕組み |
| `configs/fish/functions/md-gdocs.fish` | `report-writing`の`md_to_gdocs.py`を呼ぶ |
| `configs/fish/functions/fzf-preview.fish`、`configs/fish/functions/rgopen.fish` | ファイルや行をfzfで探して開く（`rgopen`はemacsで開く） |
| `configs/fish/functions/ls.fish` | `eza`で表示 |
| `configs/fish/functions/killport.fish` | ポートを使うプロセスを止める |
| `configs/fish/functions/fish_prompt.fish`、`configs/fish/functions/fish_user_key_bindings.fish` | プロンプト（パスとgitの状態）、fzfのキーと`Ctrl-G`でコマンドをエディタで直す |
| `configs/fish/functions/b.fish`、`configs/fish/functions/g.fish`、`configs/fish/functions/mux.fish` | bundle、git、tmuxinatorの別名 |

### `configs/tmux/`

`~/.config/tmux`へsymlink。READMEでは「明示的に起動する予備」の扱い。

| ファイル | 役割 |
| --- | --- |
| `configs/tmux/tmux.conf` | prefixは`Ctrl-Space`、`-`と`\|`で分割、`hjkl`で移動、vi風のコピー。TokyoNightに合わせた色。OSC 8のリンクのクリックを`open-link.sh`へ渡す。ウィンドウを移ると🟢を消す |
| `configs/tmux/scripts/open-link.sh` | クリックしたリンクを開く。`.md`はpopupのleaf（無ければnvim）、テキストはpopupのnvim、フォルダはFinder、それ以外は既定のアプリ |
| `configs/tmux/scripts/tm-pr.fish` | `prefix p`。PRのURLを貼ると、ghqでリポジトリを探し、`<repo>.worktrees/<branch>`にworktreeを作ってwindowを開く |

テストは`tests/test_open_link.py`。

### `configs/nvim/`

AstroNvim v5のテンプレートから作った設定。`~/.config/nvim`へsymlink。

| ファイル | 役割 |
| --- | --- |
| `configs/nvim/init.lua` | lazy.nvimを入れて`lazy_setup`と`polish`を読む |
| `configs/nvim/lua/lazy_setup.lua` | AstroNvim本体、leaderは`Space` |
| `configs/nvim/lua/community.lua` | AstroCommunityから取り込むもの。tokyonight、言語pack（lua、json、bash、fish、toml、yaml）、auto-save、octo、diffview、render-markdown |
| `configs/nvim/lua/plugins/astrocore.lua` | 相対行番号、折り返しなし、バッファ移動のキー |
| `configs/nvim/lua/plugins/astroui.lua` | 背景を透過にする色の上書き |
| `configs/nvim/lua/plugins/conform.lua` | 保存時の整形（stylua、shfmt、fish_indent、taplo、prettier） |
| `configs/nvim/lua/plugins/lint.lua` | shellcheckとfishのlint |
| `configs/nvim/lua/plugins/neo-tree.lua`、`configs/nvim/lua/plugins/snacks.lua` | 隠しファイルとgitignore済みのファイルも出す |
| `configs/nvim/lua/plugins/astrolsp.lua`、`configs/nvim/lua/plugins/mason.lua`、`configs/nvim/lua/plugins/none-ls.lua`、`configs/nvim/lua/plugins/treesitter.lua`、`configs/nvim/lua/plugins/user.lua`、`configs/nvim/lua/polish.lua` | テンプレートのまま。先頭の`if true then return`で無効 |
| `configs/nvim/lazy-lock.json` | pluginの版の固定 |
| `configs/nvim/README.md`、`configs/nvim/.luarc.json`、`configs/nvim/.neoconf.json`、`configs/nvim/.stylua.toml`、`configs/nvim/selene.toml`、`configs/nvim/neovim.yml` | テンプレートに付いてきた説明とLuaの開発ツールの設定 |

### `configs/ghostty/`

| ファイル | 役割 |
| --- | --- |
| `configs/ghostty/config` | フォントはUDEV Gothic NF、テーマはTokyoNight Storm、`Ctrl-\`と`Ctrl--`で分割。OSC 8のリンクはtmuxのクリックで開くので、Ghosttyでは無効にする |

### `configs/git/`

`~/.config/git`へフォルダごとsymlink。

| ファイル | 役割 |
| --- | --- |
| `configs/git/config` | 名前とnoreplyのメール、コミットとtagにSSH署名、pagerは`delta`、`merge.conflictStyle=zdiff3` |
| `configs/git/ignore.shared` | 全リポジトリで無視するもの（`.claude/settings.local.json`、`.claude/worktrees/`）。`install.sh`が`configs/git/ignore`に書き出す |

署名の鍵のパスなどマシン固有のgitの設定は、追跡しない`~/.gitconfig`に書く。

### `configs/gh/`

| ファイル | 役割 |
| --- | --- |
| `configs/gh/config.yml` | ghの設定。別名`co`→`pr checkout` |
| `configs/gh/hosts.yml` | github.comのユーザー名（トークンは入れない） |

### `configs/lazygit/`

| ファイル | 役割 |
| --- | --- |
| `configs/lazygit/config.yml` | アイコンを出し、差分を`delta`で描く |

### `configs/mise/`

`~/.config/mise`へフォルダごとsymlink。

| ファイル | 役割 |
| --- | --- |
| `configs/mise/config.local.toml` | dotfilesが入れるCLIツールの一覧（fd、fzf、rg、gh、ghq、tmux、lazygit、delta、eza、zoxide、leaf、node、python、go、各種のlinter）。`minimum_release_age = "7d"`で出たばかりの版は入れない |
| `configs/mise/default-python-packages` | pythonを入れたときにpipで入れるライブラリ（PyYAML） |

`config.toml`はJamfに任せるためgitignore済み。`mise use -g`は`config.toml`に書くので、dotfilesには入らない。

### `configs/textlint/`

`~/.config/textlint`へsymlink。agentのhook（`textlint-markdown.sh`、`textlint-mcp.sh`）が使う。

| ファイル | 役割 |
| --- | --- |
| `configs/textlint/.textlintrc.json` | AIの書く日本語向けのルール2つ（`preset-ai-writing`、`preset-ai-words-ja`） |
| `configs/textlint/package.json`、`configs/textlint/package-lock.json` | npm依存。`install.sh`が`npm ci`で入れる。入っていないマシンではhookは何もしない |

### `configs/hammerspoon/`

macOSのウィンドウ配置。`~/.hammerspoon`へsymlink。

| ファイル | 役割 |
| --- | --- |
| `configs/hammerspoon/init.lua` | `layouts.yml`を読んでhotkeyを登録。`Alt+H/L`で左右のウィンドウ、`Alt+J/K`で隣のモニタ、`Alt+U/I/O`で左半分・右半分・全画面（`Shift`付きで隣のモニタへ移して）、`Cmd+Alt+Ctrl+R`で読み直し |
| `configs/hammerspoon/modules/yaml_loader.lua`、`configs/hammerspoon/lib/tinyyaml.lua` | YAMLを読む |
| `configs/hammerspoon/modules/keybinder.lua` | layoutごとのhotkeyの登録 |
| `configs/hammerspoon/modules/layout_manager.lua` | layoutの適用と、押すたびの切り替え |
| `configs/hammerspoon/modules/window_utils.lua` | ウィンドウの配置、アプリの起動、画面の扱い |
| `configs/hammerspoon/layouts.yml.example` | 共有してよいlayoutの例。実際の`layouts.yml`は追跡しない |
| `configs/hammerspoon/CLAUDE.md`、`configs/hammerspoon/references/layouts.md` | 変更するときの決まりと、YAMLの書き方 |

### `configs/karabiner/`

macOSのキー配置。`~/.config/karabiner`へsymlink。

| ファイル | 役割 |
| --- | --- |
| `configs/karabiner/karabiner.json` | 有効な設定。Caps LockをControlに、OptionとCommandの単体押しで英数・かな、GhosttyでCtrl-Space（tmuxのprefix）を押すとIMEをオフ、Emacs風のキー、ChromeのCtrl-Tabを拡張機能へ |
| `configs/karabiner/assets/complex_modifications/` | Karabinerの画面から読み込むルールの元（Emacs風のキー、日本語環境向け、ChromeのCtrl-Tab、全角スペースを半角に） |

### `docs/`

| ファイル | 役割 |
| --- | --- |
| `docs/overview.md` | このページ |
| `docs/agent-assets.md` | `configs/agent/`と`configs/claude/`の決まりの全文。hookの細かい判定、承認の記録、窓口とworker、案件の一覧 |
| `docs/configuration.md` | per-machine設定、`settings.json`の合成、gitのglobalのignore、mise、`--links-only`、tmuxのリンク、新しいアプリの足し方 |

### `tests/`

リポジトリ直下のテスト。`python3 -m unittest tests/<ファイル>`で動く。

| ファイル | 確かめるもの |
| --- | --- |
| `tests/test_install_links_only.py` | `install.sh --links-only`と`--dry-run`。一時ディレクトリを`HOME`にし、brewなどは偽物に差し替える |
| `tests/test_open_link.py` | `open-link.sh`がリンクの種類ごとに正しいもので開くこと |
| `tests/test_overview.py` | 追跡しているファイルがすべてこのページに載っていること、このページに載っているパスが実在すること |

### `hooks/`

| ファイル | 役割 |
| --- | --- |
| `hooks/pre-commit` | gitleaksで、ステージした変更に秘密情報が無いか確かめる。`install.sh`は有効にしないので、使うにはgitのhookとして手で配線する |

## 変更の追い方

窓口のworkerはmainへ直接pushするので、何が入ったかはgitで見る。

```fish
# 最近入ったコミットを、変わったファイルと一緒に見る
git log --since='1 week ago' --stat --pretty='%n%ad %s' --date=short

# フォルダごとに絞る
git log --oneline -- configs/agent/
git log --oneline -- configs/tmux/ configs/fish/

# 前回見たところから今までの差分（見た位置はtagで残しておく）
git diff --stat reviewed..origin/main
git tag -f reviewed origin/main
```

コミットのscopeでも絞れる。`feat(agent)`・`fix(agent)`は窓口・worker・hook、`feat(tmux)`はtmuxのリンクや表示、`feat(install)`は`install.sh`、`fix(mise)`はツールの一覧。

ここ3週間ほどの大きな流れは次のとおり。

- 2026年10月29日〜11月4日: tmuxのwindowでworkerを動かす窓口（hub）を作り、外に出る文面のhook（`external-post-guard.py`）、`install.sh --links-only`、`report-writing`を足した。Codexの管理はやめた。
- 2026年11月4日〜11月6日: hubを消し、`claude --bg`と`claude agents`だけで組む`orchestrator`に置き換えた。案件の一覧（`cases.py`）、見張りのworker（`agents-watch`）、承認の記録（`approvals.py`、`approval-gate.py`）を足した。
- 2026年11月9日〜11月10日: 案件の一覧にworkerの状態とTODOの急ぐ順を出し、tmuxのリンクで`.md`をleafで開くようにした。miseの設定を`config.local.toml`へ、gitのglobalのignoreを`ignore.shared`からの生成へ移した。SlackやPRのスレッドと紛らわしいので、backgroundのエージェントの呼び方を「スレッド」から「worker」に改め、skillを`agents-worker`（`agents-thread`は互換の別名）、`approvals.py`の`--thread`を`--worker`、作業場所を`~/hub/workers/`にした。

## このページを保つ

フォルダやファイルを足す・消す・役割を変えるときは、このページの該当の節も直す。`tests/test_overview.py`が、追跡しているファイルの載せ忘れと、消したファイルの載せっぱなしを見つける。

```fish
python3 -m unittest tests/test_overview.py
```

フォルダとして載せたもの（末尾が`/`のパス）は、その下のファイルをまとめて載せたものとみなす。
