---
name: pr-review-comment
description: Draft and publish inline GitHub pull-request review comments through one pending review. Use when reviewing another person's PR, proposing line comments or suggestions, or submitting an approved review. Keep drafting, pending-review creation, and final submission as separate approval-aware stages.
---

# PR review comment

Create concise, line-anchored findings and publish them as one pending review. Never publish individual line comments as a substitute for the pending-review flow.

## Workflow

1. Read the PR metadata, diff, and relevant surrounding code.
2. Draft only actionable findings. Distinguish defects from observations, praise, and already-correct changes.
3. Present the proposed comment list to the user before any GitHub write.
4. After approval to create it, build one review payload without an `event` field and create a pending review.
5. Report the review ID, Files changed URL, and ordered comment summary. Let the user inspect the rendered review in GitHub.
6. If comments change, update the pending review using the documented GitHub behavior.
7. Submit only after the user explicitly supplies `COMMENT`, `APPROVE`, or `REQUEST_CHANGES`.

## Comment contract

- Anchor each comment to a changed line on the correct side of the diff.
- Put the review label on its own first line.
- State the consequence and requested change briefly.
- Use a `suggestion` block only when the replacement is complete and safe to apply.
- Do not comment on a typo or defect that the PR already fixes unless a short positive observation adds real value.
- Link other code only when it materially helps the recipient act.

## Safety boundaries

- Drafting is read-only.
- Creating or recreating a pending review is a GitHub write and needs user approval.
- Replying to an existing thread publishes immediately and needs approval of the exact reply text.
- Submitting publishes the whole review and needs explicit approval of the event type.
- Do not use `gh pr review --approve`, `--request-changes`, or `--comment` to bypass this flow.

## Progressive references

Read only what the current stage needs from [`references/review-guide.md`](references/review-guide.md):

- labels and writing style: `rg -n '^## (ラベル|コメントの書式|コメント本文のトーン|コメントの文量|suggestion)' references/review-guide.md`
- pending payload and creation: `rg -n '^### Step [123]:' references/review-guide.md`
- revision and GitHub edge cases: `rg -n '^### Step 4:|^#### ' references/review-guide.md`
- submission and prohibited shortcuts: `rg -n '^### Step 5:|^## 禁止事項' references/review-guide.md`
- examples only when wording is uncertain: `rg -n '^## 例:' references/review-guide.md`

Do not load the entire guide when one stage is enough.
