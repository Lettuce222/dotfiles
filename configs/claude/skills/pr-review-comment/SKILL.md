---
name: pr-review-comment
description: GitHub の Pull Request にレビューコメントを送るときに必ず使うスキル。冒頭ラベル付け・suggestion ブロック・pending review としての一括投稿・投稿前のユーザー確認を強制する。「PRレビュー」「コードレビュー」「review コメント」「PR にコメント」「suggestion」「指摘して」「nits」「imo」「LGTM」などのキーワードや、ユーザーが他人の PR をレビューする・指摘を送る・改善提案を伝えたい文脈で必ずトリガーすること。単発コメントの直接投稿(`gh api .../pulls/.../comments` や `gh pr review --comment` の即時 submit)は絶対に行わず、本スキルのフロー(下書き → 確認 → pending → submit)に沿わせる。
---

# PR Review Comment

GitHub の PR に対してレビューコメントを送るための統一フロー。

「単発の即時投稿」は禁止し、**pending review に複数コメントを束ねてからユーザー確認後に submit** する。冒頭ラベルを必須運用にすることで、レビュイーが意図を即座に読み取れる状態を作る。

submit 系の `gh` コマンドは `~/.claude/hooks/pr-review-submit-guard.sh` が PreToolUse で検知して許可ダイアログを強制する（settings.json で配線済み）。skill 側で「確認しました」と詐称しても、submit の瞬間に必ずユーザー操作が要求される。これは仕様であって不具合ではない。

## ラベル（冒頭必須・shields.io バッジで表示）

すべての行コメントの 1 行目を **shields.io の画像バッジ** で始める。Markdown のテキスト `[must]` だと文中の角括弧と区別がつきにくく、レビュイーが流し読みするときに優先度を見落としやすい。視覚的に色で識別できるバッジに統一することで、トーンと緊急度を一瞬で伝える。

参考: <https://qiita.com/ryuken/items/e0214ed97f46183fa3bc>

URL フォーマット: `https://img.shields.io/badge/review-<種別>-<色>.svg`
Markdown: `![review-<種別>](URL)`

| ラベル      | バッジ（Markdown）                                                                                              | 意味                           | 使いどころ                                   |
| ----------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------ | -------------------------------------------- |
| **must**    | `![review-must](https://img.shields.io/badge/review-must-red.svg)`                                              | 必ず直してほしい               | 仕様違反、バグ、セキュリティ問題。連発しない |
| **should**  | `![review-should](https://img.shields.io/badge/review-should-important.svg)`                                    | こうした方がいい（強めの提案） | 設計上の問題、保守性が顕著に下がる箇所       |
| **suggest** | `![review-suggest](https://img.shields.io/badge/review-suggest-success.svg)`                                    | こう書くのはどう？             | 別解の提示。決定権はレビュイー               |
| **imo**     | `![review-imo](https://img.shields.io/badge/review-imo-orange.svg)`                                             | 自分ならこう書く（弱め）       | 好みに近い提案。雑談寄り                     |
| **nits**    | `![review-nits](https://img.shields.io/badge/review-nits-green.svg)`                                            | 細かい指摘                     | typo、命名、フォーマット。無視されても可     |
| **ask**     | `![review-ask](https://img.shields.io/badge/review-ask-yellowgreen.svg)`                                        | 質問                           | 意図確認。指摘ではない                       |
| **discuss** | `![review-discuss](https://img.shields.io/badge/review-discuss-brown.svg)`                                      | 議論したい                     | 正解のない論点。あとで口頭で詰めるのも可     |
| **liked**   | `![review-liked](https://img.shields.io/badge/review-liked-blueviolet.svg)`                                     | いいね                         | 良い書き方の称賛                             |
| **thanks**  | `![review-thanks](https://img.shields.io/badge/review-thanks-yellow.svg)`                                       | ありがとう                     | ついで修正への感謝など                       |
| **sorry**   | `![review-sorry](https://img.shields.io/badge/review-sorry-yellow.svg)`                                         | ごめん                         | 指摘が誤りだったときの撤回                   |

書き方の決まり：

- 1 行目はバッジ画像のみ（または `バッジ + 半角スペース + 短い要約`）。空行を挟んで本文を書く。
- バッジは GitHub のレビューコメントでもインライン画像としてそのまま描画される。
- トーン補助の絵文字は本文側で添える（バッジと並べない方が視線が散らない）。
- 色やスタイルを増やしたい場合は shields.io の URL を組み替えるだけで足りる。新しいラベルを足したら必ずこの表にも追記する。

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
- `body`: `![review-<種別>](shields.io URL) 一行要約\n\n本文…\n\n```suggestion\n…\n```` の構成

### Step 3: 下書きファイルへ書き出し

**必ず一時ファイルに下書きを書き、ユーザーに提示する**。会話内に長文を貼るだけだと、レビュイーが実際に見るレンダリング結果と差が出やすい。

```fish
set draft_path /tmp/pr-review-(gh pr view <PR> --json number -q .number)-(date +%s).md
```

下書きの中身（人間が読む用）：

````markdown
# PR #123 へのレビュー下書き

## 全体コメント（review body）

…

## 行コメント

### src/foo.rb:42

![review-nits](https://img.shields.io/badge/review-nits-green.svg) 変数名の typo

`recieve` → `receive`

```suggestion
def receive_payload(payload)
```
````

### src/bar.rb:88-95

![review-should](https://img.shields.io/badge/review-should-important.svg) N+1 になっています

…

````

提示後に「この内容で pending review を作成します。直したい箇所はありますか?」と尋ねる。**ユーザーが明示的に OK と返すまで先に進まない**。

### Step 4: pending review として一括投稿

ユーザー承認後、`gh api` の `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` を `event` を指定せず（または省略して）呼び出すと **pending state** で作成される。実体は GitHub 上の「Files changed」タブで自分にだけ見える下書きレビュー。

JSON を `--input -` で渡すのが安全（シェル展開で suggestion ブロック内のバッククォートを壊さない）：

```fish
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews \
  --method POST \
  --input /tmp/pr-review-payload-(date +%s).json
````

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
      "body": "![review-nits](https://img.shields.io/badge/review-nits-green.svg) typo です\n\n```suggestion\ndef receive_payload(payload)\n```"
    },
    {
      "path": "src/bar.rb",
      "start_line": 88,
      "line": 95,
      "side": "RIGHT",
      "start_side": "RIGHT",
      "body": "![review-should](https://img.shields.io/badge/review-should-important.svg) N+1 になっています\n\n```suggestion\n…置き換え後の全行…\n```"
    }
  ]
}
````

レスポンスの `id` を控える（submit に必要）。state が `"PENDING"` であることを確認する。

### Step 5: ユーザーに最終確認 → submit

```
pending review を作成しました（review id: 12345678）。
GitHubのFiles changedタブで自分にだけ見える状態です。
このまま submit してよろしいですか? (event: COMMENT / APPROVE / REQUEST_CHANGES)
```

ユーザーから event 種別を含めた明示的な承認を受けたら submit：

```fish
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events \
  --method POST \
  -f event=COMMENT \
  -f body="（任意の追記）"
```

この submit コマンドは hook (`pr-review-submit-guard.sh`) が検知し、settings.json の `defaultMode: "auto"` を上書きして許可ダイアログが出る。ユーザーが許可を押した時点で初めて実行される。

## 禁止事項（hookで静的に縛る対象）

以下は skill 内で生成しない。実行しようとすると hook が `permissionDecision: "ask"` を返し、ユーザー許可を要求する：

- `gh pr review --approve|--request-changes|--comment` の直接実行
- `gh api .../reviews` で `event=APPROVE|COMMENT|REQUEST_CHANGES` を含むペイロード
- `gh api .../reviews/<id>/events`
- `gh api .../pulls/.../comments`（review を介さない単発 line コメント直叩き）

これは「うっかり submit」「会話の流れで Claude が勝手に投稿」を構造的に止めるためのガード。手順通り pending → 確認 → submit を踏めば自然に許可ダイアログで一度確認するだけで済む。

## 例: 良いコメント

````
![review-nits](https://img.shields.io/badge/review-nits-green.svg) typo です

```suggestion
def receive_payload(payload)
```
````

````
![review-should](https://img.shields.io/badge/review-should-important.svg) N+1 になっているので preload してほしい

`User.find_each` で回しながら `user.posts` を参照しているため、ユーザー数 N に対してクエリが O(N) 走ります。

```suggestion
User.includes(:posts).find_each do |user|
  user.posts.each { ... }
end
```
````

```
![review-ask](https://img.shields.io/badge/review-ask-yellowgreen.svg) この early return は元のロジックだと意図が拾いきれてない気がしたんですが、別 PR で扱うべきケースを意識的に外している感じでしょうか?
```

```
![review-discuss](https://img.shields.io/badge/review-discuss-brown.svg) このサービス層を Result 型に寄せるかどうか、別の PR でも話題になっていたので一度ペアで詰めたいです
```

```
![review-liked](https://img.shields.io/badge/review-liked-blueviolet.svg) ここのエラーハンドリング、failure case を全部 enum に倒してくれてるの読みやすくて好きでした
```

## 例: 避けたいコメント

- バッジなし: 「ここ直して」→ 緊急度がわからない
- `![review-must]` の乱発: すべて must だと優先度が消える
- テキストの `[must]` 表記: 過去の運用。今は shield img に統一する（混在すると視覚的なノイズが増える）
- suggestion なしの曖昧な改善案: 「もっといい書き方ありそう」→ レビュイーが手を止めて考える必要が出る。せめて方向性は本文で示す
- review を介さない単発投稿: 個別に通知が飛んで会話が散らかる。pending → 一括 submit に統一する
