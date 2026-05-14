---
name: commit-push
description: 未コミットの変更を分析し、論理的なグループに分割してconventional commit形式でコミット・pushするスキル。「コミットして」「commit」「push」「変更をまとめて」「conventional commit」「commit-push」などのキーワードや、ユーザーがgitの変更を整理してコミット・プッシュしたい文脈で必ずトリガーすること。引数として `--no-push` が指定された場合はpushをスキップする。
---

# Commit Push

未コミットの変更を分析し、論理的なグループに分割してconventional commit形式でコミットします。

## 引数

- `--no-push`: コミットのみ実行し、pushはスキップ

## 実行手順

### Step 1: 現在の状態を確認

以下のコマンドを実行して現在の状態を把握する：

- `git status` — 変更ファイルの確認
- `git diff HEAD` — staged + unstagedの差分
- `git log --oneline -10` — 最近のコミット履歴（スタイル参考用）
- `git branch -vv` — 現在のブランチとリモート状態

### Step 2: 変更の判定

取得した情報を分析し、以下を判定する：

1. **変更がない場合**: 「コミットする変更がありません」と報告して終了
2. **コンフリクトがある場合**: 「マージコンフリクトが検出されました。先に解決してください」と報告して終了
3. **変更がある場合**: Step 3へ進む

### Step 3: 変更のグループ化

変更されたファイルを以下の基準で論理的にグループ化する：

- **機能単位**: 同じ機能に関連するファイルをまとめる
- **変更タイプ**: feat/fix/chore/docs/refactor/test/style などの種類
- **依存関係**: 一緒にコミットすべきファイル（例：実装とそのテスト）

各グループに対して、以下を決定する：

1. conventional commit タイプ（feat, fix, chore, docs, refactor, test, style, perf, ci, build）
2. スコープ（任意、該当するモジュールや機能名）
3. コミットメッセージ（「何を」ではなく「なぜ」を重視、英語で記述）

### Step 4: コミットの実行

各グループに対して：

1. 対象ファイルを `git add` でステージング
2. conventional commit形式でコミット作成
   - フォーマット: `<type>(<scope>): <description>`
   - 例: `feat(nvim): add LSP configuration for TypeScript`
3. 各コミット後に結果を報告

### Step 5: プッシュ（--no-pushでない場合）

引数に `--no-push` が含まれている場合はこのステップをスキップし、「コミット完了。--no-pushが指定されたためpushはスキップしました」と報告して終了する。

`--no-push` がない場合：

1. `git push` を実行（リモートブランチ未設定の場合は `-u origin <branch>` を使用）

## 安全性ルール

- **force push禁止**: 通常のpushのみ使用
- **機密ファイルの検出**: `.env`, credentials, secrets, `*_key*`, `*.pem` などを検出したら警告し、除外を提案

## 出力フォーマット

各コミット完了時：

```
✓ コミット作成: feat(nvim): add LSP configuration for TypeScript
  2 files changed, 45 insertions(+), 3 deletions(-)
```

プッシュ完了時：

```
✓ origin/main にプッシュ完了
  2 commits pushed
```
