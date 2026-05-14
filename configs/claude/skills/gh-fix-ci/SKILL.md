---
name: gh-fix-ci
description: GitHub Actions で走る PR check が失敗したとき、gh CLI でチェック一覧とログを取得し、失敗要因を要約して修正計画を提示、承認後に実装するスキル。業務で扱う GitHub 上のリポジトリで「CI が赤い」「PR check が落ちた」「この失敗を直して」「GitHub Actions の原因を調べて」と言われたら必ず使う。PR URL・PR 番号・チェック名などが出てきた場合も発動。ただし Buildkite や CircleCI など外部 CI は対象外で、details URL の報告のみに留める。
---

# gh-fix-ci

GitHub Actions で落ちた PR check を `gh` CLI で特定・ログ取得し、失敗箇所を短く要約 → 修正計画を提示 → ユーザー承認後に実装、というフローを徹底するためのスキル。

## 使わない場面

- Buildkite / CircleCI / GitLab CI など GitHub Actions 以外の CI が落ちた場合。この skill は GH Actions 専用。外部 CI が混ざっているときは、details URL を報告するだけで手を出さない。
- CI ではなくローカルでのテスト失敗。普通にテストを読めば済むのでわざわざこの skill を起動する必要はない。

## 前提

`gh` CLI の認証が済んでいること。以下で確認:

```bash
gh auth status
```

未認証なら、ユーザーに `gh auth login` を依頼する（`repo` + `workflow` スコープが通常必要）。

## Inputs

- `repo`: リポジトリのローカルパス（既定: `.`）
- `pr`: PR 番号または URL（省略時は現在のブランチに紐づく PR を `gh pr view` で解決）

## ワークフロー

1. **gh 認証の確認**
   - `gh auth status` を実行
   - 未認証なら `gh auth login` を依頼して中断

2. **対象 PR の特定**
   - `gh pr view --json number,url` で現在のブランチから PR を引く
   - ユーザーが PR 番号 / URL を指定しているならそれを優先

3. **失敗している check の特定 (GitHub Actions に限定)**
   - `gh pr checks <pr> --json name,state,bucket,link,startedAt,completedAt,workflow`
     - フィールド名が `gh` のバージョンで弾かれる場合は、エラー文言が提示する利用可能フィールドで再実行する
   - 失敗した check それぞれについて `detailsUrl` から run id を抜き、以下を取得:
     - `gh run view <run_id> --json name,workflowName,conclusion,status,url,event,headBranch,headSha`
     - `gh run view <run_id> --log`
   - ログが「in progress」と返ってくる場合、job 単位で直接取る:
     - `gh api "/repos/<owner>/<repo>/actions/jobs/<job_id>/logs" > /tmp/<job_id>.log`

4. **非 GitHub Actions の check は除外**
   - `detailsUrl` が GitHub Actions の URL でない場合（`github.com/.../actions/runs/...` ではない）、external としてラベルし URL のみ報告。手を出さない。

5. **失敗のサマリ提示**
   - 以下をユーザーに出す:
     - 失敗 check 名
     - run URL
     - ログから抜いた失敗スニペット（エラー行 + 前後数行）
   - ログが取得できなかった場合はそれを明示する（黙って読み飛ばさない）

6. **修正計画の提示**
   - 「原因と思われるもの」「修正方針」「変更ファイル」の 3 点を短く書く
   - ユーザーの承認を得るまで実装には入らない

7. **実装 (承認後)**
   - 計画に沿って修正を入れる
   - diff とテスト結果を要約して提示
   - push してよいか / PR を立ててよいかを確認

8. **再チェック**
   - 修正後、関連テストのローカル実行と `gh pr checks` の再確認を提案する

## ログ取得の実務的コツ

- `gh run view <run_id> --log` は run 全体のログをまとめて返すが、大規模ワークフローだと巨大になる。`--log-failed` を付けると失敗 job だけに絞れる:
  ```bash
  gh run view <run_id> --log-failed
  ```
- さらに絞りたいときは `| grep -E '(Error|FAIL|error:|exit code)' -A 20` のようにパイプする
- マトリクスビルドで同一 workflow 内に複数 job がある場合、job ごとに原因が違うことがある。`gh run view <run_id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .databaseId'` で失敗 job の id を抜き、job 単位でログを取る

## 失敗サマリのフォーマット

ユーザーに返すときは次の構造を徹底する。長文でログを貼るのは避けて、スニペット + 行番号 / リンクを優先する:

```
## 失敗 check: <名前>

- workflow: <workflow 名>
- run URL: <URL>
- 失敗スニペット:
  ```
  <関連行 (前後 5〜10 行程度)>
  ```

## 原因の当たり

<1〜3 行でエラーの性質を要約>

## 修正案

- 変更対象: <ファイルパス>
- 変更内容: <短く>
- 影響範囲: <他に波及するか>

この方針で進めてよいですか?
```

## Red flags（合理化に注意）

| 出がちな判断 | 実態 |
|---|---|
| 「ログ見るより先に直してしまおう、どうせ typo だろう」 | 思い込みで直すと別な所が壊れる。必ずログから要因を特定する。 |
| 「外部 CI (Buildkite 等) も gh で取れないか試そう」 | 取れない。この skill は GitHub Actions 専用。details URL を示して手を引く。 |
| 「ログが巨大だから先頭だけ読む」 | エラーは末尾側にあることが多い。`--log-failed` か grep で絞る。 |
| 「承認前に先に修正もやってしまおう」 | 勝手な修正は PR 履歴を濁す。必ず計画提示 → 承認 → 実装の順を守る。 |
| 「再チェックはユーザーがやるから省略」 | 修正が効いたか確認しないと再度赤になって戻って来る。テスト実行を提案する。 |

## 関連

- `commit-push` — 修正のコミット / プッシュをまとめて行うとき
- `ast-grep-practice` — 落ちている原因が lint ルールで防げるものなら、再発防止を ast-grep ルールに落とす
