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
    the user reviews the wording before anything is sent. The one exception is
    a post the user has already approved in the hub's pane: when the prose and
    destination match a proposal in ${AGENT_HUB_HOME:-~/hub}/outbox whose
    <id>.approved mark is under 30 minutes old, return "allow" and rename the
    mark to <id>.sent so the approval cannot be used twice (see
    approved_proposal). outbox-guard.py keeps the model from writing marks.

No service or tool names are hard-coded; prose is found by key name, as in
textlint-mcp.sh.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
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


def is_gh(arg):
    """True for `gh` itself or a path to it (~/.local/share/gh-ghtkn/bin/gh)."""
    return os.path.basename(arg) == "gh"


def tokens(command):
    """Split a command line, keeping shell operators as separate tokens."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def is_gh_api_read(args):
    """True for a lone `gh api` call that only reads (GET without a payload)."""
    if not args or not is_gh(args[0]) or args[1:2] != ["api"] or any(a in SHELL_OPS for a in args):
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
        args = tokens(command)
    except ValueError:
        return "コマンドを解釈できません"
    if any(a in SHELL_OPS or a.startswith(("<", ">")) for a in args) or not (
        args and is_gh(args[0]) and args[1:2] == ["pr"]
    ):
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


# --- posts the user approved in the hub's pane -------------------------------

APPROVAL_TTL_S = 30 * 60
CLOCK_SKEW_S = 60
REVIEW_EVENTS = {
    "-c": "comment", "--comment": "comment",
    "-a": "approve", "--approve": "approve",
    "-r": "request-changes", "--request-changes": "request-changes",
}


def outbox_dir():
    return Path(os.environ.get("AGENT_HUB_HOME") or Path.home() / "hub").expanduser() / "outbox"


def strip_prose(node):
    """The tool input without its prose: what names the destination."""
    if isinstance(node, dict):
        return {k: strip_prose(v) for k, v in node.items() if not (isinstance(v, str) and PROSE_KEY.match(k))}
    if isinstance(node, list):
        return [strip_prose(v) for v in node]
    return node


def gh_destination(command):
    """Destination of a lone `gh pr comment|review <number> -R <owner/repo>`
    whose only other flags are the body (-b, --body, --body-file) and the
    review event, or None. gh_body reads -F as a `gh api` field, so it is not
    taken here.

    Anything else (shell operators, a PR chosen by the current branch, extra
    flags such as --edit-last) is not matched, so it still asks."""
    try:
        args = tokens(command)
    except ValueError:
        return None
    if any(a in SHELL_OPS or a.startswith(("<", ">")) for a in args):
        return None
    if len(args) < 3 or not is_gh(args[0]) or args[1] != "pr" or args[2] not in ("comment", "review"):
        return None
    sub = args[2]
    repo = number = event = None
    has_body = False
    i = 3
    while i < len(args):
        a = args[i]
        flag, eq, val = a.partition("=") if a.startswith("--") else (a, "", "")
        if flag in ("-R", "--repo", "-b", "--body", "--body-file"):
            if not eq:
                if i + 1 >= len(args):
                    return None
                i += 1
                val = args[i]
            if flag in ("-R", "--repo"):
                if repo is not None:
                    return None
                repo = val
            else:
                has_body = True
        elif sub == "review" and flag in REVIEW_EVENTS and not eq and event is None:
            event = REVIEW_EVENTS[flag]
        elif not a.startswith("-") and number is None and a.isdigit():
            number = int(a)
        else:
            return None
        i += 1
    if repo is None or number is None or not has_body or (sub == "review" and event is None):
        return None
    action = "comment" if sub == "comment" else "review-" + event
    return {"tool": "gh", "repo": repo, "pr": number, "action": action}


def destination(tool_name, tool_input, command):
    if command is not None:
        return gh_destination(command)
    return {"tool": tool_name, "input": strip_prose(tool_input)}


def load_destination(path):
    want = json.loads(path.read_text())
    if not isinstance(want, dict):
        raise ValueError("not an object")
    if want.get("tool") == "gh":
        want["pr"] = int(want.get("pr"))
    return want


def parse_time(text):
    """Seconds since the epoch for an ISO 8601 time; a time without an offset
    is local time."""
    try:
        t = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.timestamp()


def approved_proposal(dest, body, now=None):
    """Claim the approval for this exact post and return its proposal ID, or
    None. A proposal <id> is <id>.md (the prose), <id>.json (the destination)
    and <id>.approved (the time the user approved it, written by the pane).

    It matches when the prose equals the .md (ignoring trailing newlines), the
    destination equals the .json, the approval is under 30 minutes old, and
    neither file changed after the approval. The mark is renamed to <id>.sent
    before returning, so one approval lets one post through; the rename is
    atomic, so two calls racing for the same mark cannot both win."""
    if dest is None:
        return None
    now = time.time() if now is None else now
    box = outbox_dir()
    for mark in sorted(box.glob("*.approved")):
        pid = mark.name[: -len(".approved")]
        md, js = box / (pid + ".md"), box / (pid + ".json")
        try:
            if md.read_text().rstrip("\n") != body.rstrip("\n"):
                continue
            if load_destination(js) != dest:
                continue
            approved_at = parse_time(mark.read_text())
            if approved_at is None or not -CLOCK_SKEW_S <= now - approved_at <= APPROVAL_TTL_S:
                continue
            if max(md.stat().st_mtime, js.stat().st_mtime) > mark.stat().st_mtime:
                continue
            os.rename(mark, box / (pid + ".sent"))
        except (OSError, ValueError, TypeError):
            continue
        return pid
    return None


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

    pid = approved_proposal(destination(data.get("tool_name"), tin, command), body)
    if pid is not None:
        decide("allow", f"ペインで承認済みの提案 {pid} と文面・送信先が一致します。")
        return 0
    decide("ask", "外部に送る文面です。送る前に内容を確認してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
