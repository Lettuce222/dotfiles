## Shell Environment

- Shell: fish
- Use fish syntax for shell commands.

## Engineering Judgement

- Match the surrounding code and repository contracts.
- Keep state, logic, and I/O separable when that makes later changes easier.
- Design APIs, types, and schemas carefully while keeping implementations replaceable.
- Prefer clear, maintainable code over cleverness.
- Express machine-checkable invariants in tests, linters, formatters, or ast-grep when practical.

## Writing to External Services

- Before posting prose to an external service via MCP (issues, pull requests, comments, wiki pages, chat messages), write the draft to a `.md` file outside the repository (e.g. under `$TMPDIR`) first.
- Fix every textlint finding on that draft, then send its content unchanged.

## Context Boundaries

- Do not store company-, organization-, project-, team-, person-, ticket-, internal-URL-, query-, or unreleased-work context in dotfiles-managed agent configuration.
- Keep repository-local operating tips in that repository's instructions or runtime memory.
