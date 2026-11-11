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

- `agents-orchestrator`、`agents-worker`、`agents-watch`: 小さな窓口（`orchestrator`）の窓口、worker、見張りのworkerの決まり（下の「小さな窓口（orchestrator）」を参照）
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

`external-post-guard.py`はClaude Codeの`PreToolUse`で、外に出る文面や操作を実行する前に確かめる。対象は全MCP toolのうち本文らしいkeyを持つ入力と、ghの書き込み（`gh pr`の`create`・`comment`・`review`・`merge`・`ready`・`edit`・`close`・`reopen`、`gh issue`の`create`・`comment`・`edit`・`close`・`reopen`、読むだけでない`gh api`）。

- リンクになっていないチケットID（`ABC-123`）とPR番号（`#123`）があればexit 2で止める。リンクの表示名はIDそのものにする
- 曜日のない日付（`11/4`、`11月4日`、`2026-11-04`）があればexit 2で止める。`11/4(水)`のように日付の直後に曜日を書く
- 通った場合、窓口の承認の記録と一致すれば`permissionDecision: "allow"`を返して記録を消す（下の「承認の記録」を参照）。一致しなければ`"ask"`を返し、利用者に確認させる
- `"ask"`の理由の文には、送り先（ghのコマンド。`--body`で直接渡した本文は`<本文>`に置き換える。MCPはツール名と本文以外の引数）と送る本文（`--body-file`・`-F key=@file`のファイルは中身を読む）を載せ、ダイアログで何が送られるかを見られるようにする。本文は先頭1500文字で切り、切ったことと全体の文字数を書く
- 読むだけの`gh api`（GETで本文を持たない呼び出し）は対象にしない
- コマンドは`&&`・`;`・`|`・改行で分け、`bash -c`・`eval`・`$(…)`の中も見る。`env`や`X=y`を前に付けても同じに扱う。引数の文字列の中に書いたghの文字（`approvals.py add --command 'gh …'`など）は実行ではないので対象にしない
- `gh`はパスで呼んでも（`~/.local/share/gh-ghtkn/bin/gh`）同じに扱う。`settings.json`の`if`は`Bash(*gh *)`にして、パスで呼んだときも発火させる
- 送る前の下書きは`external-post-guard.py --check <file>...`で同じ決まりに当てられる。指摘をファイルごとに標準出力へ出し、指摘があればexit 1、無ければ0、ファイルが無いときは2で終わる。決まりは送り先で変わらない（MarkdownのリンクもSlackのリンクも通す）ので、送り先は渡さない
- ghの書き込みを`settings.json`の`permissions.ask`には書かない。PreToolUse hookの`allow`ではaskのルールを飛ばせず、承認の記録があってもダイアログが出てしまうため。確認はこのhookの`ask`で出す

テストは`python3 -m unittest configs/agent/tests/test_external_post_guard.py configs/agent/tests/test_approvals.py`で実行する。

`textlint-mcp.sh`と同じく、特定のserviceやtool名には依存させない。

### 承認の記録

窓口（`orchestrator`）でユーザーがAskUserQuestionで承認した操作は、確認ダイアログをもう一度出さずに通す。窓口が承認の直後に`approvals.py`で記録を書き、`external-post-guard.py`と`approval-gate.py`が記録と一致する呼び出しにだけ`allow`を返す。workerが実行する操作も、窓口がworker用の記録を書いて通す（下の「workerの確認ダイアログを窓口に回す」を参照）。

- 置き場所: `~/hub/state/approvals/<id>.json`（`AGENT_APPROVALS_DIR`か`AGENT_ORCHESTRATOR_HOME`で変わる）。1操作1件
- 書き方: `python3 ~/.claude/hooks/approvals.py add bash [--worker <worker名>] --command '<コマンド>'`、MCPは`add mcp --tool <ツール名> --params '<本文以外の引数のJSON>' --body-file <下書き> --body-key <本文のkey>`。`list`で今ある記録を出す
- Bashはコマンドの文字列全体（前後の空白を除く）が一致したときだけ通す。`--body-file`、`-F key=@file`、`--input`で読むファイルは、記録したときのsha256と同じであることも確かめる
- MCPはツール名、本文以外のtop-levelの引数（過不足なく）、本文のsha256（前後の空白を除く）が一致したときだけ通す
- 記録は30分（`--ttl`）で切れ、1回使うと消える。切れた記録はhookが見つけたときに消す
- 記録を使えるのは、記録が向けたセッションの呼び出しだけ。hookに渡る`session_id`を`claude agents --json`で引く。`--worker`を付けない記録は、名前が`orchestrator`（`AGENT_ORCHESTRATOR_NAME`）のセッションでだけ使う。`add … --worker <worker名>`の記録は、その名前のbackgroundのセッション（worker）でだけ使う。名前で結ぶので、workerを`--resume`しても使える
- 記録を書けるのは窓口だけ。`approvals.py add`は、呼んだセッション（Claude CodeがBashに渡す`CLAUDE_CODE_SESSION_ID`）が窓口でなければexit 3で断る。Claude Codeの外から実行しても断る。`approval-gate.py`も、窓口以外のセッションが記録を書く呼び出し（`approvals.py … add`、記録の置き場所を含むBash、そこへのWrite・Edit）をdenyする。workerも同じユーザーでファイルを書けるので、これらはうっかりを防ぐ確かめで、悪意のあるプロセスは防げない
- `--worker`の名前は、`claude agents --json --all`にあるworkerの名前でなければ断る。MCPの記録は、本文の無い呼び出し（リアクション、状態の変更）なら`--body-file`を付けずに書け、そのときは本文を持たない呼び出しにだけ一致する
- 名前を変える前の書き方も、移行のあいだは受け付ける。`add`は`--thread`を`--worker`と同じに扱い、記録の`thread`のkeyは`worker`と同じに読む（新しい記録は`worker`で書く）
- 文面の決まり（リンク、曜日）は記録があっても確かめ、違反すればexit 2で止める。このとき記録は消さない
- 不安定さを許す作り: MCPでは`textlint-mcp.sh`と並んで動くので、textlintが止めたときも記録は消えている。そのときは窓口が記録を書き直す。コマンドの書き方が記録と1文字でも違うとダイアログに戻る

### workerの確認ダイアログを窓口に回す

worker（`claude --bg`で起動したbackgroundのセッション）の画面は誰も見ていないので、確認ダイアログが出るとworkerが止まったままになる。`approval-gate.py`は、workerではダイアログの代わりに実行を断り、承認を窓口で聞く流れに乗せる。

- `approval-gate.py permission`: Claude Codeの`PermissionRequest`（全tool）で動く。このeventはダイアログを出す直前にだけ発火するので、hookの`ask`、`permissions.ask`、auto modeがブロックを重ねて確認に戻ったときなど、ダイアログの出どころによらず同じに扱える
  - そのセッション向けの承認の記録と一致すれば`allow`を返し、記録を消す
  - worker（`claude agents --json`で`kind`が`background`、名前が窓口でないもの）なら`deny`を返す。`message`に、止めた操作と、「要判断」で窓口に報告して止まり、承認が届いたら同じコマンドを変えずに実行し直すことを書く
  - 窓口や、窓口と関係ない対話のセッション、`claude agents --json`で引けないセッションでは何も返さず、今までどおりダイアログを出す
- `approval-gate.py pre`: `PreToolUse`（`Bash`、`Write`・`Edit`などの編集、全MCP tool）で動く
  - 窓口以外のセッションが承認の記録を書く呼び出しをdenyする（上の「承認の記録」を参照）
  - そのセッション向けの記録と一致すれば`allow`を返して記録を消す。ダイアログを経ずに断られる操作（auto modeの分類器のブロック）を、承認のあとに通すため。ghの書き込みと本文を持つMCPの呼び出しは`external-post-guard.py`が記録を使うので、ここでは触らない（2つのhookで同じ記録を取り合わないように）
  - 記録が1件も無く、記録を書く呼び出しでもなければ、`claude agents --json`を呼ばずにすぐ終わる
- 流れ: workerが止められる → 「要判断」でコマンドの全文と目的を窓口に報告 → 窓口がAskUserQuestionで聞く → 承認されたら`approvals.py add … --worker <worker名>`で記録を書き、workerに実行し直すよう返す → workerが同じコマンドを実行し、記録と一致する1回だけ通る
- 承認していない操作は今までどおり通らない。記録が無いか一致しなければ、workerではdeny、窓口ではダイアログになる
- docsで決まっていないこと: PreToolUseの`allow`がauto modeの分類器を飛ばすかは書かれていない。飛ばさなければ、承認のあとでも分類器にブロックされ、workerは「ブロック」を報告する。auto modeのブロックは`PermissionRequest`を通らない（Claudeに理由が返るだけ）ので、workerのスキルで「要判断」に回させている

`settings.json`からは`python3`で呼ぶ。テストは`python3 -m unittest configs/agent/tests/test_approvals.py`。

### tmuxのサーバーを守る

`tmux-socket-guard.py`はClaude Codeの`PreToolUse`（`Bash`）で、いつも使っているtmuxサーバーを止めるコマンドをexit 2で止める。tmuxの中では環境変数`TMUX`が`TMUX_TMPDIR`より優先されるので、テストで`TMUX_TMPDIR`を変えても本物のサーバーに届く。別のサーバーを確実に選べるのは`-L`と`-S`だけ。

- `-L`も`-S`も付けない`tmux kill-server`は、どのセッションでも止める
- `TMUX_TMPDIR`や`unset TMUX`でサーバーを分けようとしているのに、`-L`も`-S`も付けないtmuxを実行するコマンドも止める
- 見るのはコマンドラインだけで、実行するスクリプトの中のtmuxは見えない

実行ビットに頼らないよう、`settings.json`からは`python3`で呼ぶ。テストは`python3 -m unittest configs/agent/tests/test_tmux_socket_guard.py`で実行する。

## 小さな窓口（orchestrator）

自前のコードをできるだけ持たずに、Claude Codeの`claude --bg`と`claude agents`だけで窓口を組む構成。

- `orchestrator`コマンド（`configs/fish/functions/orchestrator.fish`）: tmux session `orchestrator`を開く。無ければ作る。左のペインで窓口（`claude -n orchestrator`）を`~/hub`（`AGENT_ORCHESTRATOR_HOME`で変更可）で起動し、右のペインに案件の一覧（下の「案件の一覧」を参照）を開く。案件の一覧の上には、workerの節（いまどのworkerが何をしているか）も出す。窓口はauto modeで起動する。workerとのやりとりは窓口に集約するので、`claude agents`のペインは置かない。案件の一覧のペインは、前からあるsessionでも、無ければ`orchestrator`を実行したときに足す（pane optionの`@orchestrator_role`が`cases`のペインを探す）。前の構成の`claude agents`のペイン（起動コマンドに`claude agents`を含むもの）が残っていれば、`orchestrator`を実行したときに閉じる。起動前に`configs/fish/agent-env.fish`（`~/.config/fish/agent-env.fish`）をsourceし、非対話のfishでは動かないconf.dのmiseとdirenv（allow済みの`.envrc`だけ）の環境と、ghtknの`gh`ラッパー（`~/.local/share/gh-ghtkn/bin`があれば）を取り込む
- `agents-orchestrator`（skill）: 窓口の決まり。起動時に`/agents-orchestrator`で読み込む。窓口は自分では作業せず、依頼ごとに`claude --bg -n <分類>-<対象>-<名前>`でworkerを起動する。リポジトリを変える作業は、ghqで探したリポジトリで`--worktree <worker名>`を付けて起動する（`<repo>/.claude/worktrees/<名前>`、ブランチ`worktree-<名前>`）。リポジトリに紐づかない作業は`~/hub/workers/<worker名>/`で起動する。依頼は「ゴール」「完了の条件」「やってよい範囲」で書き、1つのゴールは1人のworkerに調査から検証まで通しで任せる。起動したら`notify_when_idle`のSendMessageを送り、終わったworkerの続きは`--resume`で頼む。急ぎでないworkerの完了や見張りの知らせは案件のファイルに`未報告`で入れるだけにし、「どうなった？」と聞かれたときに案件ごとにまとめて渡す。すぐに伝えるのは、期日がその日のもの、ユーザーの判断が無いとworkerが止まったままのもの、外に出す操作の承認待ちだけ
- `agents-worker`（skill）: workerの決まり。窓口が依頼の先頭に`/agents-worker`を付けて読み込ませる。報告は窓口宛てに3行（1行目は「完了」「要判断」「送信の確認待ち」「ブロック」、2行目は「あなたの番:」、3行目は「資料:」のリンク）、workerはAskUserQuestionを使わない。人に判断を求めるときは、問いと選択肢（推奨を先頭に、選んだら何をするか）と資料のリンクを付けた「要判断」を窓口に送って止まる。承認が要る実行をhookやauto modeに止められたときも、コマンドの全文と目的を付けた「要判断」を送り、承認が届いたら同じコマンドを実行し直す。それ以外で進めなくなったときは「ブロック」を送って止まる。取り消せる判断は推奨を選んで続け、`report.md`と完了の報告の「決めたこと」にまとめる。「要判断」で止まるのは、外に出す操作、取り消せない操作、依頼の前提が崩れたときだけ
- `agents-thread`（skill）: `agents-worker`の古い名前。名前を変える前に起動したworkerや古い依頼の`/agents-thread`のために残し、読み込んだら`agents-worker`を読み込ませる。動いているworkerが片付いたら消す
- `agents-watch`（skill）: 見張りのworker`chore-hub-watch`の決まり。窓口が起動時に`claude --bg -n chore-hub-watch "/loop 30m /agents-watch"`で起こす。勤務時間（平日9〜19時）だけ、GitHubの名指しのレビュー依頼と自分のPRの動き（CI失敗、変更要求、ほかの人のコメント）、Slackのpublic・privateチャンネルの自分宛てのメンションを読み、新しい出来事だけを、1行ごとに「急ぎ」（期日がその日のもの）か「急ぎでない」を付けて窓口に送る。GitHubとSlackには書き込まない。案件の一覧の解けたWaitingは`cases.py sweep`で消す

窓口の振る舞いは`agents-orchestrator`の表にまとめている。

ペインの構成と、workerがAskUserQuestionを使わないことは`python3 -m unittest configs/agent/tests/test_orchestrator.py`で確かめる。レイアウトは専用のtmuxソケット（`-L`）で組んで見るので、いつものtmuxサーバーには触らない。

- 承認が要る操作: 仕事仲間に見えるもの、社外に出るもの、共有のもの、戻せないものは承認が要る。読むだけ、ローカルで閉じる作業、自分の作業ブランチへのpushは承認なし
- 承認と外に出す文面: workerは下書きや準備までで止まり、窓口が送る。窓口はAskUserQuestionで、送る本文を問いかpreviewに載せて承認をもらい、承認の記録（`approvals.py`）を書いてから実行するので、確認ダイアログは出ない。記録と一致しない操作には、今までどおり`external-post-guard.py`がダイアログを出す。workerは記録を書かない
- 文面の形式の直し: workerは「送信の確認待ち」を報告する前に、下書きをtextlintと`external-post-guard.py --check`に通して直しておく。窓口で送るときに文面のチェックに止められたら、窓口はユーザーに聞かずにworkerへ直しを頼み、直ったものを送る。ユーザーには送った結果だけを伝え、形式の直しのことは伝えない
- 出来事から自動で起動する: 見張りの知らせのうち、承認なしの範囲で済むもの（レビューの下読み、CIの失敗の調査、返信の下書き）は、窓口が聞かずにworkerを起動する。同時に3つまで。起動したことは`~/hub/state/auto-log.md`に1行ずつ残す
- workerの要判断: 窓口がAskUserQuestionでユーザーに聞き、答えをSendMessageでworkerに返す（止まっていれば`--resume`）。窓口は自分で選ばない
- workerの実行の承認: workerでは確認ダイアログを出さず、`approval-gate.py`が代わりに断る。workerはコマンドの全文と目的を付けた「要判断」を窓口に送り、窓口がAskUserQuestionで聞いて、承認されたらそのworker用の承認の記録を書いて返す。workerは同じコマンドを実行し直す。force push、共有のmainへのpush、ファイルの削除など、承認の表で承認が要るものもこの流れに乗せる
- workerのブロック: 窓口は、どのworkerが何で止まったかをユーザーに伝える。止まった操作を代わりに実行しない。確認ダイアログが出たままのworker（`claude agents --json`の`waitingFor`）があれば、hookが動いていないので調べる
- 状況の一覧: `claude agents --json`とworkerの報告を合わせて、「worker」「止まった理由」「あなたの番」「資料」の表にし、案件の一覧（右のペイン）と合わせて、次の行動を1件だけAskUserQuestionで提案する

### 案件の一覧

話題が並ぶと前に頼んだことが流れるので、workerとは別に案件（PRの束や1つの施策）ごとの「TODO」「Waiting」「Later」「資料」を残す。workerを片付けても、宿題は案件に残る。

- 置き場所: `~/hub/state/cases/<案件>.md`（`AGENT_ORCHESTRATOR_HOME`か`AGENT_CASES_DIR`で変わる）。1案件1ファイルのMarkdown。中身は社内の文脈なのでdotfilesには置かない。dotfilesにあるのは形の決まり（`agents-orchestrator`の「案件の一覧」）とスクリプトだけ
- 書く人: 窓口が、依頼を受けたとき、ユーザーの番やWaitingが生まれたとき、workerを片付ける前に書く。見張りは解けたWaitingを消すだけ
- Waitingの項目は` → `のあとに、待ちが解けたらやることを書ける。解けると、そこが「TODO」に移る
- 「TODO」の項目は、先頭に期日`[11/11]`と優先の印`!`を書ける。右のペインはこれで全案件のTODOを急ぐ順に並べる。見出しの次の行の`略称: <短い名前>`は、その一覧で添える案件の印になる
- 3つの節が空になった案件は`done/`に移す（消さない）

`agents-orchestrator`の`scripts/cases.py`は、Pythonの標準ライブラリと`gh`・`claude`だけで動く。サブコマンドは次の3つ。

- `board`: workerの節の下に、全案件の「TODO」を1つにして急ぐ順に番号を付けた一覧と、案件の索引（1案件1行で、見出しとWaiting・Laterの件数）を描く。TODOの項目は先頭の期日（`[11/11]`、年は今日にいちばん近い年とみなす）と優先の印（`!`）で並べ、期日のあるもの（早い順、同じ日なら`!`が先）→`!`のもの→ほか（案件のファイル名の順、案件の中は書いた順）にする。期日は、過ぎたもの・今日・明日を言葉と色で出し、ほかは`11/18（水）`の形で出す。各項目の前に案件の印（見出しの次の行の`略称:`、無ければ見出しを縮めたもの）を出し、案件のファイルへのリンクにする。Waiting・Later・資料は、印か索引の見出しをクリックして開く案件のファイルで見る。入りきらないときは、完了のworker、索引（`案件 N 件`の1行にまとめる）、TODOの2行目から先（1項目1行に切る）、の順に畳み、それでも入らなければ末尾を切る。日付が変わったら描き直す。`--by-case`を付けると、前の表示（案件ごとに全部の節を描く）になる。前の表示は次のとおり。案件の一覧を描き（見出しや区切り線は出さず、workerの節が無ければ1行目から案件を並べる）、ファイルの変化（1秒ごとにmtimeを見る）と端末の大きさの変化で描き直す。fswatchなどに頼らないのでUbuntuでも同じに動く。リンクはOSC 8で出すので、tmuxの`open-link.sh`でクリックして開ける（`file://`のMarkdownはpopupのleaf、ほかのテキストはpopupのnvim、フォルダはFinder）。チケットID（`ABC-123`）は`~/hub/pane.json`の`jira`があればリンクにする。入りきらないときは、資料、Later、待ちが解けたあとの手、の順に畳み、それでも入らなければ末尾を切る。TODOがある案件を上に出す。案件の上に、workerの節（`worker`の1行のあと、1workerを状態の印と名前の1行と、いまの作業の1行で出す）を置く
  - データは5秒ごとの`claude agents --json --all`。backgroundのworkerのうち、確認ダイアログ・窓口の番・動いている・完了のものだけを出す。`stopped`・`failed`などは出さず、出すものが1つも無ければ節ごと出さない。窓口（`AGENT_ORCHESTRATOR_NAME`、既定は`orchestrator`）と見張り（`chore-hub-watch`）は出さない。`claude rm`したworkerは出ない
  - 状態は、確認ダイアログ（`waitingFor`がある）・窓口の番（`state`が`blocked`）・動いている・完了の順に並べる。状態の名前は出さず、名前の左の印と色だけで表す（確認ダイアログと窓口の番はTODOと同じ黄の`⏸`、動いているはWaitingと同じ水色の`⟳`、完了は緑の`✔`）。内容が変わったときだけ、画面を消さず上書きで描き直す。完了のworkerは名前だけを出す。印の凡例は出さない。名前は作業場所（`cwd`）のフォルダへのリンク
  - いまの作業は、`claude agents`に要約の欄が無いので、ジョブの状態ファイル（`~/.claude/jobs/<id>/state.json`、`CLAUDE_CONFIG_DIR`で変わる）から取る。止まったときは`needs`、それ以外は`detail`（Claude Codeが付ける短い要約）。どれも無ければ起動時の依頼（`intent`）の先頭。Claude Codeの内部のファイルなので、読めなければ説明を出さないだけにする
  - 1行に入らなければ末尾を`…`で切る。ペインに入りきらなければ完了のworkerを最初に畳み、それ以外のworkerの節は畳まない
  - `claude agents`が失敗したら、workerの節を「claude agents を読めませんでした」の1行にして、案件はそのまま描く
- `sweep`: Waitingのうち、` → `の前のPRがすべてmerge・close済みの項目を消し、` → `のあとを「TODO」に移す。したことと、残ったPR付きの項目の状態（`reviewDecision`など）をJSON Linesで出す。見張りが30分ごとに実行し、レビュー待ちが解けたかなどの判断は見張りがする
- `resolve <案件> <行の一部>`: 1つの項目を消す。Waitingなら` → `のあとを「TODO」に移す

テストは`python3 -m unittest configs/agent/tests/test_cases.py`で実行する。

`agents-watch`の`scripts/watch.py`は、`gh api graphql`で読むだけのスクリプト。`hours`が`watch-heartbeat`に時刻を書き、窓口は`stale`で見張りの停止に気づく。状態は`~/hub/state/`（`AGENT_ORCHESTRATOR_HOME`か`AGENT_WATCH_STATE`で変わる）に置く。

- `seen.txt`: 知らせ済みの出来事のkey。初回は今あるものを記録し、コメント以外だけを出す
- `events.jsonl`: 知らせた出来事を1行に1つ追記する（`source`、`kind`、`key`、`url`、`title`、`at`）。あとでGTDの受信箱などから読めるよう、形を変えずに追記だけする
- `watch.json`: 設定（無くてよい）。`ignore_authors`（コメントを知らせないbotなど）、`work_days`、`work_start`、`work_end`
- Slackはスクリプトから読めないので、見張りのworkerがbrucke-slackで検索し、`watch.py seen slack`で新しいものだけに絞る

テストは`python3 -m unittest configs/agent/tests/test_agents_watch.py`で実行する。

`--worktree`の作るworktreeは、どのリポジトリでも`git status`に出ないよう、`configs/git/ignore`で無視する。片付けは`claude rm <id>`で、worktreeも安全なら一緒に消える。

外への送信の確認（`external-post-guard.py`）とtextlintは、`settings.json`の設定なので、窓口でもworkerでもそのまま動く。承認の記録で通るのは窓口のセッションだけ。

以前の窓口（tmuxのwindowでworkerを動かす`hub`、ダッシュボードの`hub-dash`、`configs/tmux/scripts/agent-hub/`、承認済みの提案を通す`outbox-guard.py`など）は消した。中身はtag `hub-v1-20261104`で見られる（`git show hub-v1-20261104:<path>`か、そのtagからブランチを作る）。
