---
name: pr-review-comment
description: GitHub の Pull Request にレビューコメントを送るときに必ず使うスキル。冒頭ラベル付け・suggestion ブロック・pending review としての一括投稿・本人が GitHub UI で確認してから submit するフローを強制する。「PRレビュー」「コードレビュー」「review コメント」「PR にコメント」「suggestion」「指摘して」「nits」「imo」「LGTM」などのキーワードや、ユーザーが他人の PR をレビューする・指摘を送る・改善提案を伝えたい文脈で必ずトリガーすること。単発コメントの直接投稿(`gh api .../pulls/.../comments` や `gh pr review --comment` の即時 submit)は絶対に行わず、本スキルのフロー(pending として一括投稿 → 本人が GitHub UI で確認 → submit)に沿わせる。
---

# PR Review Comment

GitHub の PR に対してレビューコメントを送るための統一フロー。

「単発の即時投稿」は禁止し、**pending review に複数コメントを束ねて投稿 → 本人が GitHub UI で確認 → submit** という 2 段階フローに統一する。冒頭ラベルを必須運用にすることで、レビュイーが意図を即座に読み取れる状態を作る。

なぜ事前にユーザーへ下書きを提示しないのか: pending review は GitHub 上で **本人にしか見えない** (Files changed タブの自分用下書きレビュー) ため、会話内で長文を貼って事前承認を取るより、**実際に投稿してから本人が GitHub UI で実物を見て判断する** 方が、レンダリングの差分や行ターゲットのズレを早く正確に発見できる。事前確認ステップは冗長で、フィードバックの解像度も下がる。

submit 系の `gh` コマンドは `~/.claude/hooks/pr-review-submit-guard.sh` が PreToolUse で検知して許可ダイアログを強制する（settings.json で配線済み）。skill 側で「確認しました」と詐称しても、submit の瞬間に必ずユーザー操作が要求される。これは仕様であって不具合ではない。

## ラベル（冒頭必須・shields.io バッジで表示）

すべての行コメントの 1 行目を **shields.io の画像バッジ** で始める。Markdown のテキスト `[must]` だと文中の角括弧と区別がつきにくく、レビュイーが流し読みするときに優先度を見落としやすい。視覚的に色で識別できるバッジに統一することで、トーンと緊急度を一瞬で伝える。

参考: <https://qiita.com/ryuken/items/e0214ed97f46183fa3bc>

URL フォーマット: `https://img.shields.io/badge/review-<種別>-<色>.svg`
Markdown: `![review-<種別>](URL)`

| ラベル      | バッジ（Markdown）                                                           | 意味                           | 使いどころ                                   |
| ----------- | ---------------------------------------------------------------------------- | ------------------------------ | -------------------------------------------- |
| **must**    | `![review-must](https://img.shields.io/badge/review-must-red.svg)`           | 必ず直してほしい               | 仕様違反、バグ、セキュリティ問題。連発しない |
| **should**  | `![review-should](https://img.shields.io/badge/review-should-important.svg)` | こうした方がいい（強めの提案） | 設計上の問題、保守性が顕著に下がる箇所       |
| **suggest** | `![review-suggest](https://img.shields.io/badge/review-suggest-success.svg)` | こう書くのはどう？             | 別解の提示。決定権はレビュイー               |
| **imo**     | `![review-imo](https://img.shields.io/badge/review-imo-orange.svg)`          | 自分ならこう書く（弱め）       | 好みに近い提案。雑談寄り                     |
| **nits**    | `![review-nits](https://img.shields.io/badge/review-nits-green.svg)`         | 細かい指摘                     | typo、命名、フォーマット。無視されても可     |
| **ask**     | `![review-ask](https://img.shields.io/badge/review-ask-yellowgreen.svg)`     | 質問                           | 意図確認。指摘ではない                       |
| **discuss** | `![review-discuss](https://img.shields.io/badge/review-discuss-brown.svg)`   | 議論したい                     | 正解のない論点。あとで口頭で詰めるのも可     |
| **liked**   | `![review-liked](https://img.shields.io/badge/review-liked-blueviolet.svg)`  | いいね                         | 良い書き方の称賛                             |
| **thanks**  | `![review-thanks](https://img.shields.io/badge/review-thanks-yellow.svg)`    | ありがとう                     | ついで修正への感謝など                       |
| **sorry**   | `![review-sorry](https://img.shields.io/badge/review-sorry-yellow.svg)`      | ごめん                         | 指摘が誤りだったときの撤回                   |
| **memo**    | `![review-memo](https://img.shields.io/badge/review-memo-lightgrey)`         | 観察メモ（修正要請なし）       | 自分用備忘・気付きの共有。レビュイーに行動を求めない |

書き方の決まり：

- **1 行目はバッジ画像のみ**。要約や本文を同じ行に置かない。空行を挟んで「2 行目に短い要約」、もう一つ空行を挟んで本文の順で書く。3 段構造を崩さない (バッジ単独行 → 空行 → 要約 → 空行 → 本文)。
- バッジは GitHub のレビューコメントでもインライン画像としてそのまま描画される。1 行目に置くことで「見出しチップ」のように視覚的に分離されるため、レビュイーが流し読みするときの判別性が上がる。
- 色やスタイルを増やしたい場合は shields.io の URL を組み替えるだけで足りる。新しいラベルを足したら必ずこの表にも追記する。

## コメント本文のトーン

レビューは「相手の作業を止めて時間をもらう」行為なので、文面で余計な摩擦を生まないようにする。

- **ソースコードを参照するときは GitHub の permalink を貼る** (生テキスト `path:line` で書かない)。レビュイーが該当箇所を 1 クリックで開け、ホバープレビューも効く。SHA は PR の `headRefOid` (Step 1 で控えたもの) を使う。コメント時点の行番号が永続化されるため、後続 commit でファイルが動いても意図が保たれる:
  ```markdown
  既存パターンの [`app/forms/.../uploads_form.rb#L26`](https://github.com/<owner>/<repo>/blob/<headRefOid>/app/forms/.../uploads_form.rb#L26) と整合します
  ```
  範囲指定は `#L80-L92` 形式。
- **shortcode emoji と全角「！」「？」を適度に混ぜて柔らかいトーンに**。指摘・依頼は語尾「〜していただけると嬉しいです」「〜かなと思いました」「〜していただけると助かります」を基本とし、断定で押し切らない。GitHub UI で描画される shortcode の例:
  - `:pray:` (依頼・お願い)
  - `:+1:` (賛意・後押し)
  - `:bow:` (恐縮・低姿勢)
  - `:eyes:` (見落としかも、要確認)
  - `:sparkles:` (改善・きれいになる)
  - `:warning:` (注意喚起・落とし穴)
  - `:sweat_smile:` (恥ずかしいけど指摘、自己ツッコミ)
- **トーン補助の絵文字は本文側で添える**。バッジと同じ行に並べると視線が散るので、バッジ行は単独のまま維持する。
- 過剰に使うとノイズになるので、1 コメントあたり 2〜4 個を目安にする。
- **観察ラベル (`memo` / `liked` / `thanks` / `sorry`) は修正要請の語尾を含めない**。「〜していただけると嬉しいです」「〜書いてほしいです」のような action を促す表現を避け、観察した事実だけを 1〜3 行で書く。理由: これらのラベルはレビュイーに作業を求めるものではなく、行動を促す語尾が混じると意図がぶれて「結局直してほしいのか?」とノイズになる。ユーザーが新規ラベル (skill 既定外) を指定してきたときも、ラベル名から「要請系か観察系か」を判断し、観察系ならこの規約を適用する。

## suggestion ブロック（できる限り使う）

GitHub の suggestion 構文を使うと、レビュイーが「Commit suggestion」ボタン一発で反映できる。**コメント対象の行と差し替える形**になるため、対象範囲の選択と中身の整合が重要。

````
```suggestion
修正後のコード
```
````

注意点：

- suggestion ブロックの内容は、コメントを付けた行（または `start_line` 〜 `line` の範囲）を**まるごと置き換える**。インデント・末尾改行・前後の文脈まで含めて完成形を書く。
- 「ここを足してほしい」だけの場合も、**元の行+追加行** をブロックに入れる（消えてしまうので）。
- 複数行に渡る suggestion は `start_line` と `line` を指定して範囲レビューにする。
- 差し替え不能な指摘（命名相談、設計議論、ファイル全体の話）は無理に suggestion 化しない。`[ask]` `[discuss]` で文章のみ。

## 実行フロー

### Step 1: PR と diff の取得

引数として PR 番号、PR URL、もしくは「現在ブランチの PR」のいずれかを受け取る。

```fish
# PR番号 / URL から
gh pr view <PR> --json number,title,headRefOid,baseRefName,headRepository,headRepositoryOwner,url
gh pr diff <PR>

# 現在ブランチ
gh pr view --json number,title,headRefOid,headRepositoryOwner,headRepository,url
```

`headRefOid` を控えておく（後で `commit_id` として使う）。

### Step 2: コメント候補の作成

diff を読みながら、行単位の指摘を以下の構造で組み立てる：

- `path`: ファイルパス（リポジトリルートから）
- `line`: 右側（新コード側）の行番号。RIGHT が既定
- `start_line`: 複数行に渡る場合の開始行（任意）
- `body`: `![review-<種別>](shields.io URL)\n\n一行要約 :pray:\n\n本文…\n\n```suggestion\n…\n```` の構成 (バッジ単独行 → 空行 → 要約 → 空行 → 本文。要約には `:pray:` 等の shortcode emoji と全角「！」を 1〜2 個添える)

### Step 3: pending review として一括投稿

事前確認を取らずに、組み立てたコメント候補をそのまま pending review として一括投稿する。pending review は GitHub 上で本人にしか見えない下書きなので、この段階での投稿は外部に影響を与えない（= 事前承認を取る意味が薄い）。

`gh api` の `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` を `event` を指定せず（または省略して）呼び出すと **pending state** で作成される。実体は GitHub 上の「Files changed」タブで自分にだけ見える下書きレビュー。

JSON を `--input <file>` で渡すのが安全（シェル展開で suggestion ブロック内のバッククォートを壊さない）：

```fish
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews \
  --method POST \
  --input /tmp/pr-review-payload-(date +%s).json
```

ペイロード（`event` を入れないこと）：

````json
{
  "commit_id": "<headRefOid>",
  "body": "全体コメント（任意）",
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
      "body": "![review-should](https://img.shields.io/badge/review-should-important.svg)\n\nN+1 になっているので preload に寄せたいです :pray:\n\n`User.find_each` で回しながら `user.posts` を参照しているため、ユーザー数 N に対してクエリが O(N) 走ってしまっています。詳細は [`app/models/user.rb#L42`](https://github.com/<owner>/<repo>/blob/<headRefOid>/app/models/user.rb#L42) を参照 :eyes:\n\n```suggestion\n…置き換え後の全行…\n```"
    }
  ]
}
````

レスポンスの `id` を控える（submit と削除/編集に必要）。state が `"PENDING"` であることを確認する。

**下書きファイルも残しておく**: 投稿と同時に、人間が読みやすい Markdown 下書きを `/tmp/pr-review-<PR番号>-<timestamp>.md` にも書き出しておく。これは **ユーザー承認の関門としてではなく、後で編集/削除する際の元データ・チームへの共有資料・トラブル時の復元元** として使う。Step 4 の修正フェーズで「N 番目のコメントを直して」と指示されたときに、ローカルに残しておいた下書きから該当 body を再構築するのが速い。

```fish
set draft_path /tmp/pr-review-(gh pr view <PR> --json number -q .number)-(date +%s).md
```

下書きの中身は、各行コメントを `path:line` 単位で見出し化したもの。

### Step 4: 本人が GitHub UI で確認 → 修正 or submit

投稿が完了したら、レビュー ID と Files changed タブの URL をユーザーに提示し、**会話内ではなく GitHub UI で実物を見て判断してもらう**。会話内で長文を貼って疑似プレビューさせるより、GitHub のレンダリング (suggestion ブロックの diff 表示、行ターゲットの位置、shields.io バッジの実描画) を直接見てもらう方が、ズレや過不足を早く正確に見つけられる。

```
pending review を作成しました。

- review id: 12345678
- 確認 URL: https://github.com/<owner>/<repo>/pull/<PR番号>/files
  (Files changed タブで自分にだけ pending として見えます)

GitHub 上で内容を確認してください。修正が必要な箇所があれば「N 番のコメント直して」「削除して」など、
そのままで OK なら「submit して (event: COMMENT / APPROVE / REQUEST_CHANGES)」と返してください。
```

ユーザーから「修正したい」 と返ってきた場合は **submit せず、review 全体を再構築** して応える:

**重要 (2026-05 時点の挙動)**: GitHub API の `/pulls/comments/{id}` 系エンドポイントは **submit 後のレビューコメントしか対象にしない**。pending state のコメントに対して `PATCH /pulls/comments/{id}` を叩くと **404 Not Found** が返る。同じ理由で `DELETE /pulls/comments/{id}` も pending 状態では動かないと考えるのが安全。pending 中の修正は **review 全体破棄 → 再 POST** が正攻法。

- **pending review 全体の破棄 → 再作成** (推奨パス):

  ```fish
  # 1. 元の review を丸ごと削除
  gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id} --method DELETE

  # 2. 修正後のペイロードで再 POST (Step 3 と同じ)
  gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews \
    --method POST \
    --input /tmp/pr-review-payload-v2.json
  ```

  Step 3 で保存した下書き Markdown と payload JSON を元に、該当 body だけ書き換えて再投稿する。コメント本数が多い場合 (~10 件以上)、`jq` で原 payload を `--slurpfile` 経由でマージするのが楽:

  ```fish
  jq -n --slurpfile orig <orig.json> --slurpfile c1 <revise-1.json> \
    '{commit_id: $orig[0].commit_id, body: $orig[0].body,
      comments: [($orig[0].comments[0] | del(.body)) + {body: $c1[0].body}, ...]}' \
    > <payload-v2.json>
  ```

- **個別コメントの編集 / 削除** (submit **後** のみ):
  submit 済みのレビューコメントは `/pulls/comments/{id}` で個別操作できる。pending 段階では使えない:

  ```fish
  # submit 後のみ動作
  gh api repos/{owner}/{repo}/pulls/comments/{comment_id} \
    --method PATCH -f body="新しい本文"
  gh api repos/{owner}/{repo}/pulls/comments/{comment_id} --method DELETE
  ```

- **pending review にコメント追加** (既存 pending review の上に重ねる場合): pending review は 1 PR につき自分用に 1 つしか持てない仕様なので、追加コメントは `POST /repos/{owner}/{repo}/pulls/{pr_number}/comments` で **同じ pull_request_review_id を指定して** 追加する。`in_reply_to` ではなく `pull_request_review_id` を使うのがポイント:
  ```fish
  gh api repos/{owner}/{repo}/pulls/{pr_number}/comments \
    --method POST \
    --input <payload.json>
  # payload.json で pull_request_review_id を指定する
  ```

これらの編集系コマンドは hook (`pr-review-submit-guard.sh`) の対象になっているケースもあるため、許可ダイアログが出ることがある。出たらユーザーに状況を伝えて許可を仰ぐ。設定上カバーされていない操作で意図せず自動実行されそうな場合は、skill 利用者に hook 設定の見直しを促すこと。

修正後は **再度 GitHub UI で確認するよう案内** し、OK が出たら次の submit ステップへ進む。

### Step 5: submit

ユーザーから event 種別を含めた明示的な承認を受けたら submit：

```fish
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events \
  --method POST \
  -f event=COMMENT \
  -f body="（任意の追記）"
```

この submit コマンドは hook (`pr-review-submit-guard.sh`) が検知し、settings.json の `defaultMode: "auto"` を上書きして許可ダイアログが出る。ユーザーが許可を押した時点で初めて実行される。submit すると pending だったコメントが一斉に公開され、レビュイーに通知が飛ぶ。

## 禁止事項（hookで静的に縛る対象）

以下は skill 内で生成しない。実行しようとすると hook が `permissionDecision: "ask"` を返し、ユーザー許可を要求する：

- `gh pr review --approve|--request-changes|--comment` の直接実行
- `gh api .../reviews` で `event=APPROVE|COMMENT|REQUEST_CHANGES` を含むペイロード
- `gh api .../reviews/<id>/events`
- `gh api .../pulls/.../comments`（review を介さない単発 line コメント直叩き）

これは「うっかり submit」「会話の流れで Claude が勝手に投稿」を構造的に止めるためのガード。手順通り pending 投稿 → 本人が GitHub UI で確認 → submit を踏めば、submit の瞬間に許可ダイアログで一度確認するだけで済む。

## 例: 良いコメント

````
![review-nits](https://img.shields.io/badge/review-nits-green.svg)

typo です :pray:

```suggestion
def receive_payload(payload)
```
````

````
![review-should](https://img.shields.io/badge/review-should-important.svg)

N+1 になっているので preload に寄せていただけると嬉しいです :pray:

`User.find_each` で回しながら `user.posts` を参照しているため、ユーザー数 N に対してクエリが O(N) 走ってしまっています。詳細は [`app/models/user.rb#L42`](https://github.com/<owner>/<repo>/blob/<headRefOid>/app/models/user.rb#L42) を参照 :eyes:

```suggestion
User.includes(:posts).find_each do |user|
  user.posts.each { ... }
end
```
````

```
![review-ask](https://img.shields.io/badge/review-ask-yellowgreen.svg)

この early return は元のロジックだと意図が拾いきれてない気がしたのですが、別 PR で扱うべきケースを意識的に外している感じでしょうか？ :pray:
```

```
![review-discuss](https://img.shields.io/badge/review-discuss-brown.svg)

このサービス層を Result 型に寄せるかどうか、別の PR でも話題になっていたので一度ペアで詰めたいです！ :+1:
```

```
![review-liked](https://img.shields.io/badge/review-liked-blueviolet.svg)

ここのエラーハンドリング、failure case を全部 enum に倒してくれてるの読みやすくて好きでした :+1:
```

## 例: 避けたいコメント

- バッジなし: 「ここ直して」→ 緊急度がわからない
- `![review-must]` の乱発: すべて must だと優先度が消える
- テキストの `[must]` 表記: 過去の運用。今は shield img に統一する（混在すると視覚的なノイズが増える）
- **バッジと要約を同じ行に書く**: `![review-nits](...) typo です` のような形は禁止。バッジは単独行で「見出しチップ」として機能させる。必ず空行を挟む
- **ソースコード参照を生テキスト `path:line` で書く**: レビュイーが追えない。必ず GitHub permalink (`https://github.com/<owner>/<repo>/blob/<headRefOid>/<path>#L<line>`) に変換する
- **断定で押し切る語尾 / emoticon 皆無**: 「〜してください」「〜は間違っています」のみで構成された冷たいコメントは摩擦を生む。`:pray:` `:+1:` `:bow:` や「〜していただけると嬉しいです」を併用する
- suggestion なしの曖昧な改善案: 「もっといい書き方ありそう」→ レビュイーが手を止めて考える必要が出る。せめて方向性は本文で示す
- review を介さない単発投稿: 個別に通知が飛んで会話が散らかる。pending → 一括 submit に統一する
