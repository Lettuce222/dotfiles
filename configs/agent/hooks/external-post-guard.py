#!/usr/bin/env python3
"""Claude Code PreToolUse hook: guard prose that is about to leave the machine.

Targets:
  - MCP tools whose input carries prose under body-like keys (Slack messages,
    issue/PR comments, page bodies, ...).
  - Bash `gh pr|issue create|comment|edit|review` and `gh api` calls with a body.

Rules (exit 2 so the agent fixes the draft):
  1. Every ticket ID (ABC-123) and PR/issue number (#123) must be a link whose
     label is the ID itself: Markdown `[ABC-123](url)` or Slack `<url|ABC-123>`.
  2. Every date (11/4, 11月4日, 2026-11-04) must be followed by its weekday in
     parentheses, e.g. `11/4(水)`.

When the prose passes, return permissionDecision "ask" so the user reviews the
wording before anything is sent.

No service or tool names are hard-coded; prose is found by key name, as in
textlint-mcp.sh.
"""

import json
import re
import shlex
import sys
from pathlib import Path

PROSE_KEY = re.compile(r"^(body|description|commentBody|comment|text|message)$", re.I)

MD_LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)")
SLACK_LINK = re.compile(r"<(?P<url>[^>|\s]+)\|(?P<label>[^>]+)>")
SLACK_TOKEN = re.compile(r"<[@#!][^>]*>")
BARE_URL = re.compile(r"https?://\S+")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)

TICKET = re.compile(r"(?<![\w/.-])[A-Z][A-Z0-9]+-\d+(?![\w-])")
NUMBER = re.compile(r"(?<![\w&/])#\d+\b")
NOT_TICKETS = {"UTF-8", "UTF-16", "SHA-1", "SHA-256", "ISO-8601", "AES-256", "MD-5"}
ID_LABEL = re.compile(r"^(?:[A-Z][A-Z0-9]+-\d+|#\d+)$")

WEEKDAY = r"\s*[(（][月火水木金土日][)）]"
DATE = re.compile(
    r"(?<![\w/.-])(?:\d{4}-\d{1,2}-\d{1,2}|(?:\d{4}/)?\d{1,2}/\d{1,2}|(?:\d{4}年)?\d{1,2}月\d{1,2}日)"
    r"(?![\w/])(?!" + WEEKDAY + ")"
)


def collect_prose(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and PROSE_KEY.match(k):
                out.append(v)
            else:
                collect_prose(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_prose(v, out)


def read_file(path):
    p = Path(path).expanduser()
    return p.read_text(errors="replace") if p.is_file() else ""


def gh_body(command):
    """Return the body text of a gh write command, or None if not one."""
    if not re.search(r"\bgh\s+(pr|issue)\s+(create|comment|edit|review)\b|\bgh\s+api\b", command):
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        return command
    parts = []
    i = 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        i += 1
        if a == "--body-file" and nxt is not None:
            parts.append(read_file(nxt))
            i += 1
        elif a in ("-b", "--body") and nxt is not None:
            parts.append(nxt)
            i += 1
        elif a.startswith("--body="):
            parts.append(a.split("=", 1)[1])
        elif a in ("-f", "-F", "--field", "--raw-field") and nxt is not None:
            i += 1
            key, _, val = nxt.partition("=")
            if PROSE_KEY.match(key):
                parts.append(read_file(val[1:]) if val.startswith("@") else val)
    return "\n\n".join(parts)


def strip_links(text):
    text = CODE.sub(" ", text)
    for rx in (MD_LINK, SLACK_LINK):
        # Drop links labelled with the bare ID; keep other labels so IDs or
        # dates hidden inside them are still checked.
        text = rx.sub(
            lambda m: " " if ID_LABEL.match(m.group("label").strip()) else " " + m.group("label") + " ",
            text,
        )
    text = SLACK_TOKEN.sub(" ", text)
    return BARE_URL.sub(" ", text)


def problems(text):
    text = strip_links(text)
    ids = [m.group(0) for m in TICKET.finditer(text) if m.group(0) not in NOT_TICKETS]
    ids += [m.group(0) for m in NUMBER.finditer(text)]
    dates = [m.group(0) for m in DATE.finditer(text)]
    out = []
    if ids:
        out.append(
            "リンクになっていないチケット ID・PR 番号: " + ", ".join(dict.fromkeys(ids))
            + "\n  表示名を ID にしたリンクに直す。Markdown は [PROD-123](URL)、Slack は <URL|PROD-123>。"
        )
    if dates:
        out.append(
            "曜日のない日付: " + ", ".join(dict.fromkeys(dates))
            + "\n  日付のすぐ後に (曜日) を付ける。例: 11/4(水)"
        )
    return out


def main():
    data = json.load(sys.stdin)
    tin = data.get("tool_input") or {}

    if data.get("tool_name") == "Bash":
        body = gh_body(tin.get("command", ""))
        if body is None:
            return 0
    else:
        prose = []
        collect_prose(tin, prose)
        if not prose:
            return 0
        body = "\n\n".join(prose)

    found = problems(body)
    if found:
        print("送信をブロックしました。下書きを直してから送り直してください。\n" + "\n".join(found), file=sys.stderr)
        return 2

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "外部に送る文面です。送る前に内容を確認してください。",
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
