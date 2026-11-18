# dotfiles

macOS と Ubuntu に対応する個人用 dotfiles。`install.sh` が `configs/*` をユーザーディレクトリにシンボリックリンクで配置する。

## 編集時の契約

- 配置される設定を変えるときは `configs/` の原本を編集する。
- ファイルやフォルダを追加・削除したり役割を変えたりしたら、[docs/overview.md](docs/overview.md) を更新し、`python3 -m unittest tests/test_overview.py` を通す。
- エージェント資産の配線と管理境界は [docs/agent-assets.md](docs/agent-assets.md)、マシン固有設定とインストールの規約は [docs/configuration.md](docs/configuration.md) を参照する。
- 仕事・私用と OS、ツール、サービスを結び付ける運用情報や、組織・業務案件・社内 URL・端末管理の具体情報は dotfiles に残さない。CLI の選択値はマシン固有の Git 管理外設定に置き、業務の文脈は必要な作業場所で管理する。

## 互換性

- 変更は Claude Code と Codex の両方で使えることを確認する。起動・設定配置・共通ワークフローを変えたら、`claude` と `codex` の両方の選択経路をテストする。
- 共通資産は両方から使える形で保つ。CLI 固有の引数、設定形式や hooks は対応する経路に置き、どちらの起動やセットアップにも影響する変更は両方で検証する。
- macOS と Ubuntu の両方を維持する。OS 固有処理は `install.sh` で分岐し、symlink や mise の共通処理は共有する。インストールは冪等に保つ。

## Git ワークフロー

- PR を作らず、`main` へ直接 push する。Conventional Commits 形式でコミットし、push の前に `origin/main` に rebase する。force push はしない。
- コミット前に設定を現在のマシンへ反映して検証する。リンクと設定だけの反映には `./install.sh --links-only` を使える。反映できなかった場合は、必要な手順を報告する。
