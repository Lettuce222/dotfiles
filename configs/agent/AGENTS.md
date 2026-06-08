## Shell Environment

- Shell: fish
- Use fish syntax for shell commands (e.g., `fish_add_path` instead of `export PATH=...`)

## Code Design Principles

- **関心の分離を保つ**: 状態とロジック、I/O と純粋関数を分けて書く。
- **契約層を厳密に、実装は差し替え可能に**: API・型・スキーマは丁寧に設計し、内部実装は自由に書き換えられる構造を優先する。
- **静的検査可能なルールはプロンプトではなく、linter / formatter / ast-grep で表現する**: CLAUDE.md やメモリで言葉で縛るのは、コードや CI で強制できない性質のものに限定する。「この書き方は禁止」など機械的に判定可能な制約は必ず静的ツール側に寄せる。
- **可読性・保守性を最優先する**: 巧妙さより明快さ。読み手が次に変更するときのコストを下げることを基準に判断する。

## 仕事の全体観 Vault

dotfiles で管理する agent 設定には、特定の会社・組織・プロジェクト・チーム・人・チケットキー・内部 URL・クエリ・未公開情報など、仕事固有の文脈を含めない。dotfiles 側には一般的な仕事の進め方、記録先、ツールの使い分けだけを書く。

仕事固有の文脈を含めてエージェントを操作する必要がある場合は、`~/workspace` 配下の Vault ノート、または `~/workspace/AGENTS.md` に書く。特定リポジトリに紐付かない仕事の全体観やタスクは `~/workspace` の Vault に集約し、必要に応じて `ws` skill で参照（orient）・記録（capture）・タスク追加する。リポジトリ固有の即時 tips は auto-memory の領分なので混同しない。
