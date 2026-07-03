---
name: pr-review-comment
description: GitHub の Pull Request にレビューコメントを送るときに必ず使うスキル。冒頭ラベル付け・suggestion ブロック・pending review としての一括投稿・本人が GitHub UI で確認してから submit するフローを強制する。「PRレビュー」「コードレビュー」「review コメント」「PR にコメント」「suggestion」「指摘して」「nits」「imo」「LGTM」などのキーワードや、ユーザーが他人の PR をレビューする・指摘を送る・改善提案を伝えたい文脈で必ずトリガーすること。単発コメントの直接投稿(`gh api .../pulls/.../comments` や `gh pr review --comment` の即時 submit)は絶対に行わず、本スキルのフロー(pending として一括投稿 → 本人が GitHub UI で確認 → submit)に沿わせる。
---

# PR Review Comment

GitHub の PR に対してレビューコメントを送るための統一フロー。

## フロー全体像

以下の 5 ステップを順番に実行する。各ステップの詳細は「実行フロー」セクションにある。

1. **PR と diff の取得** — `gh pr view` / `gh pr diff`。`headRefOid` を控える
2. **コメント候補の作成** — 「コメントの書式」「トーン」「文量」「suggestion ブロック」の各規約に従って組み立てる
3. **pending review として一括投稿** — ユーザーへの事前確認は不要。投稿してよい
4. **ユーザーが GitHub UI で確認** — review ID と URL を提示して待つ。修正依頼が来たら review を作り直す
5. **submit** — ユーザーの明示承認を受けてから実行する

投稿するコメントが 0 件になるケース（指摘なし・最初から approve 依頼）の分岐は Step 2 と Step 5 に定義がある。

単発の即時投稿はせず、**pending review に複数コメントを束ねて投稿 → 本人が GitHub UI で確認 → submit** という 2 段階フローに統一する。

なぜ Step 3 で事前確認を取らないのか: pending review は GitHub 上で **本人にしか見えない** (Files changed タブの自分用下書きレビュー) ため、この段階での投稿は外部に影響を与えない。会話内で長文を貼って事前承認を取るより、実際に投稿してから本人が GitHub UI で実物 (suggestion ブロックの diff 表示、行ターゲットの位置、バッジの実描画) を見て判断する方が、ズレや過不足を早く正確に発見できる。

## ラベル（冒頭必須・shields.io バッジで表示）

すべての行コメントの 1 行目を **shields.io の画像バッジ** で始める。Markdown のテキスト `[must]` だと文中の角括弧と区別がつきにくく、レビュイーが流し読みするときに優先度を見落としやすい。視覚的に色で識別できるバッジに統一することで、トーンと緊急度を一瞬で伝える。

参考: <https://qiita.com/ryuken/items/e0214ed97f46183fa3bc>

URL フォーマット: `https://img.shields.io/badge/review-<種別>-<色>.svg`
Markdown: `![review-<種別>](URL)`

| ラベル      | バッジ（Markdown）                                                           | 意味                           | 使いどころ                                           |
| ----------- | ---------------------------------------------------------------------------- | ------------------------------ | ---------------------------------------------------- |
| **must**    | `![review-must](https://img.shields.io/badge/review-must-red.svg)`           | 必ず直してほしい               | 仕様違反、バグ、セキュリティ問題。連発しない         |
| **should**  | `![review-should](https://img.shields.io/badge/review-should-important.svg)` | こうした方がいい（強めの提案） | 設計上の問題、保守性が顕著に下がる箇所               |
| **suggest** | `![review-suggest](https://img.shields.io/badge/review-suggest-success.svg)` | こう書くのはどう？             | 別解の提示。決定権はレビュイー                       |
| **imo**     | `![review-imo](https://img.shields.io/badge/review-imo-orange.svg)`          | 自分ならこう書く（弱め）       | 好みに近い提案。雑談寄り                             |
| **nits**    | `![review-nits](https://img.shields.io/badge/review-nits-green.svg)`         | 細かい指摘                     | typo、命名、フォーマット。無視されても可             |
| **ask**     | `![review-ask](https://img.shields.io/badge/review-ask-yellowgreen.svg)`     | 質問                           | 意図確認。指摘ではない                               |
| **discuss** | `![review-discuss](https://img.shields.io/badge/review-discuss-brown.svg)`   | 議論したい                     | 正解のない論点。あとで口頭で詰めるのも可             |
| **liked**   | `![review-liked](https://img.shields.io/badge/review-liked-blueviolet.svg)`  | いいね                         | 良い書き方の称賛                                     |
| **thanks**  | `![review-thanks](https://img.shields.io/badge/review-thanks-yellow.svg)`    | ありがとう                     | ついで修正への感謝など                               |
| **sorry**   | `![review-sorry](https://img.shields.io/badge/review-sorry-yellow.svg)`      | ごめん                         | 指摘が誤りだったときの撤回                           |
| **memo**    | `![review-memo](https://img.shields.io/badge/review-memo-lightgrey.svg)`     | 観察メモ（修正要請なし）       | 自分用備忘・気付きの共有。レビュイーに行動を求めない |

新しいラベルを足すときは shields.io の URL を組み替え、必ずこの表にも追記する。ユーザーが表にないラベルを指定してきたときは、ラベル名から「要請系か観察系か」を判断し、観察系なら「トーン」セクションの観察ラベル規約を、要請系なら通常の指摘と同じトーン・文量規約を適用する。

## コメントの書式（正準定義）

各コメントの body は次の 4 段構造で書く。この構造の定義はここが唯一の正準で、他セクションからはここを参照する。

````markdown
![review-<種別>](https://img.shields.io/badge/review-<種別>-<色>.svg)

一行要約 :pray:

本文（1〜3 文）

```suggestion
修正後のコード
```
````

- **1 段目（必須）**: バッジ画像のみの単独行。要約や本文を同じ行に置かない。バッジは GitHub 上でインライン画像として描画され、単独行に置くことで「見出しチップ」のように視覚的に分離される
- **2 段目（必須）**: 一行要約。shortcode emoji を 1〜2 個添える
- **3 段目（省略可）**: 本文 1〜3 文。emoji は 0〜2 個。要約 + suggestion で意図が伝わるなら書かない
- **4 段目（省略可）**: suggestion ブロック。差し替え可能な指摘ならできる限り付ける

各段の間には空行を 1 つ挟む。省略した段は空行ごと詰める（例: 本文なしならバッジ → 空行 → 要約 → 空行 → suggestion）。

## コメント本文のトーン

レビューは「相手の作業を止めて時間をもらう」行為なので、文面で余計な摩擦を生まないようにする。

- **指摘・依頼の語尾は柔らかく**: 「〜していただけると嬉しいです」「〜かなと思いました」「〜していただけると助かります」を基本とし、断定で押し切らない。短文化を優先する場面では「〜したいです」「〜したくて」のような意向表明形も可（`:pray:` を添えて柔らかさを担保する）
- **shortcode emoji と全角「！」「？」を適度に混ぜる**。GitHub UI で描画される shortcode の例:
  - `:pray:` (依頼・お願い)
  - `:+1:` (賛意・後押し)
  - `:bow:` (恐縮・低姿勢)
  - `:eyes:` (見落としかも、要確認)
  - `:sparkles:` (改善・きれいになる)
  - `:warning:` (注意喚起・落とし穴)
  - `:sweat_smile:` (恥ずかしいけど指摘、自己ツッコミ)
- emoji はトーン補助として本文・要約側に添える。バッジ行には置かない（視線が散る）。個数は「コメントの書式」の通り（要約 1〜2、本文 0〜2）
- **ソースコードを参照するときは GitHub の permalink を貼る**: 生テキスト `path:line` だとレビュイーが追えない。`https://github.com/<owner>/<repo>/blob/<headRefOid>/<path>#L<line>` 形式（範囲は `#L80-L92`）に変換する。SHA は Step 1 で控えた `headRefOid`、`<owner>/<repo>` は Step 1 で決めた base リポジトリのものを使う（fork からの PR でも base 側でよい。PR の head commit は base リポジトリの URL 空間から参照できる）。コメント時点の行番号が永続化されるため、後続 commit でファイルが動いても意図が保たれる。「そもそも参照を貼るべきか」は「コメントの文量」の削減基準に従い、本当に有用なときだけ貼る:
  ```markdown
  既存パターンの [`app/forms/.../uploads_form.rb#L26`](https://github.com/<owner>/<repo>/blob/<headRefOid>/app/forms/.../uploads_form.rb#L26) と整合します
  ```
- **観察ラベル (`memo` / `liked` / `thanks` / `sorry`) は観察した事実だけを 1〜3 行で書く**。「〜していただけると嬉しいです」のような行動を促す語尾を混ぜると「結局直してほしいのか?」とノイズになる。これらのラベルはレビュイーに作業を求めないためのもの

## コメントの文量（最重要）

レビューは一往復で終わらせない。**短く書いて返信余地を残す**ことを最優先にする。本文の標準は **1〜3 文**。それ以上書くなら本当にその分量が必要か一度疑う。

なぜか: AI 生成のレビューは「言っていることは全部真っ当だが量が多すぎて読む気が失せる」状態 (いわゆる _AI slop_) に陥りやすい。レビュイーは自分の作業を中断して読みに来ているので、**1 コメントから 1 つの問い・1 つの行動**だけ拾える粒度に削るのがリスペクトの示し方。文章を **長くするのではなく鋭くする** こと。参考: <https://noslopgrenade.com/>

副次効果として、短いコメントは「返信余地」を残す。長文で全部書ききると相手は「了解しました」しか返せないが、1 文の問いかけは対話を促す。レビューは対話であって演説ではない。

### 削る対象

- **レビュイーが既知の概念の解説**: N+1 / race condition / SRP / strong parameters / MVC のような業務知識は、現に書いているコードのレビュー文脈で改めて定義しない。「N+1 です」で足りる。相手はその概念を知っている前提でコードを書いている
- **permalink を貼ったあとの内容要約**: リンクを踏めば読める内容を本文に書き写さない。permalink + 「ここと整合させたいです」の一言で完結させる
- **suggestion ブロックを言葉で再説明する文**: diff を見れば差分は自明。要約だけで意図が伝わるなら本文は省略する。要約自体も「typo です :pray:」「命名整えました :pray:」程度の一行で足りる
- **hedge の重ね打ち**: badge で温度感は伝わっているので、「もしよろしければ」「ちょっとした提案ですが」のような前置きは 1 コメント内に最大 1 つ
- **「結論として」「以上を踏まえると」のような締めくくり**: レビューコメントに結論セクションは要らない
- **逐次的な思考の開示**: 「最初は X かと思ったのですが、よく読むと Y で…」のような推論プロセスは貼らず、**結論だけ**書く

### 長く書いて良い例外

- **設計の論点出し** (`discuss`): 選択肢 A/B/C を整理するとき。冒頭で「詳しく書きます」と一言ことわる
- **背景共有メモ** (`memo`): 後続の読み手向けのコンテキスト残しは、情報密度が高ければ長くてもよい
- **教育的フィードバック**: 新人や初接触の領域に対して意図的にコーチングするとき。冒頭で「詳しめにコメントします」と宣言してから書く

判定は文数ではなく内容で行う。3 文以内でも「削る対象」に該当すれば削る。4 文以上必要なときは冒頭で「詳しく書きます」と宣言する。一度書いたら 1 文ずつ「これを消したらレビュイーの行動が変わるか?」を問い、変わらない文は落とす。

### 削る前後の例

削る前 (AI slop の典型):

````
![review-should](https://img.shields.io/badge/review-should-important.svg)

N+1 になっているので preload に寄せていただけると嬉しいです :pray:

N+1 (関連レコードをループ参照するときに親 1 件 + 子 N 件のクエリが発行されるパターン) になっています。`User.find_each` で回しながら `user.posts` を参照しているため、ユーザー数 N に対してクエリが O(N) 走ってしまっています。これはパフォーマンス上の問題で、ユーザー数が増えるほど顕著になります。`includes` を使うと事前に関連レコードをまとめて取得できるので、クエリ数が一定になります :sparkles:

```suggestion
User.includes(:posts).find_each do |user|
  user.posts.each { ... }
end
```
````

削った後 (推奨):

````
![review-should](https://img.shields.io/badge/review-should-important.svg)

N+1 なので preload に寄せたいです :pray:

```suggestion
User.includes(:posts).find_each do |user|
  user.posts.each { ... }
end
```
````

違い: N+1 の解説 / `includes` の挙動説明 / `:sparkles:` を落とした。レビュイーは Rails を書いている時点で N+1 と `includes` を知っているので、説明は冗長。suggestion ブロックが差分を示すので「こう書いて」も不要。

## suggestion ブロック（できる限り使う）

GitHub の suggestion 構文を使うと、レビュイーが「Commit suggestion」ボタン一発で反映できる。**コメント対象の行と差し替える形**になるため、対象範囲の選択と中身の整合が重要。

````
```suggestion
修正後のコード
```
````

- suggestion ブロックの内容は、コメントを付けた行（または `start_line` 〜 `line` の範囲）を**まるごと置き換える**。インデント・末尾改行・前後の文脈まで含めて完成形を書く
- 「ここを足してほしい」だけの場合も、**元の行 + 追加行** をブロックに入れる（元の行が消えてしまうので）
- 複数行に渡る suggestion は `start_line` と `line` を指定して範囲レビューにする
- 差し替え不能な指摘（命名相談、設計議論、ファイル全体の話）は無理に suggestion 化せず、`ask` / `discuss` ラベルで文章のみにする

## 実行フロー

### Step 1: PR と diff の取得

対象 PR は、ユーザーが PR 番号または PR URL を指定していればそれを使い、指定がなければ現在ブランチの PR を対象とする。

```fish
# PR 番号 / URL から
gh pr view <PR> --json number,title,headRefOid,baseRefName,url
gh pr diff <PR>

# 現在ブランチ（引数なし）
gh pr view --json number,title,headRefOid,baseRefName,url
gh pr diff
```

次の 2 つを控えておく:

- `headRefOid`: Step 3 の `commit_id` と permalink の SHA に使う
- `url`: 以降の全 API コールの `{owner}/{repo}` はここから取る。PR の `url` は `https://github.com/<owner>/<repo>/pull/<番号>` 形式で、この `<owner>/<repo>` が **base リポジトリ**。reviews API は base リポジトリに対して叩くものなので、fork からの PR でも head 側 (fork 側) の owner/repo を使ってはいけない (404 になる)

### Step 2: コメント候補の作成

diff を読みながら、行単位の指摘を以下のフィールドで組み立てる:

- `path`: ファイルパス（リポジトリルートから）
- `line`: 右側（新コード側）の行番号。`side` は `RIGHT` が既定
- `start_line` / `start_side`: 複数行に渡る場合のみ指定
- `body`: 「コメントの書式」セクションの 4 段構造。文量・トーンも各セクションの規約に従う

`line` / `start_line` には **diff に含まれる行**しか指定できない（diff 外の行を指すと投稿時に 422 が返る）。変更されていない行への指摘は、同じファイルの diff 内の近い行に付けるか、レビュー全体コメント（Step 3 payload の `body`）へ回す。それでも 422 が返ったら、エラーメッセージが指す `path` のコメントの行番号を diff 内に修正して再 POST する。

**分岐: diff を読み終えて投稿するコメントが 0 件だった場合**は、Step 3〜4 を実行しない（空の pending review を確認してもらう意味がない）。「指摘はありませんでした。approve などで submit しますか?」とユーザーに報告して指示を待つ。event 種別込みの submit 指示が返ってきたら、`comments` を空配列にした payload で pending review を作成し、Step 5 の submit に直行する。submit しない指示なら何も作成せず終了する。

### Step 3: pending review として一括投稿

ユーザーへの事前確認を取らずに、組み立てたコメント候補をそのまま pending review として一括投稿する（理由は「フロー全体像」参照）。

`POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` を **`event` フィールドを含めずに** 呼ぶと pending state で作成される。JSON は `--input <file>` で渡す（シェル展開で suggestion ブロック内のバッククォートを壊さないため）。

1. payload JSON を一時ディレクトリに `pr-review-payload-<PR番号>-1.json` として Write で書き出す（修正のたびに末尾の連番を増やす）。一時ディレクトリは、セッションで scratchpad ディレクトリが案内されていればそこ、なければ `/tmp`（以降 `<tmpdir>` と表記）。`event` フィールドは入れない。`body`（レビュー全体へのコメント）は、書くことがある場合だけ入れ、なければフィールドごと省略する:

   `body` は JSON 文字列なので通常のエスケープを施す（改行は `\n`、ダブルクォートは `\"`、バックスラッシュは `\\`。suggestion に含まれるコードも同様）:

   ````json
   {
     "commit_id": "<headRefOid>",
     "comments": [
       {
         "path": "src/foo.rb",
         "line": 42,
         "side": "RIGHT",
         "body": "![review-nits](https://img.shields.io/badge/review-nits-green.svg)\n\ntypo です :pray:\n\n```suggestion\ndef receive_payload(payload)\n```"
       },
       {
         "path": "src/bar.rb",
         "start_line": 88,
         "line": 95,
         "side": "RIGHT",
         "start_side": "RIGHT",
         "body": "![review-should](https://img.shields.io/badge/review-should-important.svg)\n\nN+1 なので preload に寄せたいです :pray:\n\n```suggestion\n…置き換え後の全行…\n```"
       }
     ]
   }
   ````

2. 書き出したファイルのパスをそのまま `--input` に渡して投稿する:

   ```fish
   gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews \
     --method POST \
     --input <tmpdir>/pr-review-payload-<PR番号>-1.json
   ```

3. レスポンスの `id` を控え、`state` が `"PENDING"` であることを確認する。`id` は Step 4 の修正（削除→再作成）と Step 5 の submit に必要

4. **payload JSON ファイルは削除せず残す**: Step 4 で修正依頼が来たときの正準の元データになる（人間向けの控えは GitHub UI の pending 表示と payload JSON で足りるので、別ファイルは作らない）

### Step 4: ユーザーが GitHub UI で確認 → 修正 or submit

投稿が完了したら、次の形式でユーザーに提示し、**会話内ではなく GitHub UI で実物を見て判断してもらう**:

```
pending review を作成しました。

- review id: 12345678
- 確認 URL: https://github.com/<owner>/<repo>/pull/<PR番号>/files
  (Files changed タブで自分にだけ pending として見えます)
- コメント一覧（番号指定はこの並びで受けます）:
  1. src/foo.rb:42 — typo 修正の suggestion (nits)
  2. src/bar.rb:88-95 — N+1 の preload 化 (should)

GitHub 上で内容を確認してください。修正が必要な箇所があれば「N 番のコメント直して」「削除して」など、
そのままで OK なら「submit して (event: COMMENT / APPROVE / REQUEST_CHANGES)」と返してください。
```

コメント一覧は payload の `comments` 配列の順に、`path:line — 一行の内容要約 (ラベル)` の形式で列挙する。番号の解釈ズレ（ユーザーが GitHub UI の表示順で数える等）をここで防ぐ。

提示したらユーザーの返答を待つ。返答なしに Step 5 へ進まない。

#### 修正依頼が来た場合: review 全体を破棄して再作成する

**重要 (2026-05 時点の GitHub API の挙動)**: `/pulls/comments/{id}` 系エンドポイント（PATCH / DELETE）は **submit 後のレビューコメントしか対象にしない**。pending state のコメントに叩くと 404 Not Found が返る。pending 中の修正は **review 全体破棄 → 再 POST** が正攻法。

手順:

1. ユーザーの指示に該当するコメントを特定する。「N 番目のコメント」は Step 4 で提示したコメント一覧（= payload JSON の `comments` 配列）の上から N 番目（1 始まり）と解釈する。指示が配列内の 1 コメントに一意に対応付けられない場合のみ、`path:line` を挙げて「この typo 指摘のコメントですか?」と確認する（一意に決まるなら確認せず進める）
2. **最新の連番の payload JSON** を、連番を 1 増やした別ファイルにコピーしてから修正を反映する（例: 2 回目の修正なら `-2.json` → `-3.json`。過去のファイルは復元用に残す）。表現の修正なら該当 body を書き換え、削除依頼なら該当要素を `comments` 配列から取り除く。削除の結果コメントが 0 件になる場合は、review の DELETE だけ行い再 POST はせず、その旨をユーザーに報告する（その後 submit 指示が来たら Step 5 の 0 件分岐に合流する）（その後 submit を依頼されたら Step 5 の 0 件例外に合流する）
3. 元の review を削除し、修正版で再 POST する:

   ```fish
   # 1. 元の review を丸ごと削除
   gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id} --method DELETE

   # 2. 修正版 payload で再 POST (Step 3 と同じコマンド)
   gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews \
     --method POST \
     --input <tmpdir>/pr-review-payload-<PR番号>-2.json
   ```

4. 実行後の報告では、修正・削除した対象コメントの `path:line` と要約を明記する（ユーザーが番号を GitHub UI の表示順で数えていた場合など、対象の取り違えにここで気付けるようにするため）。新しい review `id` を控え直し、再度 GitHub UI で確認するよう案内する。OK が出たら Step 5 へ

この DELETE と再 POST（`event` なし）は次セクションの禁止事項に該当しない。もし環境の hook が許可ダイアログを出したら、修正フローの一部であることをユーザーに伝えて許可を仰ぐ。

補助知識（必要になったときだけ使う）:

- **submit 後の個別編集/削除**: `gh api repos/{owner}/{repo}/pulls/comments/{comment_id} --method PATCH -f body="新しい本文"`（DELETE も同様）。pending 段階では使えない
- **既存 pending review へのコメント追加**: pending review は 1 PR につき自分用に 1 つしか持てないため、追加は `POST /repos/{owner}/{repo}/pulls/{pr_number}/comments` で payload に **`pull_request_review_id`** を指定する（`in_reply_to` ではない）。ただしこのエンドポイントは禁止事項の対象と重なるので、許可ダイアログが出たら状況を説明して許可を仰ぐ

### Step 5: submit

ユーザーから **event 種別 (COMMENT / APPROVE / REQUEST_CHANGES) を含めた明示的な承認** を受けたら submit する。`event` にはユーザーが指定した種別を入れる（例: 「approve で submit して」→ `event=APPROVE`）。`body` は全体への追記がある場合だけ付け、なければ `-f body=...` ごと省略する:

```fish
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events \
  --method POST \
  -f event=COMMENT \
  -f body="（任意の追記。なければこの行ごと省略）"
```

環境によっては submit ガードの hook が設定されており、このコマンドに許可ダイアログが出る。hook の有無に関わらず「ユーザーの明示承認を受けてから実行する」という手順は変わらない。submit すると pending だったコメントが一斉に公開され、レビュイーに通知が飛ぶ。

**例外: 投稿するコメントが 0 件の submit**。確認対象のコメントが存在しないため、Step 4 の確認待ちは不要。次の 2 パターンとも、`comments` を空配列にした payload で pending review を作成してから、この submit コマンドを実行する:

- ユーザーが自分の判断で最初から event 種別込みの submit を依頼してきた場合（例: 「この PR、LGTM なので approve で submit して」）。ユーザー自身がレビュー済みなので、こちらで diff を読み直す必要はない。Step 1 は PR の特定（`url` と `pr_number` の取得）だけ行い、Step 2〜4 は飛ばす
- 自分で diff をレビューして指摘 0 件だった場合。Step 2 の 0 件分岐に従い、ユーザーから event 種別込みの指示を受けてからここに来る

## 禁止事項

以下はこのスキル内で生成しない（submit ガードの hook が設定されている環境では、実行しようとすると hook がユーザー許可を要求する）:

- `gh pr review --approve|--request-changes|--comment` の直接実行
- `gh api .../reviews` で `event=APPROVE|COMMENT|REQUEST_CHANGES` を含むペイロード
- `gh api .../reviews/<id>/events`（Step 5 の正規 submit もこれに該当する。実行前にユーザーの明示承認が必須）
- `gh api .../pulls/.../comments` の単発直叩き（review を介さない line コメント。個別に通知が飛んで会話が散らかる）

これは「うっかり submit」「会話の流れで勝手に投稿」を止めるためのガード。手順通り pending 投稿 → 本人が GitHub UI で確認 → submit を踏めば、外部に公開されるのは承認済みの submit 一回だけになる。

## 例: 良いコメント

本文なし（badge + 要約 + suggestion で完結）:

````
![review-nits](https://img.shields.io/badge/review-nits-green.svg)

typo です :pray:

```suggestion
def receive_payload(payload)
```
````

クロスリファレンスが本当に有用な場合だけ permalink を 1 行添える（例: 直前の PR で同じ箇所を直したばかりで整合させたい等。「念のため」「ご参考まで」で貼らない）:

````
![review-should](https://img.shields.io/badge/review-should-important.svg)

命名を [`app/models/user.rb#L42`](https://github.com/<owner>/<repo>/blob/<headRefOid>/app/models/user.rb#L42) と揃えたいです :pray:

```suggestion
User.includes(:posts).find_each do |user|
  user.posts.each { ... }
end
```
````

suggestion 化できない質問・議論（文章のみ）:

```
![review-ask](https://img.shields.io/badge/review-ask-yellowgreen.svg)

この early return は元のロジックだと意図が拾いきれてない気がしたのですが、別 PR で扱うべきケースを意識的に外している感じでしょうか？ :pray:
```

```
![review-discuss](https://img.shields.io/badge/review-discuss-brown.svg)

このサービス層を Result 型に寄せるかどうか、別の PR でも話題になっていたので一度ペアで詰めたいです！ :+1:
```

観察ラベル（行動を求める語尾を含めない）:

```
![review-liked](https://img.shields.io/badge/review-liked-blueviolet.svg)

ここのエラーハンドリング、failure case を全部 enum に倒してくれてるの読みやすくて好きでした :+1:
```

## 例: 避けたいコメント

- バッジなし・バッジと要約の同一行書き: 「コメントの書式」の 4 段構造が正準。バッジは必ず単独行
- `must` の乱発: すべて must だと優先度が消える
- テキストの `[must]` 表記: 過去の運用。今は shields.io バッジに統一する
- 生テキスト `path:line` でのコード参照: 「トーン」セクションの permalink 規約に従う
- 断定語尾のみ・emoji 皆無の冷たいコメント: 「トーン」セクションに従う
- suggestion なしの曖昧な改善案（「もっといい書き方ありそう」）: レビュイーが手を止めて考える必要が出る。せめて方向性は本文で示す
- AI slop 化した長文: 「コメントの文量」セクションの削減基準と例が正準
