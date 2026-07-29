## Shell Environment

- Shell: fish
- Use fish syntax for shell commands.

## Engineering Judgement

- Match the surrounding code and repository contracts.
- Keep state, logic, and I/O separable when that makes later changes easier.
- Design APIs, types, and schemas carefully while keeping implementations replaceable.
- Prefer clear, maintainable code over cleverness.
- Express machine-checkable invariants in tests, linters, formatters, or ast-grep when practical.

## Context Boundaries

- Do not store company-, organization-, project-, team-, person-, ticket-, internal-URL-, query-, or unreleased-work context in dotfiles-managed agent configuration.
- Put durable cross-project work knowledge and tasks in `~/workspace`; use the `ws` skill when that Vault is the intended source of truth.
- Keep repository-local operating tips in that repository's instructions or runtime memory rather than duplicating them in the Vault.
