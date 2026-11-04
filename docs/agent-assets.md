# AI agent assets

AI agentはClaude Codeだけを管理する。指示、skill、hookは`configs/agent/`を単一ソースにする。

Codexの設定は管理しない。`install.sh`は、以前`~/.codex/`へ置いたdotfiles向けsymlinkを削除し、空の`hooks/`、`prompts/`、`rules/`も削除する。`~/.codex/config.toml`や`~/.codex/hooks.json`からdotfilesのhookを呼んでいるマシンでは、その配線を手で外す。

## 配置

- `configs/agent/AGENTS.md`
  - `~/.claude/CLAUDE.md`
- `configs/agent/skills/<name>/`
  - `~/.claude/skills/<name>`
- `configs/agent/hooks/*.sh`
  - `~/.claude/hooks/`

`settings.json`などClaude Code本体の設定ファイルは`configs/claude/`に置く。`settings.json`だけはsymlinkせず、`install.sh`が`settings.local.json`と合成して書き出す（[`configuration.md`](configuration.md)を参照）。

## Skill

skillは、作業の種類ごとに必要なときだけ読み込まれる。毎回読み込まれる`AGENTS.md`や記憶には、特定の作業でしか使わない知識を置かず、skillに移す。

- `agents-orchestrator`、`agents-thread`: 小さな窓口（`orchestrator`）の窓口とスレッドの決まり（下の「小さな窓口（orchestrator）」を参照）
- `commit-push`: 未コミットの変更を意図ごとにコミットしてpushする
- `gh-fix-ci`: GitHub ActionsのPR checkの失敗を調べて直す
- `grill-me`: 計画や設計を質問で掘り下げる
- `pr-review-comment`: ほかの人のPRに、1つのpending reviewで行コメントを付ける
- `report-writing`: 上長や関係者に向けた進捗報告・定例の報告資料・報告用の議事録の節を、空雨傘（現状・見立て・ネクストアクション）で書く。付属の`scripts/md_to_gdocs.py`は、Markdownの箇条書きの`- `を`* `に直し（入れ子も、コードブロックと表は変えない）、Google Docsの「Markdownから貼り付け」用にpbcopyでクリップボードに入れる。pbcopyが無ければ標準出力に出す。fishからは`md-gdocs <ファイル>`で呼べる

skillに付けるscriptはskillのディレクトリの中に置き、`~/.claude/skills/<name>/`経由で呼ぶ。テストは`configs/agent/tests/`に置く（`python3 -m unittest configs/agent/tests/test_md_to_gdocs.py`）。

## なぜ個別symlinkか

`~/.claude/skills/`には、別の方法で導入したskillが同居する。ディレクトリ全体をsymlinkせず、dotfiles管理対象だけを個別にlinkする。

`~/.claude/`のhistory、sessions、cacheなどの動的ファイルは管理しない。

## Hookの配線

hook scriptの配置（`configs/agent/hooks/`）と発火設定（`configs/claude/settings.json`）は分ける。

### textlint

`textlint-markdown.sh`はClaude Codeの`PostToolUse`（`Write|Edit`）で、書き込まれた`*.md`をtextlintにかける。指摘があればexit 2でagentへ返し、書き直させる。

- ルール設定とnpm依存: `configs/textlint/`（`~/.config/textlint`へsymlink）
- npm依存のinstall: `install.sh`の`install_textlint`（`npm ci`）
- 未installの機械ではhookは何もしない

`textlint-mcp.sh`はClaude Codeの`PreToolUse`（全MCP tool）で、tool inputのうち本文らしいkey（`body`、`description`、`comment`、`text`など）の日本語をtextlintにかける。指摘があればexit 2で送信を止める。特定のserviceやtool名には依存させない。コードが入る`content`は対象外にする。`AGENTS.md`の「まず.mdに下書きする」ルールを機械的に担保するためのhook。

### 外部送信の確認

`external-post-guard.py`はClaude Codeの`PreToolUse`で、外に出る文面を送る前に確かめる。対象は全MCP toolのうち本文らしいkeyを持つ入力と、`gh pr`・`gh issue`の作成・コメント・編集と`gh api`の本文。

- リンクになっていないチケットID（`ABC-123`）とPR番号（`#123`）があればexit 2で止める。リンクの表示名はIDそのものにする
- 曜日のない日付（`11/4`、`11月4日`、`2026-11-04`）があればexit 2で止める。`11/4(水)`のように日付の直後に曜日を書く
- 通った場合は`permissionDecision: "ask"`を返し、送る前に必ず利用者に文面を確認させる
- 読むだけの`gh api`（GETで本文を持たない呼び出し）は対象にしない
- `gh`はパスで呼んでも（`~/.local/share/gh-ghtkn/bin/gh`）同じに扱う。`settings.json`の`if`は`Bash(*gh *)`にして、パスで呼んだときも発火させる
- いまは`Bash`向けの登録を一時的に外している（確認でたびたび止まるため）。MCP toolへの登録は残している。戻すときは`PreToolUse`の`Bash` matcherの先頭に`{"type": "command", "if": "Bash(*gh *)", "command": "~/.claude/hooks/external-post-guard.py", "timeout": 30}`を足す

テストは`python3 -m unittest configs/agent/tests/test_external_post_guard.py`で実行する。

`textlint-mcp.sh`と同じく、特定のserviceやtool名には依存させない。

### tmuxのサーバーを守る

`tmux-socket-guard.py`はClaude Codeの`PreToolUse`（`Bash`）で、いつも使っているtmuxサーバーを止めるコマンドをexit 2で止める。tmuxの中では環境変数`TMUX`が`TMUX_TMPDIR`より優先されるので、テストで`TMUX_TMPDIR`を変えても本物のサーバーに届く。別のサーバーを確実に選べるのは`-L`と`-S`だけ。

- `-L`も`-S`も付けない`tmux kill-server`は、どのセッションでも止める
- `TMUX_TMPDIR`や`unset TMUX`でサーバーを分けようとしているのに、`-L`も`-S`も付けないtmuxを実行するコマンドも止める
- 見るのはコマンドラインだけで、実行するスクリプトの中のtmuxは見えない

実行ビットに頼らないよう、`settings.json`からは`python3`で呼ぶ。テストは`python3 -m unittest configs/agent/tests/test_tmux_socket_guard.py`で実行する。

## 小さな窓口（orchestrator）

自前のコードをできるだけ持たずに、Claude Codeの`claude --bg`と`claude agents`だけで窓口を組む構成。

- `orchestrator`コマンド（`configs/fish/functions/orchestrator.fish`）: tmux session `orchestrator`を開く。無ければ作る。左のペインで窓口（`claude -n orchestrator`）を`~/hub`（`AGENT_ORCHESTRATOR_HOME`で変更可）で起動し、右のペインで`claude agents`を開く。どちらもauto modeで起動する。起動前に`configs/fish/agent-env.fish`（`~/.config/fish/agent-env.fish`）をsourceし、非対話のfishでは動かないconf.dのmiseとdirenv（allow済みの`.envrc`だけ）の環境と、ghtknの`gh`ラッパー（`~/.local/share/gh-ghtkn/bin`があれば）を取り込む
- `agents-orchestrator`（skill）: 窓口の決まり。起動時に`/agents-orchestrator`で読み込む。窓口は自分では作業せず、依頼ごとに`claude --bg -n <分類>-<対象>-<名前>`でスレッドを起動する。リポジトリを変える作業は、ghqで探したリポジトリで`--worktree <スレッド名>`を付けて起動する（`<repo>/.claude/worktrees/<名前>`、ブランチ`worktree-<名前>`）。リポジトリに紐づかない作業は`~/hub/threads/<スレッド名>/`で起動する。起動したら`notify_when_idle`のSendMessageを送り、終わったスレッドの続きは`--resume`で頼む
- `agents-thread`（skill）: スレッドの決まり。窓口が依頼の先頭に`/agents-thread`を付けて読み込ませる。報告は窓口宛てに3行以内、人に判断を求めるときは必ずAskUserQuestionで止まる。止まったスレッドは`claude agents`の一覧で入力待ちとして上に出るので、ユーザーはそこで選んで答える

`--worktree`の作るworktreeは、どのリポジトリでも`git status`に出ないよう、`configs/git/ignore`で無視する。片付けは`claude rm <id>`で、worktreeも安全なら一緒に消える。

外への送信の確認（`external-post-guard.py`）とtextlintは、`settings.json`のhookなので、窓口でもスレッドでもそのまま動く。送信はいつも確認ダイアログで止まり、一覧で入力待ちになる。

以前の窓口（tmuxのwindowでworkerを動かす`hub`、ダッシュボードの`hub-dash`、`configs/tmux/scripts/agent-hub/`、承認済みの提案を通す`outbox-guard.py`など）は消した。中身はtag `hub-v1-20261104`で見られる（`git show hub-v1-20261104:<path>`か、そのtagからブランチを作る）。
