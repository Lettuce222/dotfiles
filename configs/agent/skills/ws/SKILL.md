---
name: ws
description: Manage durable cross-project work knowledge and tasks in the ~/workspace Obsidian Vault. Use to orient from existing context, capture durable knowledge, manage tasks, sync external task state, unfold next steps, or clean up the Vault. Do not use for repository-local implementation tips or one-off output formatting.
---

# ws

Treat `~/workspace` as the single source of truth for durable, cross-project work knowledge and tasks.

## Choose one operation

- `orient`: retrieve relevant goals, decisions, people, initiatives, and open tasks.
- `capture`: turn durable work context into the appropriate note type and links.
- `task`: create, update, complete, or list Vault tasks.
- `sync`: reconcile Vault tasks with an external task system without inventing mappings.
- `unfold`: derive the next concrete actions from current goals and constraints.
- `cleanup`: inspect health and repair structure without changing meaning.

## Boundaries

- Keep repository-local operating tips in that repository's instructions or runtime memory.
- Keep one-off summaries, code edits, PR descriptions, and external-document formatting out of the Vault unless the user explicitly wants durable capture.
- Do not duplicate the same knowledge in runtime memory and the Vault.
- When another workflow requires a proposal or approval before writing, preserve that approval boundary.
- A direct request to save durable knowledge authorizes the scoped Vault write; ambiguous requests should produce a proposal first.

## Progressive references

Read only the relevant section of [`references/operations.md`](references/operations.md):

- structure and note types: `rg -n '^## (Vault の場所|ディレクトリ構造|ノートの型)' references/operations.md`
- orient/capture: `rg -n '^### [12]\\.' references/operations.md`
- task/sync: `rg -n '^### [34]\\.' references/operations.md`
- unfold/cleanup: `rg -n '^### [56]\\.' references/operations.md`
- placement boundaries: `rg -n '^## (何を Vault|やらないこと)' references/operations.md`

Use the existing templates under `templates/`. Run `scripts/ws-healthcheck.py` for structural health checks rather than recreating its logic.
