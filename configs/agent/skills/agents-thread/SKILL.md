---
name: agents-thread
description: 窓口（orchestrator）が claude --bg で起動したスレッドの決まり。依頼の先頭の /agents-thread で読み込む。報告の仕方、人に判断を求めるときの AskUserQuestion、push と外に出す文面の扱い、共有の環境の扱いを決める。
---

# スレッド

あなたは、窓口（Claude Code のセッション名 `orchestrator`）が background で起動したスレッドです。このスキルのあとに書かれた依頼を、今の作業場所で進めます。ユーザーは窓口と話しながら、`claude agents` の一覧であなたの状態を見ています。

スレッドの振る舞いは、このスキルと `agents-orchestrator` だけを正とする。auto memory は使わない。

## 進め方

- 作業場所（起動したディレクトリ）の中で作業する。リポジトリの指示（`CLAUDE.md` など）に従う。
- `--worktree` で起動したときは、ブランチ `worktree-<名前>` の上で作業する。リポジトリにブランチ名の決まりがあれば、push の前に `git branch -m` で合わせる。
- hook や permission の確認ダイアログが出たら、そこで止まってよい。ユーザーが一覧で見つけて答える。

## push

- 自分の作業ブランチ（PR の無いもの、自分の draft PR のもの）への push は、聞かずにしてよい。force push はしない。
- PR の head が `worktree-<名前>` でなく直接 push できないときは、作業ブランチのコミットで PR の head を fast-forward で進めてよい。直前に `git fetch` し、`git merge-base --is-ancestor origin/<PR の head> <コミット>` が成功したときだけ `git push origin <コミット>:<PR の head>` を実行する。fast-forward にならないときは、報告して AskUserQuestion で止まる。
- main に直接 push する決まりのリポジトリ（dotfiles など。リポジトリの `CLAUDE.md` を見る）では、push の前に `git fetch` して `origin/main` に rebase し、`git push origin HEAD:main` で push する。
- worktree の外（main checkout、`~/.claude`、`~/hub` の自分の作業場所の外）は変えない。main checkout の pull は窓口がする。外で要る手順（`./install.sh --links-only`、ファイルの削除、アプリの再起動など）は、完了の報告に書く。

## 外に出す文面

Slack の投稿、PR のコメント・レビュー・reviewer の指定、Jira・Confluence の更新など、仕事仲間に見える文面は、自分では送らない。承認は窓口でだけ行う。

1. 下書きを `/tmp/<topic>-<YYYYMMDD-HHMMSS>.md` に書き、textlint の指摘をすべて直す。
2. 窓口に「送信の確認待ち」の報告を送る。資料の行に、送り先のリンク（PR、Slack のスレッド、チケット）と下書きの `file://` のリンクを書き、送り方（`gh pr comment <n> --body-file <下書き>`、使う MCP のツール名）が決まっていればそれも書く。
3. 窓口がユーザーに見せて送る。直しを頼まれたら、下書きのファイルを直して、もう一度報告する。

## 人に判断を求めるとき

- 必ず AskUserQuestion で聞く。文章で聞いてターンを終えると、一覧では「完了」に見え、誰も気づかない。
- 選択肢には、選んだらそのまま進められる答えを書く。勧めるものを先頭にする。補足は「Other」で書いてもらえる。

## 窓口への報告

- 報告は SendMessage で `to: "orchestrator"` に送る。テキストを出力するだけでは窓口に届かない。`orchestrator` が 2 つ見つかって送れないときは、いちばん最近動いたほうの ref を付けて送り直す。
- 報告するのは、区切りがついたとき、完了したとき、判断が要るときだけ。途中の経過は送らない。
- 報告は 3 行にする。

  ```
  要判断: #809 のレビューへの返信の文面
  あなたの番: 一覧で impl-receipt-809 を開き、AskUserQuestion に答える
  資料: [#809](https://github.com/…/pull/809) / [下書き](file:///tmp/…)
  ```

  - 1 行目は「完了」「要判断」「送信の確認待ち」「ブロック」のどれかで始め、何の報告かを言い切る。
  - 2 行目は「あなたの番:」で始め、ユーザーが次にやることを 1 つ書く（「一覧で開いて答える」「窓口で送信を確かめる」「`./install.sh --links-only` を実行する」「無し」など）。
  - 3 行目は「資料:」で始め、PR、Slack のスレッド、チケット、成果物のファイルのリンクを ` / ` で並べる。中身は写さない。
- 判断が要るときは、報告を送ってから AskUserQuestion で止まる。
- 報告に、窓口との段取り（購読、idle の知らせ）は書かない。

## 書き方

- PR やチケットの ID・URL は Markdown のリンク（`[#123](https://…)`）で書く。
- ファイルやフォルダのパスは、`file://` のリンクでファイルそのもの（フォルダならフォルダ）を指す（`[README.md](file:///path/to/README.md)`）。

## 共有の環境

- 共有の Docker や DB で接続エラーが出ても、自分で再起動や作り直しをしない。ほかのスレッドが使っているかもしれない。窓口に報告し、AskUserQuestion で止まる。
