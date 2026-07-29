---
name: commit-push
description: ローカルの未コミット変更を意図ごとに整理し、Conventional Commits形式でコミットして安全にpushする。コミットだけ行う場合は `--no-push` を受け付ける。
---

# Commit Push

Claude と Codex のどちらでも使える、通常の commit / push の共通契約。
変更を読み解き、レビュー可能な単位に分けて履歴へ残す。

## インターフェース

- 既定: commit 後に通常の push を行う
- `--no-push`: commit までで終了する
- ユーザーが対象ファイル、commit 数、メッセージを指定した場合はその意図を優先する

stacked PR、専門的なレビュー連携、CI 監視、複数ブランチの公開フローは、
利用可能なら `code-flow` Plugin に委ねる。この Skill は通常の Git 操作に集中する。

## ワークフロー

### 1. 状態を把握する

次を確認し、ユーザーの変更と今回の対象を区別する。

- `git status --short`
- `git diff` と `git diff --staged`
- 最近の `git log --oneline`
- 現在の branch、upstream、ahead / behind

変更がなければ終了する。未解決 conflict や意図不明の大きな混在があれば、
安全に切り分けられる情報を示して確認する。

### 2. コミット単位を設計する

同じ目的を持ち、単独でレビュー・revert できる変更をまとめる。
実装とそのテスト、設定と対応ドキュメントなど、分離すると不完全になるものは同じ
commit に含める。無関係な整形やユーザーの既存変更は混ぜない。

各グループについて Conventional Commits の type と任意の scope を選ぶ。
subject は差分の列挙ではなく、変更の意図が分かる簡潔な英語にする。

### 3. 安全性を確認する

- status と diff から、対象外ファイルが含まれていないことを確認する
- `.env`、credential、秘密鍵、token などの疑いがあるファイルを stage しない
- 秘密らしい値を出力へ転載しない
- 生成物や大容量ファイルは、リポジトリの方針と変更目的を確認する
- hook を回避しない。失敗した場合は原因を報告し、勝手に別手段で通さない

### 4. Commit する

グループごとに対象パスを明示して stage し、staged diff を再確認してから
`<type>(<scope>): <subject>` 形式で commit する。scope が不要なら省く。

commit 後に、作成した commit と残っている変更を確認する。

### 5. Push する

`--no-push` なら commit 結果だけを報告して終了する。
それ以外は通常の push を使い、upstream がなければ現在の branch に設定する。

force push、履歴の書き換え、別 branch への付け替えはこの Skill の範囲外。
必要なら操作と影響を分けてユーザーへ確認する。

## 完了報告

次を簡潔に報告する。

- 作成した commit の hash と subject
- push 先、または `--no-push` により省略したこと
- commit せず残した変更と理由
- 実行した検証、または未実施の検証

## 安全境界

- ユーザーの変更を破棄・上書きしない。
- `git add .` のような広い指定より、確認済みの対象パスを使う。
- force push や destructive な履歴操作を行わない。
- Plugin のインストール状態やキャッシュは変更しない。
