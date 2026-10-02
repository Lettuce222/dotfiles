#!/usr/bin/env bash
# Claude Code PostToolUse hook: lint Markdown written by the agent with textlint.
# Exit 2 feeds the findings back to the agent so it rewrites the text.

set -u

textlint_dir="$HOME/.config/textlint"
textlint="$textlint_dir/node_modules/.bin/textlint"

# Skip silently until install.sh has installed the npm packages.
[ -x "$textlint" ] || exit 0

file=$(jq -r '.tool_input.file_path // empty')
case "$file" in
  *.md) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

if ! out=$("$textlint" --config "$textlint_dir/.textlintrc.json" "$file" 2>&1); then
  echo "$out" >&2
  exit 2
fi
exit 0
