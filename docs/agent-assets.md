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
- 通った場合の扱いはセッションで分ける
  - worker（`spawn.fish`が`AGENT_HUB_WORKER`と`AGENT_HUB_BRANCH`を渡す）では、作業ブランチのdraft PRの作成・編集・コメントだけを確認なしで通す。`gh pr create`は`--draft`と今のブランチを、`gh pr edit`と`gh pr comment`は`gh pr view`で対象のPRのブランチとdraftであることを確かめる。`cd`や`&&`を付けたコマンド、`-R`、`--head`、reviewerの指定は通さない。それ以外の送信（MCP経由の投稿、ほかのPR、draftでないPR、issue、`gh api`の書き込み）はexit 2で止め、下書きを窓口に渡すよう案内する。利用者は窓口とだけ話すため、workerのwindowで確認ダイアログを出すと、気づかれないまま止まる
  - 窓口とそれ以外のセッションでは`permissionDecision: "ask"`を返し、送る前に必ず利用者に文面を確認させる。例外は、利用者がペインで承認済みの提案と一致する送信で、`"allow"`を返す（下の「承認済みの提案」を参照）
- 読むだけの`gh api`（GETで本文を持たない呼び出し）は対象にしない
- `gh`はパスで呼んでも（`~/.local/share/gh-ghtkn/bin/gh`）同じに扱う。`settings.json`の`if`は`Bash(*gh *)`にして、パスで呼んだときも発火させる

テストは`python3 -m unittest configs/agent/tests/test_external_post_guard.py`で実行する。`git`と`gh`は偽物に置き換えるので、ネットワークには出ない。

#### 承認済みの提案

窓口は外に送る文面を提案として利用者に出し、利用者はペイン（窓口が作るClaude Codeのmod）の[承認]で承認する。承認のあとに確認ダイアログでもう一度確かめる二度手間をなくすため、承認した提案と文面・送信先がそのまま一致する送信だけを確認なしで通す。

- `${AGENT_HUB_HOME:-~/hub}/outbox/<ID>.md`: 送る本文。窓口が書く
- `<ID>.json`: 送信先。MCPなら`{"tool": "<ツール名>", "input": {<本文以外の引数すべて>}}`、GitHubのPRなら`{"tool": "gh", "repo": "<owner/repo>", "pr": <番号>, "action": "comment"}`（レビューは`review-comment`、`review-approve`、`review-request-changes`）。窓口が書く
- `<ID>.approved`: 承認した時刻のISO 8601文字列。利用者が[承認]を押した時点でペインが書く。モデルは書かない

`external-post-guard.py`は、既存の確かめ（チケットIDと日付）を通った送信のうち、次をすべて満たすものに`"allow"`を返す。

- 本文が`<ID>.md`と一致する（末尾の改行は無視する）。MCPでは本文らしいkeyの値をつないだもの、`gh`では`--body`か`--body-file`の中身
- 送信先が`<ID>.json`と一致する。MCPでは、ツール名と、本文らしいkeyを除いた入力のすべてが一致する。`gh`では`gh pr comment|review <番号> -R <owner/repo>`の形で、本文とレビューの種類のほかに引数がなく、`cd`や`&&`を付けない単独のコマンドに限る。今のブランチでPRを選ぶ呼び出しは対象にしない
- `<ID>.approved`の時刻から30分以内で、`.md`と`.json`が承認のあとに変わっていない

通すときは`<ID>.approved`を`<ID>.sent`に名前を変え、同じ承認で二度送れないようにする。名前の変更は原子的なので、同時に来た2つの呼び出しの片方しか通らない。worker（`AGENT_HUB_WORKER`）では、承認があっても今までどおり止める。

`outbox-guard.py`は`PreToolUse`（`Write|Edit|MultiEdit|NotebookEdit`と`Bash`）で、モデルが承認を自分で作るのを防ぐ。

- outboxの`*.approved`へのWrite・Editをdenyする
- `.approved`を含むBashコマンドと、`outbox`を含みファイルを書き換えるBashコマンド（`touch`、`mv`、`cp`、`tee`、`sed -i`、インタプリタ、リダイレクトなど）をdenyする。文字列での最善の検出で、シェルのあらゆる書き方は防げない。`.md`と`.json`が承認後に変わっていれば通さない確かめと合わせて守る

ほかのhookとの関係:

- `PreToolUse`の複数のhookが違う判定を返したときは、`deny` > `defer` > `ask` > `allow`の順で強いほうが勝つ。exit 2は`allow`より強い。`textlint-mcp.sh`の指摘や、brucke pluginの`ifg-gate.py`が止めれば、こちらの`allow`があっても送られない
- 確認ダイアログを出していたのは`external-post-guard.py`の`"ask"`だった。brucke pluginの`ifg-gate.py`は、Brucke MCPのwriteで、公開範囲を広げる操作に`"ask"`、認証情報らしき文字列に`"deny"`を返す。分類器の判定がつかないときは何も返さずClaude Code本体の権限の判定に任せる。auto modeのメインセッションで分類器が使えず、`brucke:brucke-guardrails`も実行していなければexit 2で止める。何も返さない場合はこちらの`allow`が通る。pluginは変えない
- 承認の印は`PreToolUse`で使い切るので、ほかのhookに止められた送信でも承認は`.sent`になる。Bruckeで送る前に`brucke:brucke-guardrails`を実行しておくよう、`hub-rules.md`に書いている
- `allow`を返しても、`settings.json`のdenyとaskのルールは評価される

テストは`python3 -m unittest configs/agent/tests/test_outbox_approval.py`で実行する。`AGENT_HUB_HOME`を一時ディレクトリに向けるので、本物の`~/hub`には触れない。

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
- `pane/`: 窓口の横に出す状況ペインのmod。`hub.fish`が窓口にだけ読み込む（下の「状況ペイン」を参照）。
- `cleanup.py`: 窓口が呼ぶ。workerのセッション名を受け取り、記録ファイルから元のリポジトリ、worktree、ブランチを読んで片付ける。merge済みかを判定し（dotfilesは`origin/main`の祖先か、それ以外はブランチを含むPRが`MERGED`か）、判定できなければ何も消さずに止まる。続けて、workerのwindow、worktree、手元とリモートのブランチ、記録ファイルを消し、元のリポジトリが既定ブランチできれいなら`git pull --ff-only`する。行ったことを1行ずつ出し、`--dry-run`では予定だけ出す（判定のための`git fetch`は行う）。`--force-unmerged`はmergeされていなくても片付け、リモートのブランチは残す。`--kill-other-windows`はworker以外でそのworktreeを開いているwindowも閉じる。`gh`は`AGENT_HUB_GH`、無ければ`PATH`の`gh`を使う。テストは`python3 -m unittest configs/tmux/scripts/agent-hub/test_cleanup.py`で実行する。gitは一時ディレクトリの本物のリポジトリを、`gh`と`tmux`は偽物を使い、本物のtmuxを使うテストは`-L`で専用のソケットに分ける。
- `hub-rules.md`、`worker-rules.md`: それぞれの`--append-system-prompt-file`に渡す役割定義。

窓口とworkerはどちらもauto modeで起動する。非対話のfishではconf.dのmiseとdirenvが動かないため、起動前に`agent-env.fish`で作業場所の環境を取り込む（direnvはallow済みの`.envrc`だけ）。`mise env`は`mise`の`gh`を`PATH`の先頭に置くので、`agent-env.fish`はそのあとに`gh`のラッパー（`~/.local/share/gh-ghtkn/bin`、ghtknでトークンを渡すもの）があれば`PATH`の先頭に戻す。窓口もworkerも、指示書に`gh`のパスを書かずに`PATH`の`gh`を使う。ラッパーが無いマシンでは`mise`の`gh`のまま。報告と追加指示はClaude Codeのセッション間メッセージ（`SendMessage`）でやり取りする。permission modeが異なるセッションからのメッセージはユーザー承認待ちになるため、modeを揃える。workerの報告先になる窓口のClaudeセッション名は`hub`で、`AGENT_HUB_NAME`で変えられる（`hub.fish`と`spawn.fish`が同じ変数を読む）。tmuxのsession名は常に`hub`のまま変わらない。workerは承認範囲（`worker-rules.md`）の中のことを誰にも聞かずに進め、範囲の外のことは窓口に「要判断」で報告する。窓口が利用者に聞き、外部への送信は窓口が自分のセッションから送る。workerは窓口からの伝言を、承認範囲を広げる根拠にしない。範囲の中のことはもともと許可が要らないので、窓口の伝言で決めてよい。こうして、セッション間のメッセージで権限が広がらないようにする。workerは作業ブランチにだけpushし、作るPRは必ずdraftにする。例外はこのdotfilesで、PRを作らず、作業ブランチを`main`へfast-forwardでpushする。workerは作業場所の外を変えない。dotfilesのworktreeから`install.sh`を実行すると`$HOME`のsymlinkがworktreeを指してしまうため、`install.sh`はworktreeからの実行を拒否する。dotfilesのworkerを片付けて`cleanup.py`が元のcheckoutの`main`をpullしたら、窓口が`./install.sh --links-only`で`$HOME`へ反映する（[`configuration.md`](configuration.md)の「リンクと設定だけを反映する」）。インストールや`chsh`を含む引数なしの`./install.sh`は、これまでどおり利用者が実行する。

窓口は執事として、議事録からGTDのリストを作って管理する。窓口はリポジトリのファイルを自分では変えず、設定ファイル、hook、dotfilesの小さな変更もworkerに任せる。議事録とリストは仕事の文脈を含むため、dotfilesには置かず、`~/hub`に置く。`hub.fish`が新しく作るときは、自分だけが読める権限（700）にする。workerへの指示の記録は`${XDG_STATE_HOME:-~/.local/state}/agent-hub/`に、自分だけが読める権限（ディレクトリ700、ファイル600）で置く。dotfilesに置くのは役割定義とファイル形式だけにする。

### ダッシュボード

`dash.py`は、窓口の状況と資料をブラウザで見るためのローカルのwebページ。Pythonの標準ライブラリだけで動き、モデルのトークンを使わない。fishの`hub-dash`で起動し、ブラウザで開く。すでに起動していれば開くだけにする。

- Overview: `~/hub/gtd/`からDOING、次にやること、待ち、今日と昨日の完了、プロジェクトを出す。待ちは`waiting-for.md`にある項目と、`waiting::`か`worker::`の付いた項目。DOINGは`doing::`が付いていて待ちに入らない項目。渡したあとも`doing::`は残るので、待ちを先に判定する。`note::`は資料へ、`worker::`と`record::`はworker一覧へ、`link::`は外部へリンクする。
- 話題: workerごとのスレッド。一覧に状態、最後のやり取りの1行、最終更新を出し、開くと会話を読める。詳しくは下の「話題」。
- 資料: `notes/`、`minutes/`、`gtd/`のmarkdownを整形して表示する。
- Workers: 記録ファイル（`$XDG_STATE_HOME/agent-hub/*.md`）ごとに、指示の全文、worktree、ブランチ、tmuxのwindowの有無、`gh`で取ったPRとCIの状態、未対応の報告の件数を出す。
- 受信箱: workerの報告（`$XDG_STATE_HOME/agent-hub/reports/<セッション名>.md`）を出す。まだ答えていない要判断とブロックを上に並べ、そこから答えられる。Overviewにも未対応の件数を出す。

ページは数秒ごとに読み直す（`--interval`で変える）。`gh`の結果は60秒ごとに裏で取り直す。

資料には仕事の内容が入るため、`127.0.0.1`だけで待ち受け、Hostヘッダーが`127.0.0.1`か`localhost`でない要求は断る。`~/hub`と記録ファイルは読むだけで、書き換えない。

#### 話題

workerごとのスレッドを、Claude Codeのtranscriptから読んで出す（`topics.py`）。モデルは使わない。

- transcriptの決め方: `claude agents --json`のうち、pidがworkerのtmux paneの`pane_pid`の子孫であるセッションの`sessionId`を使い、`~/.claude/projects/<作業ディレクトリの英数字以外を-にした名前>/<sessionId>.jsonl`を読む。paneが分からなければ、名前と作業ディレクトリが一致するセッションが1つだけのときに使う。セッションが動いていなければ、worktreeのtranscriptのうち`agent-name`がworkerのセッション名と同じで最も新しいものを読む。transcriptは追記された分だけを読み足す。
- 会話: ユーザー、assistant、ほかのセッション（hubなど）からのメッセージをmarkdownで出す。続けて呼んだツールは1つに畳み、失敗した数を添える。thinking、サブエージェント、裏の知らせ（task-notification）、Skillの本文は出さない。
- 状態: 確認画面が出ている、AskUserQuestionなどの答えを待っている、未対応の要判断・ブロックがある、のどれかなら「あなたの返事待ち」。ほかは、未読なら「新しい返答あり」、`claude agents`の`busy`（取れなければwindow名の🟡）なら「進行中」、残りは「完了・待機」。
- 既読: workerの最後の発言（assistantの文章と報告）の時刻を、話題を開いたときに`$XDG_STATE_HOME/agent-hub/dash/seen.json`へ書く。それより新しい発言があれば未読。ほかのサイトからの読み込み（`Sec-Fetch-Site`がcross-siteなど）では既読にしない。
- 返答: 話題の画面の入力欄から、そのworkerのpaneへ`send-keys -l`で送る。受信箱の回答と同じく、記録ファイルとwindowのあるworkerに限り、確認画面が出ていれば送らずに「許可待ち。windowへ移ってください」と出す。前置きは付けず、windowで打ったのと同じ入力になる。
- windowへ移る: `tmux select-window`と`switch-client`で、tmuxのclientをworkerのwindowへ切り替える（clientが1つの前提）。
- 成果物のパス: 会話と報告の中の、`/tmp`、`~/hub`、`AGENT_HUB_OPEN_DIRS`（`:`区切り）の下に実在するパスをボタンにする。押すと、ファイルなら`open -R`でFinderに選んだ状態で、ディレクトリなら`open`で開く（Ubuntuは`xdg-open`でディレクトリを開く）。symlinkを辿ったあとの場所で確かめ、許可したディレクトリの外は開かない。画像（png、jpg、gif、webp）は話題の画面の中にも出す（`GET /topics/file`。同じ制限で、ほかのサイトからは読ませない）。

返答、windowへ移る、パスを開くは、受信箱の回答と同じくPOSTだけで受け、トークン・Host・Origin・`Sec-Fetch-Site`を確かめる。

#### 受信箱と回答

workerは報告をSendMessageで窓口に送る前に、`report.sh`で同じ内容を報告のファイルへ追記する（`worker-rules.md`）。ファイルはworkerごとに1つで、各項目は次の見出しで始まり、次の見出しまでが本文になる。報告の時刻が、そのworkerの中での報告のIDになる。本文の行頭の`##`は`report.sh`が字下げする。

```
## 2026-11-02 10:00:00 要判断
## 2026-11-02 10:05:00 回答 2026-11-02 10:00:00
## 2026-11-02 10:06:00 対応済み 2026-11-02 10:00:00
```

要判断とブロックは、`回答`か`対応済み`が付くか、後から同じworkerの`完了`が届くと対応済みになる。本文の`選択肢: <文>`の行は、その文を送るボタンになる。

受信箱で答えると、`dash.py`はworkerのwindowのpaneへ`tmux send-keys`で`[ダッシュボードから回答 <報告の時刻>] <答え>`を打ち込んでEnterを送り、報告のファイルに`回答`を追記する。workerはユーザーの入力として受け取り、窓口へ`[回答受領]`をSendMessageで知らせる。窓口はそれを見てGTDを更新する。送らずに`対応済み`にするだけのボタンもある。

ダッシュボードで書き込みを受けるのはこの口と話題の口だけなので、次のように守る。

- 待ち受けは`127.0.0.1`のまま。答えは`POST /inbox/answer`だけで受け、GETでは何も変えない（話題の既読の記録を除く）。
- 起動ごとに`secrets.token_urlsafe(32)`でトークンを作り、受信箱のフォームに埋める。POSTはトークンの一致（`hmac.compare_digest`）、許可したHost、同じOriginを必須にし、`Sec-Fetch-Site`が付いていれば`same-origin`に限る。CSPの`form-action 'self'`も付ける。
- 送り先は、記録ファイル（`$XDG_STATE_HOME/agent-hub/*.md`）があり、`@agent-hub-worker`の印が付いたtmuxのwindowがあるworkerに限る。セッション名は英数字と`._-`だけを受け付ける。まだ答えていない報告にだけ答えられ、同じ報告へ二度は送らない。
- 答えは1000文字まで。改行とタブは空白に変え、ほかの制御文字（ESCなど）とUnicodeの双方向制御文字は落とす。`send-keys -l`で文字として送る。フォームの本体は16KiBまで。
- workerが許可などの確認画面を出しているとき（window名の🔴や、画面の確認の文言）は、文字とEnterで選択肢を選んでしまうので送らない。

報告のファイルには報告の本文が入るため、ディレクトリは700、ファイルは600で作る。ポートは`AGENT_HUB_DASH_PORT`（既定8765）、窓口の作業場所は`AGENT_HUB_HOME`で変える。

#### ターミナルから使うコマンド

ブラウザを使わずに、ターミナルのペインなどから同じ集計を読み、報告に答えるためのサブコマンド。HTTPサーバーは起動しない。

- `dash.py status --json [--no-prs]`: 状況を1つのJSONにして標準出力に出し、終わる。中身は次のとおり。
  - `inbox`: まだ答えていない要判断とブロック。worker名、報告の時刻（`ref`。答えるときに使う）、種類、1行目、本文、`選択肢:`の行、workerのwindowが確認画面を出しているか（`dialog`）。
  - `workers`: 記録ファイルのあるworker。window、状態（`busy`・`idle`・`permission`・`no_window`・`unknown`）、GTDの項目、PRとCIの状態。状態は、確認画面なら`permission`、ほかは`claude agents --json`の`status`、取れなければwindow名の🟡🟢から決める。
  - `gtd`: OverviewのDOING、待ち、次にやること（上から10件）と、期限が3日以内か過ぎた未完了の項目。各項目は本文と属性をそのまま持つ。
  - `prs`: `prs.py`の結果のうち、レビュー依頼と、自分のPRで手を打つ必要があるもの（Overviewの「要対応」と同じ）。
  - `generated_at`と`errors`。取れなかった部分は空にし、理由を`errors`に入れる。全体は失敗させない。
- `dash.py answer <worker> <報告の時刻> <答え>`、`dash.py answer <worker> <報告の時刻> --done`: 受信箱と同じく、workerのpaneへ答えを送るか、送らずに対応済みにする。守ることも受信箱と同じ。結果を1行で出し、成功なら終了コード0、断ったら1で終わる。答えの処理は報告のファイルを`flock`で押さえ、ダッシュボードと同時に答えても二度は送らない。

`status`は`gh`を待たずに返す。`gh`の結果は`${XDG_CACHE_HOME:-~/.cache}/agent-hub/status-prs.json`に覚えておき、古ければ（workerのPRは60秒、自分のPRは5分）裏で`dash.py refresh-cache`を起動して取り直す。初めて実行したときや取り直しの途中は、前の結果か空の結果を返す（`prs.pending`）。`--no-prs`ではキャッシュを読まず、取り直しも始めない。

markdownの整形は、外部パッケージを入れずにmacOSとUbuntuの`python3`だけで動かすため、GFMの一部（表、リスト、コード、リンク、強調）を`dash.py`の中で扱う。テストは`python3 -m unittest configs/tmux/scripts/agent-hub/test_dash.py configs/tmux/scripts/agent-hub/test_topics.py configs/tmux/scripts/agent-hub/test_prs.py configs/tmux/scripts/agent-hub/test_notify.py`で実行する。

`prs.py`は、ユーザーのPRの状況（自分宛てのレビュー依頼と、自分のPRの待ち状態）を`gh api graphql`で読み、JSONか短い一覧で出す。窓口が起動時・状況確認・週次レビューで使い（`hub-rules.md`の「PRの状況」）、ダッシュボードのOverviewにも5分ごとに取り直して表示する。GitHubへは書き込まない。判定の考え方はJeongJaeSoon/agent-skillsの`skills/watch-prs`（MIT License）を参考にしている。

対象のorgやリポジトリ、除外するもの、`gh`のパスは、dotfilesの外の`${XDG_CONFIG_HOME:-~/.config}/agent-hub/prs.json`（`AGENT_HUB_PRS_CONFIG`で変える）に置く。無ければ全リポジトリが対象になる。組織名などの具体的な値はdotfilesに書かない。`gh`は環境変数`AGENT_HUB_GH`、設定の`gh`、`PATH`の`gh`の順に探す。ダッシュボードのworkerのPRの表示も同じ`gh`を使う。

`notify.py`は、GitHubで新しい出来事（名指しのレビュー依頼、自分のPRのCI失敗、自分のPRへの人のレビューとコメント、人からの@）が起きるまで待ち、1行1件（種類、repo、番号、タイトル、URLのタブ区切り）で出して終わる。窓口がBashの`run_in_background`で動かし、終わるたびに起こされて`~/hub/proposals.md`に次の行動の提案を足し、また起動する（`hub-rules.md`の「出来事から提案を出す」）。ループは窓口の側にあり、スクリプトは待つあいだモデルのトークンを使わない。終了コードは、出来事を出したら0、`notify_max_minutes`（既定720分）のあいだ何も無ければ1、認証エラーなどが3回続いたり設定が誤っていたりしたら2。5xx・タイムアウト・利用枠の超過は間隔を延ばして待ち直す。

GitHubの通知API（`gh api notifications`）は、ghtknのようなGitHub Appのユーザートークンでは読めない（HTTP 403）。そのため`notify.py`は通知APIを使わず、`prs.py`と同じ`gh api graphql`で自分のPR、レビュー依頼、mentionを`notify_interval_s`（既定60秒）ごとに読み、前に見たものとの差分を出来事にする。この方法には次の制約がある。

- mentionは検索（`mentions:@me`）で更新の新しい20件を取り、その中の直近のコメント（会話は20件、レビューは10件とその中のコメント10件ずつ）だけを調べる。そのため通知より粗く、長いスレッドの奥のコメント、編集で後から足された@、チーム宛ての@は拾わない。
- 自分のPRのレビューとコメントは、PRごとに直近30件ずつを見る。1回の間隔のあいだにそれより多く付くと、古い分は拾えないが、そのPRの出来事としては出る。
- GraphQLの利用枠は、1回の見回りでレビュー依頼・自分のPR・mentionの3つのクエリを使い、合わせて約4ポイント（自分のPRやレビュー依頼が25件を超えるとページの分だけ増える）。既定の60秒間隔なら1時間に約240ポイントで、1時間の上限（ユーザーのトークンで5,000）の5%ほどになる。`prs.py`とダッシュボードも同じ枠を使う。

見たものの記録は`${XDG_STATE_HOME:-~/.local/state}/agent-hub/notify-seen.txt`（キーだけ、ファイルは600）に置く。ファイルが無い初回は、今ある出来事を記録するだけで出さない。設定は`prs.py`と同じ`prs.json`で、対象のorgやリポジトリ、除外、`bots`、`gh`のパスに加えて、`notify_interval_s`と`notify_max_minutes`を使う。考え方はwatch-prsの`scripts/notify.py`（MIT License）を参考にしている。

### 状況ペイン

窓口のClaude Codeの横に、提案・判断待ち・worker・期限・GTD・PRを出すペインを置く。Claude Codeのmod（hooks module）で、名前は`hub-dashboard`。

- 場所: `configs/tmux/scripts/agent-hub/pane/`（`.claude-plugin/plugin.json`、`hooks/`、`types/index.d.ts`、`tests/`）
- 読み込み: `hub.fish`が窓口のclaudeを`--plugin-dir <pane/の場所>`付きで起動する。窓口を起動するたびに読み込まれる。workerには付けない
- 有効になる場所: 起動した場所が`~/hub`のセッションだけ。ほかの場所では`session.start`で何もしない。`AGENT_HUB_HOME`で別の場所を使うと、ペインは出ない
- 開き方: 起動すると自動で開く。閉じたあとは`/gtd-dashboard`で開き直す

中身は描くだけにして、状況は`dash.py status --json`を20秒ごとと、`Write`、`Edit`、`Bash`、`SendMessage`の直後に読み直す。workerへの答えは`dash.py answer`に渡す。

`~/hub`のファイルとの関係:

- `~/hub/proposals.md`: 窓口が1行1件で書く提案（`- [ ] P1 タイトル source:: … plan:: …`）。ペインは読むだけで書き換えない。`[ ]`（未決）を先に、`[>]`（あとで）を後ろに出す。[承認]・[却下]・[あとで]と一言は、窓口への発言として送り、窓口がファイルを書き換える
- `~/hub/outbox/<ID>.md`: 送る文面がある提案で[承認]を押すと、ペインがその時点で`<ID>.approved`を書く。`external-post-guard.py`は、文面と送信先がこの提案と同じときだけ送信を通す（上の「承認済みの提案」を参照）
- `~/hub/pane.json`: `{"jira": "<末尾にチケットのキーを足すURL>"}`。チケットIDをリンクにするのに使う。社内のURLを含むのでdotfilesには置かない。無ければチケットIDはリンクにしない

確かめるときは、`pane/`で次を実行する。

- `claude plugin validate .`: マニフェストとモジュールを読み込みと同じ形で確かめる。マーケットプレイス向けのLICENSEとアイコンの指摘は、配布しないので無視してよい
- `claude plugin test .`: `tests/*.test.ts`（提案の読み取りとリンク化）を実行する
- 型の確かめ: `tsconfig.json`は`.claude-plugin/types/tsconfig.json`を継承する。この型はClaude Codeがmodを読み込んだときに生成する（gitの管理外）。一度窓口を起動してから`npx -p typescript@5 tsc -p .`を実行する
