#!/usr/bin/env python3
"""Claude Code PreToolUse hook: guard prose that is about to leave the machine.

Targets:
  - MCP tools whose input carries prose under body-like keys (Slack messages,
    issue/PR comments, page bodies, ...).
  - Bash commands that run a gh write: `gh pr create|comment|review|merge|
    ready|edit|close|reopen`, `gh issue create|comment|edit|close|reopen`, and
    `gh api` calls that are not plain reads. gh may be called by path.

Rules (exit 2 so the agent fixes the draft):
  1. Every ticket ID (ABC-123) and PR/issue number (#123) must be a link whose
     label is the ID itself: Markdown `[ABC-123](url)` or Slack `<url|ABC-123>`.
  2. Every date (11/4, 11月4日, 2026-11-04) must be followed by its weekday in
     parentheses, e.g. `11/4(水)`.

When the prose passes:
  - if the orchestrator recorded a one-shot approval for exactly this call
    (approvals.py), consume it and return permissionDecision "allow";
  - otherwise return "ask" so the user reviews the operation first.

No service or tool names are hard-coded; prose is found by key name, as in
textlint-mcp.sh.

Drafts can be checked with the same rules before anything is sent:
  external-post-guard.py --check <file>...
prints the problems of each file and exits 1 if any file has one (0 if all
pass). The rules do not depend on the destination: Markdown and Slack links
are both accepted.
"""

import json
import os
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


PR_WRITES = {"create", "comment", "review", "merge", "ready", "edit", "close", "reopen"}
ISSUE_WRITES = {"create", "comment", "edit", "close", "reopen"}
SEPARATOR = re.compile(r"^[();<>|&\n]+$")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"env", "command", "builtin", "exec", "time", "nohup", "sudo", "xargs", "timeout"}
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}


def simple_commands(command):
    """Split a shell command line into argv lists at operators and newlines."""
    lex = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    argv = []
    for tok in lex:
        if SEPARATOR.match(tok):
            if argv:
                yield argv
            argv = []
        else:
            argv.append(tok)
    if argv:
        yield argv


def unwrap(argv, depth):
    """Strip env assignments and wrappers; descend into `sh -c` and `eval`."""
    i = 0
    while i < len(argv):
        if ASSIGNMENT.match(argv[i]):
            i += 1
        elif argv[i] in WRAPPERS:
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or ASSIGNMENT.match(argv[i])):
                i += 1
        else:
            break
    argv = argv[i:]
    if not argv:
        return []
    name = os.path.basename(argv[0])
    if depth < 3 and name in SHELLS and "-c" in argv[1:-1]:
        return gh_writes(argv[argv.index("-c") + 1], depth + 1)
    if depth < 3 and name == "eval":
        return gh_writes(" ".join(argv[1:]), depth + 1)
    return [argv]


def is_write(argv):
    if not argv or not is_gh(argv[0]) or len(argv) < 2:
        return False
    group, sub = argv[1], (argv[2] if len(argv) > 2 else "")
    if group == "pr":
        return sub in PR_WRITES
    if group == "issue":
        return sub in ISSUE_WRITES
    if group == "api":
        return not is_gh_api_read(argv)
    return False


def substitutions(token):
    """Bodies of `$(...)` and backquote substitutions inside a token."""
    out = []
    i = token.find("$(")
    while i != -1:
        level, j = 1, i + 2
        while j < len(token) and level:
            level += {"(": 1, ")": -1}.get(token[j], 0)
            j += 1
        out.append(token[i + 2 : j - 1] if level == 0 else token[i + 2 :])
        i = token.find("$(", j)
    out += re.findall(r"`([^`]*)`", token)
    return out


def gh_writes(command, depth=0):
    """argv lists of the gh writes in a command line.

    Text that only appears inside a quoted argument (for example the command
    handed to `approvals.py add --command '...'`) is not a gh call, but a
    command substitution inside one is.
    """
    out = []
    for argv in simple_commands(command):
        out += [a for a in unwrap(argv, depth) if is_write(a)]
        if depth < 3:
            for tok in argv:
                for inner in substitutions(tok):
                    out += gh_writes(inner, depth + 1)
    return out


def gh_body(argv):
    """Return the body text a gh write sends."""
    parts = []
    i = 0
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        i += 1
        if a == "--body-file" and nxt is not None:
            parts.append(read_file(nxt))
            i += 1
        elif a.startswith("--body-file="):
            parts.append(read_file(a.split("=", 1)[1]))
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


def is_gh(arg):
    """True for `gh` itself or a path to it (~/.local/share/gh-ghtkn/bin/gh)."""
    return os.path.basename(arg) == "gh"


def is_gh_api_read(args):
    """True for a `gh api` call that only reads (GET without a payload)."""
    if not args or not is_gh(args[0]) or args[1:2] != ["api"]:
        return False
    method = None
    payload = False
    for i, a in enumerate(args):
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a in ("-X", "--method"):
            method = nxt.upper()
        elif a.startswith("--method="):
            method = a.split("=", 1)[1].upper()
        elif a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith(
            ("--field=", "--raw-field=", "--input=")
        ):
            payload = True
    # gh api sends fields with POST unless the method is given.
    return method == "GET" if method else not payload


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


def decide(decision, reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


def take_approval(data):
    """Consume a matching one-shot approval. Returns (record, reason)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.dont_write_bytecode = True  # keep __pycache__ out of the hooks directory
    try:
        import approvals
    except ImportError:
        return None, None
    return approvals.take(data.get("tool_name"), data.get("tool_input") or {}, data.get("session_id"))


def check_files(paths):
    """`--check <file>...`: report rule violations in drafts without a hook payload."""
    if not paths:
        print("usage: external-post-guard.py --check <file>...", file=sys.stderr)
        return 2
    status = 0
    for path in paths:
        p = Path(path).expanduser()
        if not p.is_file():
            print(f"{path}: ファイルがありません", file=sys.stderr)
            return 2
        found = problems(p.read_text(errors="replace"))
        if found:
            status = 1
            print(f"{path}:\n" + "\n".join(found))
    return status


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--check"]:
        return check_files(argv[1:])
    data = json.load(sys.stdin)
    tin = data.get("tool_input") or {}
    command = tin.get("command", "") if data.get("tool_name") == "Bash" else None

    if command is not None:
        try:
            writes = gh_writes(command)
            body = "\n\n".join(gh_body(argv) for argv in writes)
        except ValueError:
            # Unparsable (unbalanced quotes): check the raw text conservatively.
            if not re.search(r"\bgh\s+(pr|issue|api)\b", command):
                return 0
            writes, body = [command], command
        if not writes:
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

    record, why = take_approval(data)
    if record:
        decide("allow", "窓口で承認済みの操作です: " + (record.get("note") or record.get("id", "")))
        return 0

    reason = "外部に送る文面です。送る前に内容を確認してください。"
    decide("ask", reason + (f"（{why}）" if why else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
