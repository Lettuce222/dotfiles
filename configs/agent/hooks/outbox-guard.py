#!/usr/bin/env python3
"""Claude Code PreToolUse hook: keep the model from approving its own posts.

external-post-guard.py lets a post through without a prompt when the user has
approved it in the hub's pane, which writes ${AGENT_HUB_HOME:-~/hub}/outbox/
<id>.approved. Only the pane may write that mark, so this hook denies:

  - Write, Edit, MultiEdit and NotebookEdit on a file named *.approved in an
    outbox directory.
  - Bash commands that name `.approved` at all, or that mention `outbox` and
    write files (touch, mv, cp, ln, tee, sed -i, an interpreter, a redirect...).
    The hub writes proposals with the Write tool, so it needs neither. Bash is
    checked as text only: a best effort that catches the plain ways, not every
    way a shell can reach a file.

external-post-guard.py also refuses a proposal whose .md or .json changed
after its approval, so editing an approved proposal does not help either.
"""

import json
import os
import re
import sys
from pathlib import Path

FILE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
MARK = re.compile(r"\.approved\b", re.I)
WRITES = re.compile(
    r"\b(?:touch|mv|cp|ln|install|rsync|tee|dd|truncate|python3?|perl|ruby|node|osascript)\b"
    r"|\bsed\b[^|;&]*\s-i"
    r"|(?<![0-9&>])>(?!&)",
)


def outbox_dir():
    return Path(os.environ.get("AGENT_HUB_HOME") or Path.home() / "hub").expanduser() / "outbox"


def is_mark(path, cwd):
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(cwd or ".") / p
    if not p.name.lower().endswith(".approved"):
        return False
    if p.parent.name == "outbox":
        return True
    try:
        return p.parent.resolve() == outbox_dir().resolve()
    except OSError:
        return False


def reason(tool_name, tool_input, cwd):
    if tool_name in FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if path and is_mark(path, cwd):
            return "outbox の .approved は、ユーザーがペインで承認したときにだけ書かれます。モデルは作らず、変えません。"
    elif tool_name == "Bash":
        command = tool_input.get("command") or ""
        if MARK.search(command):
            return "outbox の .approved に触れるコマンドは実行しません。承認はユーザーがペインで行います。"
        if "outbox" in command and WRITES.search(command):
            return "outbox のファイルは Bash で書き換えません。提案の .md と .json は Write で書きます。"
    return None


def main():
    data = json.load(sys.stdin)
    why = reason(data.get("tool_name") or "", data.get("tool_input") or {}, data.get("cwd"))
    if why is None:
        return 0
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": why,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
