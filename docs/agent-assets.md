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
- 通った場合の扱いはセッションで分ける
  - worker（`spawn.fish`が`AGENT_HUB_WORKER`と`AGENT_HUB_BRANCH`を渡す）では、作業ブランチのdraft PRの作成・編集・コメントだけを確認なしで通す。`gh pr create`は`--draft`と今のブランチを、`gh pr edit`と`gh pr comment`は`gh pr view`で対象のPRのブランチとdraftであることを確かめる。`cd`や`&&`を付けたコマンド、`-R`、`--head`、reviewerの指定は通さない。それ以外の送信（MCP経由の投稿、ほかのPR、draftでないPR、issue、`gh api`の書き込み）はexit 2で止め、下書きを窓口に渡すよう案内する。利用者は窓口とだけ話すため、workerのwindowで確認ダイアログを出すと、気づかれないまま止まる
  - 窓口とそれ以外のセッションでは`permissionDecision: "ask"`を返し、送る前に必ず利用者に文面を確認させる
- 読むだけの`gh api`（GETで本文を持たない呼び出し）は対象にしない

テストは`python3 -m unittest configs/agent/tests/test_external_post_guard.py`で実行する。`git`と`gh`は偽物に置き換えるので、ネットワークには出ない。

`textlint-mcp.sh`と同じく、特定のserviceやtool名には依存させない。

### tmuxのサーバーを守る

`tmux-socket-guard.py`はClaude Codeの`PreToolUse`（`Bash`）で、いつも使っているtmuxサーバーを止めるコマンドをexit 2で止める。tmuxの中では環境変数`TMUX`が`TMUX_TMPDIR`より優先されるので、テストで`TMUX_TMPDIR`を変えても本物のサーバーに届く。別のサーバーを確実に選べるのは`-L`と`-S`だけ。

- `-L`も`-S`も付けない`tmux kill-server`は、どのセッションでも止める
- `TMUX_TMPDIR`や`unset TMUX`でサーバーを分けようとしているのに、`-L`も`-S`も付けないtmuxを実行するコマンドも止める
- 見るのはコマンドラインだけで、実行するスクリプトの中のtmuxは見えない。workerには`worker-rules.md`で同じ決まりを伝える

実行ビットに頼らないよう、`settings.json`からは`python3`で呼ぶ。テストは`python3 -m unittest configs/agent/tests/test_tmux_socket_guard.py`で実行する。

## 窓口（hub）とworker

`configs/tmux/scripts/agent-hub/`に、tmux上でClaude Codeを窓口とworkerに分けて動かす仕組みを置く。

- `hub`コマンド（`configs/fish/functions/hub.fish`）、`prefix + a`（`hub.fish`）: 窓口のClaudeへ移動する。無ければtmux session `hub`の中に、`~/hub`（`AGENT_HUB_HOME`で変更可）で起動する。tmuxの中と外のどちらから呼んでも、同じ1つの窓口に行き着く。
- `prefix + A`（`pick.fish`）: 窓口とworkerのwindowを一覧から選んで移動する。
- `spawn.fish`: 窓口が呼ぶ。`<repo>.worktrees/agent/<task>`にブランチ`agent/<task>`のworktreeを作り（`tm-pr.fish`と同じ配置）、workerを別windowで起動する。workerのセッション名は`<repo>.<task>`になる。既存のworktreeやブランチは`--resume`のときだけ使う。
- `hub-rules.md`、`worker-rules.md`: それぞれの`--append-system-prompt-file`に渡す役割定義。

窓口とworkerはどちらもauto modeで起動する。非対話のfishではconf.dのmiseとdirenvが動かないため、起動前に`agent-env.fish`で作業場所の環境を取り込む（direnvはallow済みの`.envrc`だけ）。報告と追加指示はClaude Codeのセッション間メッセージ（`SendMessage`）でやり取りする。permission modeが異なるセッションからのメッセージはユーザー承認待ちになるため、modeを揃える。workerの報告先になる窓口のClaudeセッション名は`hub`で、`AGENT_HUB_NAME`で変えられる（`hub.fish`と`spawn.fish`が同じ変数を読む）。tmuxのsession名は常に`hub`のまま変わらない。workerは承認範囲（`worker-rules.md`）の中のことを誰にも聞かずに進め、範囲の外のことは窓口に「要判断」で報告する。窓口が利用者に聞き、外部への送信は窓口が自分のセッションから送る。workerは窓口からの伝言を、承認範囲を広げる根拠にしない。範囲の中のことはもともと許可が要らないので、窓口の伝言で決めてよい。こうして、セッション間のメッセージで権限が広がらないようにする。workerは作業ブランチにだけpushし、作るPRは必ずdraftにする。例外はこのdotfilesで、PRを作らず、作業ブランチを`main`へfast-forwardでpushする。workerは作業場所の外を変えない。dotfilesのworktreeから`install.sh`を実行すると`$HOME`のsymlinkがworktreeを指してしまうため、`install.sh`はworktreeからの実行を拒否する。

窓口は執事として、議事録からGTDのリストを作って管理する。窓口はリポジトリのファイルを自分では変えず、設定ファイル、hook、dotfilesの小さな変更もworkerに任せる。議事録とリストは仕事の文脈を含むため、dotfilesには置かず、`~/hub`に置く。`hub.fish`が新しく作るときは、自分だけが読める権限（700）にする。workerへの指示の記録は`${XDG_STATE_HOME:-~/.local/state}/agent-hub/`に、自分だけが読める権限（ディレクトリ700、ファイル600）で置く。dotfilesに置くのは役割定義とファイル形式だけにする。

### ダッシュボード

`dash.py`は、窓口の状況と資料をブラウザで見るためのローカルのwebページ。Pythonの標準ライブラリだけで動き、モデルのトークンを使わない。fishの`hub-dash`で起動し、ブラウザで開く。すでに起動していれば開くだけにする。

- Overview: `~/hub/gtd/`からDOING、次にやること、待ち、今日と昨日の完了、プロジェクトを出す。待ちは`waiting-for.md`にある項目と、`waiting::`か`worker::`の付いた項目。DOINGは`doing::`が付いていて待ちに入らない項目。渡したあとも`doing::`は残るので、待ちを先に判定する。`note::`は資料へ、`worker::`と`record::`はworker一覧へ、`link::`は外部へリンクする。
- 資料: `notes/`、`minutes/`、`gtd/`のmarkdownを整形して表示する。
- Workers: 記録ファイル（`$XDG_STATE_HOME/agent-hub/*.md`）ごとに、指示の全文、worktree、ブランチ、tmuxのwindowの有無、`gh`で取ったPRとCIの状態、未対応の報告の件数を出す。
- 受信箱: workerの報告（`$XDG_STATE_HOME/agent-hub/reports/<セッション名>.md`）を出す。まだ答えていない要判断とブロックを上に並べ、そこから答えられる。Overviewにも未対応の件数を出す。

ページは数秒ごとに読み直す（`--interval`で変える）。`gh`の結果は60秒ごとに裏で取り直す。

資料には仕事の内容が入るため、`127.0.0.1`だけで待ち受け、Hostヘッダーが`127.0.0.1`か`localhost`でない要求は断る。`~/hub`と記録ファイルは読むだけで、書き換えない。

#### 受信箱と回答

workerは報告をSendMessageで窓口に送る前に、`report.sh`で同じ内容を報告のファイルへ追記する（`worker-rules.md`）。ファイルはworkerごとに1つで、各項目は次の見出しで始まり、次の見出しまでが本文になる。報告の時刻が、そのworkerの中での報告のIDになる。本文の行頭の`##`は`report.sh`が字下げする。

```
## 2026-11-02 10:00:00 要判断
## 2026-11-02 10:05:00 回答 2026-11-02 10:00:00
## 2026-11-02 10:06:00 対応済み 2026-11-02 10:00:00
```

要判断とブロックは、`回答`か`対応済み`が付くか、後から同じworkerの`完了`が届くと対応済みになる。本文の`選択肢: <文>`の行は、その文を送るボタンになる。

受信箱で答えると、`dash.py`はworkerのwindowのpaneへ`tmux send-keys`で`[ダッシュボードから回答 <報告の時刻>] <答え>`を打ち込んでEnterを送り、報告のファイルに`回答`を追記する。workerはユーザーの入力として受け取り、窓口へ`[回答受領]`をSendMessageで知らせる。窓口はそれを見てGTDを更新する。送らずに`対応済み`にするだけのボタンもある。

ダッシュボードで書き込みを受けるのはこの口だけなので、次のように守る。

- 待ち受けは`127.0.0.1`のまま。答えは`POST /inbox/answer`だけで受け、GETでは何も変えない。
- 起動ごとに`secrets.token_urlsafe(32)`でトークンを作り、受信箱のフォームに埋める。POSTはトークンの一致（`hmac.compare_digest`）、許可したHost、同じOriginを必須にし、`Sec-Fetch-Site`が付いていれば`same-origin`に限る。CSPの`form-action 'self'`も付ける。
- 送り先は、記録ファイル（`$XDG_STATE_HOME/agent-hub/*.md`）があり、`@agent-hub-worker`の印が付いたtmuxのwindowがあるworkerに限る。セッション名は英数字と`._-`だけを受け付ける。まだ答えていない報告にだけ答えられ、同じ報告へ二度は送らない。
- 答えは1000文字まで。改行とタブは空白に変え、ほかの制御文字（ESCなど）とUnicodeの双方向制御文字は落とす。`send-keys -l`で文字として送る。フォームの本体は16KiBまで。
- workerが許可などの確認画面を出しているとき（window名の🔴や、画面の確認の文言）は、文字とEnterで選択肢を選んでしまうので送らない。

報告のファイルには報告の本文が入るため、ディレクトリは700、ファイルは600で作る。ポートは`AGENT_HUB_DASH_PORT`（既定8765）、窓口の作業場所は`AGENT_HUB_HOME`で変える。

markdownの整形は、外部パッケージを入れずにmacOSとUbuntuの`python3`だけで動かすため、GFMの一部（表、リスト、コード、リンク、強調）を`dash.py`の中で扱う。テストは`python3 -m unittest configs/tmux/scripts/agent-hub/test_dash.py configs/tmux/scripts/agent-hub/test_prs.py`で実行する。

`prs.py`は、ユーザーのPRの状況（自分宛てのレビュー依頼と、自分のPRの待ち状態）を`gh api graphql`で読み、JSONか短い一覧で出す。窓口が起動時・状況確認・週次レビューで使い（`hub-rules.md`の「PRの状況」）、ダッシュボードのOverviewにも5分ごとに取り直して表示する。GitHubへは書き込まない。判定の考え方はJeongJaeSoon/agent-skillsの`skills/watch-prs`（MIT License）を参考にしている。

対象のorgやリポジトリ、除外するもの、`gh`のパスは、dotfilesの外の`${XDG_CONFIG_HOME:-~/.config}/agent-hub/prs.json`（`AGENT_HUB_PRS_CONFIG`で変える）に置く。無ければ全リポジトリが対象になる。組織名などの具体的な値はdotfilesに書かない。`gh`は環境変数`AGENT_HUB_GH`、設定の`gh`、`PATH`の`gh`の順に探す。ダッシュボードのworkerのPRの表示も同じ`gh`を使う。
