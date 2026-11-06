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

skillは、作業の種類ごとに必要なときだけ読み込まれる。毎回読み込まれる`AGENTS.md`には、特定の作業でしか使わない知識を置かず、skillに移す。

Claude Codeのauto memoryは`settings.json`の`autoMemoryEnabled: false`で止めている。覚えさせたい振る舞いは、memoryではなくskill、`AGENTS.md`、リポジトリの`CLAUDE.md`に書く。memoryは決まりと食い違っても気づきにくいため。

- `agents-orchestrator`、`agents-thread`、`agents-watch`: 小さな窓口（`orchestrator`）の窓口、スレッド、見張りのスレッドの決まり（下の「小さな窓口（orchestrator）」を参照）
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
- 代わりに、`settings.json`の`permissions.ask`で、gh の書き込み（`gh pr create`・`comment`・`review`・`merge`・`ready`・`edit`・`close`、`gh issue`の作成・コメント・編集、`gh api`の`-X`/`--method`での書き込み・`body=`の付いた呼び出し・`--input`・graphqlの`mutation`）に確認ダイアログを出す。auto modeでもaskのルールは必ず確認を出し、`&&`などでつないだコマンドの中でも一致する。パスで呼んだとき用に`*/gh …`も並べている。文字列の一致なので、`gh api`の書き込みのすべてを捕まえられるわけではない

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

- `orchestrator`コマンド（`configs/fish/functions/orchestrator.fish`）: tmux session `orchestrator`を開く。無ければ作る。左のペインで窓口（`claude -n orchestrator`）を`~/hub`（`AGENT_ORCHESTRATOR_HOME`で変更可）で起動し、右のペインに案件の一覧（下の「案件の一覧」を参照）を開く。窓口はauto modeで起動する。スレッドとのやりとりは窓口に集約するので、`claude agents`のペインは置かない。案件の一覧のペインは、前からあるsessionでも、無ければ`orchestrator`を実行したときに足す（pane optionの`@orchestrator_role`が`cases`のペインを探す）。前の構成の`claude agents`のペイン（起動コマンドに`claude agents`を含むもの）が残っていれば、`orchestrator`を実行したときに閉じる。起動前に`configs/fish/agent-env.fish`（`~/.config/fish/agent-env.fish`）をsourceし、非対話のfishでは動かないconf.dのmiseとdirenv（allow済みの`.envrc`だけ）の環境と、ghtknの`gh`ラッパー（`~/.local/share/gh-ghtkn/bin`があれば）を取り込む
- `agents-orchestrator`（skill）: 窓口の決まり。起動時に`/agents-orchestrator`で読み込む。窓口は自分では作業せず、依頼ごとに`claude --bg -n <分類>-<対象>-<名前>`でスレッドを起動する。リポジトリを変える作業は、ghqで探したリポジトリで`--worktree <スレッド名>`を付けて起動する（`<repo>/.claude/worktrees/<名前>`、ブランチ`worktree-<名前>`）。リポジトリに紐づかない作業は`~/hub/threads/<スレッド名>/`で起動する。起動したら`notify_when_idle`のSendMessageを送り、終わったスレッドの続きは`--resume`で頼む
- `agents-thread`（skill）: スレッドの決まり。窓口が依頼の先頭に`/agents-thread`を付けて読み込ませる。報告は窓口宛てに3行（1行目は「完了」「要判断」「送信の確認待ち」「ブロック」、2行目は「あなたの番:」、3行目は「資料:」のリンク）、スレッドはAskUserQuestionを使わない。人に判断を求めるときは、問いと選択肢（推奨を先頭に、選んだら何をするか）と資料のリンクを付けた「要判断」を窓口に送って止まる。確認ダイアログやauto modeのブロックで進めなくなったときは「ブロック」を送って止まる
- `agents-watch`（skill）: 見張りのスレッド`chore-hub-watch`の決まり。窓口が起動時に`claude --bg -n chore-hub-watch "/loop 30m /agents-watch"`で起こす。勤務時間（平日9〜19時）だけ、GitHubの名指しのレビュー依頼と自分のPRの動き（CI失敗、変更要求、ほかの人のコメント）、Slackのpublic・privateチャンネルの自分宛てのメンションを読み、新しい出来事だけを窓口に送る。GitHubとSlackには書き込まない。案件の一覧の解けたWaitingは`cases.py sweep`で消す

窓口の振る舞いは`agents-orchestrator`の表にまとめている。

ペインの構成と、スレッドがAskUserQuestionを使わないことは`python3 -m unittest configs/agent/tests/test_orchestrator.py`で確かめる。レイアウトは専用のtmuxソケット（`-L`）で組んで見るので、いつものtmuxサーバーには触らない。

- 承認が要る操作: 仕事仲間に見えるもの、社外に出るもの、共有のもの、戻せないものは承認が要る。読むだけ、ローカルで閉じる作業、自分の作業ブランチへのpushは承認なし
- 外に出す文面: スレッドは下書きまでで止まり、窓口が送る。送る直前の確認ダイアログ（MCPは`external-post-guard.py`、ghは`permissions.ask`）を承認とする
- 出来事から自動で起動する: 見張りの知らせのうち、承認なしの範囲で済むもの（レビューの下読み、CIの失敗の調査、返信の下書き）は、窓口が聞かずにスレッドを起動する。同時に3つまで。起動したことは`~/hub/state/auto-log.md`に1行ずつ残す
- スレッドの要判断: 窓口がAskUserQuestionでユーザーに聞き、答えをSendMessageでスレッドに返す（止まっていれば`--resume`）。窓口は自分で選ばない
- スレッドのブロック: 窓口は、どのスレッドが何で止まったかをユーザーに伝える。止まった操作を代わりに実行しない。確認ダイアログが出たままのスレッドは`claude agents --json`の`waitingFor`で気づき、ユーザーに`claude agents`でそのスレッドを開いて答えてもらう
- 状況の一覧: `claude agents --json`とスレッドの報告を合わせて、「スレッド」「止まった理由」「あなたの番」「資料」の表にし、案件の一覧（右のペイン）と合わせて、次の行動を1件だけAskUserQuestionで提案する

### 案件の一覧

話題が並ぶと前に頼んだことが流れるので、スレッドとは別に案件（PRの束や1つの施策）ごとの「TODO」「Waiting」「Later」「資料」を残す。スレッドを片付けても、宿題は案件に残る。

- 置き場所: `~/hub/state/cases/<案件>.md`（`AGENT_ORCHESTRATOR_HOME`か`AGENT_CASES_DIR`で変わる）。1案件1ファイルのMarkdown。中身は社内の文脈なのでdotfilesには置かない。dotfilesにあるのは形の決まり（`agents-orchestrator`の「案件の一覧」）とスクリプトだけ
- 書く人: 窓口が、依頼を受けたとき、ユーザーの番やWaitingが生まれたとき、スレッドを片付ける前に書く。見張りは解けたWaitingを消すだけ
- Waitingの項目は` → `のあとに、待ちが解けたらやることを書ける。解けると、そこが「TODO」に移る
- 3つの節が空になった案件は`done/`に移す（消さない）

`agents-orchestrator`の`scripts/cases.py`は、Pythonの標準ライブラリと`gh`だけで動く。サブコマンドは次の3つ。

- `board`: 案件の一覧を描き、ファイルの変化（1秒ごとにmtimeを見る）と端末の大きさの変化で描き直す。fswatchなどに頼らないのでUbuntuでも同じに動く。リンクはOSC 8で出すので、tmuxの`open-link.sh`でクリックして開ける（`file://`はpopupのnvim）。チケットID（`ABC-123`）は`~/hub/pane.json`の`jira`があればリンクにする。入りきらないときは、資料、Later、待ちが解けたあとの手、の順に畳み、それでも入らなければ末尾を切る。TODOがある案件を上に出す
- `sweep`: Waitingのうち、` → `の前のPRがすべてmerge・close済みの項目を消し、` → `のあとを「TODO」に移す。したことと、残ったPR付きの項目の状態（`reviewDecision`など）をJSON Linesで出す。見張りが30分ごとに実行し、レビュー待ちが解けたかなどの判断は見張りがする
- `resolve <案件> <行の一部>`: 1つの項目を消す。Waitingなら` → `のあとを「TODO」に移す

テストは`python3 -m unittest configs/agent/tests/test_cases.py`で実行する。

`agents-watch`の`scripts/watch.py`は、`gh api graphql`で読むだけのスクリプト。状態は`~/hub/state/`（`AGENT_ORCHESTRATOR_HOME`か`AGENT_WATCH_STATE`で変わる）に置く。

- `seen.txt`: 知らせ済みの出来事のkey。初回は今あるものを記録し、コメント以外だけを出す
- `events.jsonl`: 知らせた出来事を1行に1つ追記する（`source`、`kind`、`key`、`url`、`title`、`at`）。あとでGTDの受信箱などから読めるよう、形を変えずに追記だけする
- `watch.json`: 設定（無くてよい）。`ignore_authors`（コメントを知らせないbotなど）、`work_days`、`work_start`、`work_end`
- Slackはスクリプトから読めないので、見張りのスレッドがbrucke-slackで検索し、`watch.py seen slack`で新しいものだけに絞る

テストは`python3 -m unittest configs/agent/tests/test_agents_watch.py`で実行する。

`--worktree`の作るworktreeは、どのリポジトリでも`git status`に出ないよう、`configs/git/ignore`で無視する。片付けは`claude rm <id>`で、worktreeも安全なら一緒に消える。

外への送信の確認（`external-post-guard.py`、`permissions.ask`）とtextlintは、`settings.json`の設定なので、窓口でもスレッドでもそのまま動く。

以前の窓口（tmuxのwindowでworkerを動かす`hub`、ダッシュボードの`hub-dash`、`configs/tmux/scripts/agent-hub/`、承認済みの提案を通す`outbox-guard.py`など）は消した。中身はtag `hub-v1-20261104`で見られる（`git show hub-v1-20261104:<path>`か、そのtagからブランチを作る）。
