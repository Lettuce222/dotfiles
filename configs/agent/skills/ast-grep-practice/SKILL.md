---
name: ast-grep-practice
description: Design, test, and integrate project-specific ast-grep lint or rewrite rules. Use for structural patterns that ordinary linters cannot express, for safely migrating deprecated APIs, or for moving machine-checkable coding constraints out of prose instructions.
---

# ast-grep practice

Use ast-grep when the constraint depends on syntax-tree structure or a rewrite needs captured nodes. Prefer the repository's existing linter when it already expresses the rule clearly.

## Core workflow

1. Inspect the repository's language, package manager, lint layout, and existing rules.
2. Reduce the intended constraint to the smallest structural pattern.
3. Decide whether the rule is detection-only or safe to fix automatically.
4. Register the rule in `sgconfig.yml`.
5. Add valid and invalid tests. Add fix snapshots when a fix exists.
6. Run classification tests, review snapshots, and scan without rewriting.
7. Apply rewrites only after reviewing the match set and semantic risk.
8. Run the project's formatter, typecheck, tests, and final ast-grep scan.
9. Add the same deterministic checks to CI.

## Fix safety

Use an automatic fix only when captured nodes can be substituted without changing evaluation order, imports, types, side effects, or exception behavior. Otherwise keep the rule detection-only and explain the manual migration.

Before a bulk rewrite:

- test representative valid, invalid, and edge cases;
- review the generated fix snapshot;
- inspect the dry scan and match count;
- confirm the replacement preserves the API contract.

## Progressive references

Read only the sections needed for the current task:

- setup and config: `rg -n '^## (インストール|クイックスタート|プロジェクト設定)' references/guide.md`
- rule schema and matching: `rg -n '^## (ルールファイル構造|メタ変数|constraints|transform|utils)' references/guide.md`
- safe rewrites: `rg -n '^## fix|^### 範囲拡張' references/guide.md`
- tests and CI: `rg -n '^## (テスト|CI 統合)' references/guide.md`
- AST discovery and examples: `rg -n '^## (kind 名|実践的なルール例)' references/guide.md`

The detailed guide is [`references/guide.md`](references/guide.md). Do not load it wholesale when one section is enough.
