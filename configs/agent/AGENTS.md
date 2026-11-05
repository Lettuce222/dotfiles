## Shell Environment

- The user's interactive shell is fish, but the Bash tool runs zsh. Write POSIX syntax for commands you run yourself.
- Use fish syntax only when showing commands for the user to run.

## Engineering Judgement

- Match the surrounding code and repository contracts.
- Keep state, logic, and I/O separable when that makes later changes easier.
- Design APIs, types, and schemas carefully while keeping implementations replaceable.
- Prefer clear, maintainable code over cleverness.
- Express machine-checkable invariants in tests, linters, formatters, or ast-grep when practical.

## Writing to External Services

- Before posting prose to an external service via MCP (issues, pull requests, comments, wiki pages, chat messages), write the draft to `/tmp/<topic>-<YYYYMMDD-HHMMSS>.md` first. The timestamp keeps parallel sessions from overwriting each other's drafts.
- Fix every textlint finding on that draft, then send its content unchanged.
- Treat the draft and textlint steps as routine: do not mention them in reports to the user unless textlint could not be run.

## Context Boundaries

- Do not store company-, organization-, project-, team-, person-, ticket-, internal-URL-, query-, or unreleased-work context in dotfiles-managed agent configuration.
- Keep repository-local operating tips in that repository's instructions or runtime memory.
