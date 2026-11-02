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

When the prose passes, the decision depends on the session:
  - agent-hub worker (AGENT_HUB_WORKER is set by spawn.fish): a draft PR on
    the worker's own branch (AGENT_HUB_BRANCH) may be created, edited, or
    commented on without a prompt. Every other post is blocked with exit 2 and
    the worker is told to hand the draft to the hub, which sends it after the
    user approves. The user talks only to the hub, so a prompt in a worker
    window would stall the worker until someone noticed.
  - any other session (the hub included): return permissionDecision "ask" so
    the user reviews the wording before anything is sent.

No service or tool names are hard-coded; prose is found by key name, as in
textlint-mcp.sh.
"""

import json
import os
import re
import shlex
import subprocess
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


GH_WRITE = re.compile(r"\bgh\s+(pr|issue)\s+(create|comment|edit|review)\b|\bgh\s+api\b")
SHELL_OPS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;"}


def gh_body(command):
    """Return the body text of a gh write command, or None if not one."""
    if not GH_WRITE.search(command):
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        return command
    if is_gh_api_read(args):
        return None
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


def is_gh_api_read(args):
    """True for a lone `gh api` call that only reads (GET without a payload)."""
    if args[:2] != ["gh", "api"] or any(a in SHELL_OPS for a in args):
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


def worker_branch():
    """Return the agent-hub worker's own branch, or None outside a worker."""
    name = os.environ.get("AGENT_HUB_WORKER", "")
    if not name:
        return None
    # spawn.fish names a worker <repo>.<task> and its branch agent/<task>;
    # task has no dot. Workers started before AGENT_HUB_BRANCH existed rely
    # on that naming.
    return os.environ.get("AGENT_HUB_BRANCH") or "agent/" + name.rsplit(".", 1)[-1]


def run(args, cwd):
    try:
        r = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def own_draft_pr(command, cwd, branch):
    """Return None if the command writes only to the worker's own draft PR,
    otherwise the reason it does not."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        args = list(lexer)
    except ValueError:
        return "コマンドを解釈できません"
    if any(a in SHELL_OPS or a.startswith(("<", ">")) for a in args) or args[:2] != ["gh", "pr"]:
        return "gh pr create・edit・comment を、cd・&&・リダイレクトを付けずに単独で実行していません"
    sub = args[2] if len(args) > 2 else ""
    if sub not in ("create", "edit", "comment"):
        return f"gh pr {sub} は作業ブランチの draft PR の作成・編集・コメントに当たりません"
    for a in args[3:]:
        flag = a.split("=", 1)[0]
        if flag in ("-R", "--repo"):
            return "-R・--repo で別のリポジトリを指しています"
        if sub == "create" and flag in ("-H", "--head"):
            return "--head で作業ブランチ以外を指せます"
        if flag in ("--add-reviewer", "--remove-reviewer"):
            return "reviewer の指定は承認範囲の外です"

    if sub == "create":
        if not any(a in ("-d", "--draft") for a in args[3:]):
            return "--draft の付いていない PR を作ろうとしています"
        current = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd)
        if current != branch:
            return f"今のブランチ（{current}）が作業ブランチ {branch} ではありません"
        return None

    # edit / comment: the target is the first positional argument, or the
    # current branch's PR when none is given.
    target = []
    i = 3
    takes_value = {"-b", "--body", "-F", "--body-file", "-t", "--title", "-B", "--base",
                   "-a", "--add-assignee", "--remove-assignee", "-l", "--add-label",
                   "--remove-label", "-m", "--milestone", "-p", "--add-project",
                   "--remove-project"}
    while i < len(args):
        a = args[i]
        if a in takes_value:
            i += 2
            continue
        if not a.startswith("-"):
            target = [a]
            break
        i += 1
    raw = run(["gh", "pr", "view", *target, "--json", "headRefName,isDraft,isCrossRepository,state"], cwd)
    if raw is None:
        return "対象の PR を gh pr view で確かめられません"
    try:
        pr = json.loads(raw)
    except ValueError:
        return "対象の PR を gh pr view で確かめられません"
    if pr.get("headRefName") != branch or pr.get("isCrossRepository"):
        return f"対象の PR が作業ブランチ {branch} のものではありません"
    if pr.get("state") != "OPEN" or not pr.get("isDraft"):
        return "対象の PR が open の draft ではありません"
    return None


def main():
    data = json.load(sys.stdin)
    tin = data.get("tool_input") or {}
    command = tin.get("command", "") if data.get("tool_name") == "Bash" else None

    if command is not None:
        body = gh_body(command)
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

    branch = worker_branch()
    if branch is not None:
        reason = own_draft_pr(command, data.get("cwd"), branch) if command is not None else "MCP 経由の送信です"
        if reason is None:
            return 0
        print(
            "worker から送れるのは、作業ブランチの draft PR の作成・編集・コメントだけです"
            f"（{reason}）。\n"
            "送らずに、下書きを /tmp/<topic>-<YYYYMMDD-HHMMSS>.md に書き、送り先と目的を添えて"
            "hub に「要判断」で報告してください。hub がユーザーに確認してから送ります。",
            file=sys.stderr,
        )
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
