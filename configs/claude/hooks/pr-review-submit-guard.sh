#!/bin/bash
# PreToolUse hook for Bash tool.
#
# Detects GitHub PR review *submit* commands and forces a permission prompt
# so the user must explicitly approve the wording before it goes public.
# Pairs with the `pr-review-comment` skill, which builds a pending review
# locally and only submits after the user signs off.
#
# Patterns flagged:
#   - gh pr review ... --approve|--request-changes|--comment
#   - gh api ... /pulls/.../reviews        with event=APPROVE|COMMENT|REQUEST_CHANGES
#   - gh api ... /reviews/<id>/events
#   - gh api ... /pulls/.../comments       (single line-comment direct post)
#
# Pending-review *creation* (POST /reviews without an event) and pure read
# operations are intentionally not flagged — those are the safe building
# blocks the skill relies on.
#
# Returns JSON on stdout for PreToolUse:
#   {"hookSpecificOutput": {"hookEventName": "PreToolUse",
#                           "permissionDecision": "ask",
#                           "permissionDecisionReason": "..."}}
# Otherwise prints nothing (no decision = fall through to defaults).

set -u

input=$(cat)

tool_name=$(printf '%s' "$input" | jq -r '.tool_name // ""')
if [ "$tool_name" != "Bash" ]; then
  exit 0
fi

command=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')
if [ -z "$command" ]; then
  exit 0
fi

emit_ask() {
  reason=$1
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# `gh pr review` with a submit flag.
if printf '%s' "$command" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+review([[:space:]]|$)' \
   && printf '%s' "$command" | grep -Eq -- '--approve|--request-changes|--comment'; then
  emit_ask "PRレビューの即時 submit を検知しました。pr-review-comment skill のフロー(下書き→確認→pending→submit)を踏み、文面をユーザーに提示して承認を得てから実行してください。"
fi

# `gh api ... /reviews/<id>/events` — explicit submit of an existing pending review.
if printf '%s' "$command" | grep -Eq 'gh[[:space:]]+api' \
   && printf '%s' "$command" | grep -Eq 'reviews/[0-9]+/events'; then
  emit_ask "pending review の submit (events エンドポイント) を検知しました。文面をユーザーに最終確認してから実行してください。"
fi

# `gh api ... /pulls/.../reviews` carrying an event= field — creates+submits in one shot.
if printf '%s' "$command" | grep -Eq 'gh[[:space:]]+api' \
   && printf '%s' "$command" | grep -Eq 'pulls/.*/reviews' \
   && printf '%s' "$command" | grep -Eq 'event[[:space:]]*=[[:space:]]*(APPROVE|COMMENT|REQUEST_CHANGES)'; then
  emit_ask "review 作成と同時の submit (event 指定) を検知しました。pending → ユーザー確認 → submit の順に分割してください。"
fi

# Direct single line-comment post, bypassing review batching.
if printf '%s' "$command" | grep -Eq 'gh[[:space:]]+api' \
   && printf '%s' "$command" | grep -Eq 'pulls/[^[:space:]]*/comments'; then
  emit_ask "review を介さない単発 line コメントの直接投稿を検知しました。pr-review-comment skill の pending review にまとめてください。"
fi

exit 0
