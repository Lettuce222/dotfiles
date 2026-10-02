#!/usr/bin/env bash
# Claude Code PreToolUse hook: lint Japanese prose that an MCP tool is about to send.
# Exit 2 blocks the call and tells the agent to fix the draft .md first.

set -u

textlint_dir="$HOME/.config/textlint"
textlint="$textlint_dir/node_modules/.bin/textlint"

# Skip silently until install.sh has installed the npm packages.
[ -x "$textlint" ] || exit 0

# Collect string values under prose-like keys anywhere in the input, so this works
# across services (issue/PR bodies, comments, page bodies, ADF text nodes).
# "content" is excluded because file-push tools put source code there.
body=$(jq -r '
  [.tool_input | .. | objects | to_entries[]
    | select((.key | test("^(body|description|commentBody|comment|text|message)$"; "i"))
             and (.value | type == "string"))
    | .value]
  | join("\n\n")
')

# Only Japanese prose is in scope; reads and English-only payloads pass through.
printf '%s' "$body" | grep -q '[ぁ-んァ-ヶ]' || exit 0

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf '%s\n' "$body" >"$tmp/mcp-body.md"

if ! out=$("$textlint" --config "$textlint_dir/.textlintrc.json" "$tmp/mcp-body.md" 2>&1); then
  {
    echo "MCPでの送信をブロックしました。本文がtextlintに通っていません。"
    echo "下書きの.mdを直してtextlintを通してから、その内容を送信し直してください。"
    echo "$out"
  } >&2
  exit 2
fi
exit 0
