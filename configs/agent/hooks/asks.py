#!/usr/bin/env python3
"""Asks: what a worker wants from the user, as files the Hub (local) panel shows as cards.

A worker (a `claude --bg` session the orchestrator started) that stops for the
user writes one ask besides its report to the orchestrator. The Hub panel of
Orca reads the asks and shows each as a card; a person presses an answer there
or in the orchestrator, and whoever answers first takes the ask.

An ask is not an approval. Approvals are records only the orchestrator (and,
from stage 3 on, the Hub panel) writes; see approvals.py. A card answer is sent
to the worker as text, and text never lets a guarded operation through.

Asks live in ~/hub/state/asks/<id>.json (AGENT_ASKS_DIR, or
$AGENT_ORCHESTRATOR_HOME/state/asks). The answer is <id>.answer.json, created
with O_EXCL, so one answer wins when the panel and the orchestrator answer at
once.

CLI:
  asks.py decide --question <text> --option '<label>|<what the worker does>' ...
                 [--recommended N] [--case SLUG] [--level B]
      A question with 2-4 options (the worker's 「要判断」 that is not an approval).
  asks.py next --suggest '<label>|<prompt>|<reason>' ... [--case SLUG] [--level B]
      Up to 3 next steps a finished worker suggests; the prompt is what the panel
      sends to the worker when one is pressed.
  asks.py question --question <text> --option '<label>|<description>' ... [--body <file>]
                   [--approval] [--recommended N] [--case SLUG]
      The orchestrator's own question to the user, shown only in the Hub panel (panel-mode):
      the question, the whole body read from <file> as one text (a draft to send, a command to
      run; never split into pages), and the options, which are only the real answers.
      --approval marks a question whose answer the orchestrator turns into an approval record.
  asks.py verify <id>
      The answer the panel gave to an orchestrator's question, as JSON, only when the answer file
      was written by the panel (`--by panel`) for the ask as it is now (same hash). Exit 0 with
      {"id", "choice", "label", "description", "text", "approval"}; 4 otherwise, with the reason.
  asks.py list [--json] [--all]
      Open asks (with --all, answered ones too).
  asks.py answer <id> --by panel|orchestrator --choice <text> [--shown <sha256>] [--text <written answer>]
      Take the ask. --shown is the sha256 of the ask file as the card showed it;
      a changed file is refused. Exit 0 when taken, 3 when someone answered
      first, 4 when the ask is gone or changed. Prints the ask as JSON.
      For an orchestrator's question, `--by panel` is written only from the Hub panel: the
      parent process must be Orca's plugin host (Orca Helper) whose parent is Orca itself, with
      no Claude Code session around it. Agents run under a shell or Orca's terminal daemon.
  asks.py claim <id>
      The orchestrator takes the ask to ask the user in its own window.
      A permission (below) can be neither claimed nor answered by the orchestrator.
  asks.py close <id> | close --worker NAME
      Remove an ask and its answer (the orchestrator, when it removes a worker).

Permissions (kind "permission") are written by approval-gate.py, not from the command line: when
the orchestrator's Claude Code is about to show a permission dialog, the hook writes the call
(new_permission) and waits for the panel's answer (wait_permission): allow, deny (with an optional
reason in --text) or terminal (show the dialog now). Only the Hub panel answers one, with the hash
of the ask as its card showed it, and the hook uses the answer only when that hash is the one of
the bytes it wrote. Anything else leaves the dialog to the terminal.

decide and next run in the worker: the worker's name, session and cwd come from
CLAUDE_CODE_SESSION_ID and `claude agents --json`, never from arguments. A new
ask from a session replaces the open asks that session wrote before.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")
LEVELS = ("C", "B", "A", "S")
NOT_WORKERS = {"chore-hub-watch"}
LIMITS = {
    "question": 1000,
    "option_label": 60,
    "option_description": 300,
    # The same limits as the `next` block of Orca terminal agents (orca-milestone's parseSuggestions).
    "suggest_label": 30,
    "suggest_prompt": 300,
    "suggest_reason": 80,
}
EXIT_TAKEN = 3
ORCA_HELPER = "/Applications/Orca.app/Contents/Frameworks/Orca Helper.app/Contents/MacOS/Orca Helper"
ORCA_MAIN = "/Applications/Orca.app/Contents/MacOS/Orca"
BODY_MAX = 50000
EXIT_GONE = 4
PERMISSION_CHOICES = ("allow", "deny", "terminal")
# Calls whose dialog is a question to the user, answered in the orchestrator's own way.
NOT_PANEL_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
PERMISSION_INPUT_MAX = 50000
PERMISSION_POLL = 0.5


class AskError(Exception):
    pass


def hub_home():
    return Path(os.environ.get("AGENT_ORCHESTRATOR_HOME") or Path.home() / "hub")


def asks_dir():
    explicit = os.environ.get("AGENT_ASKS_DIR")
    return Path(explicit) if explicit else hub_home() / "state" / "asks"


def orchestrator_name():
    return os.environ.get("AGENT_ORCHESTRATOR_NAME") or "orchestrator"


def agents():
    claude = shutil.which("claude") or "claude"
    try:
        out = subprocess.run([claude, "agents", "--json"], capture_output=True, text=True, timeout=15, check=False)
        data = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return data if isinstance(data, list) else []


def caller():
    """The background worker that runs this command."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        raise AskError("Claude Code のセッションの中で実行してください（CLAUDE_CODE_SESSION_ID がありません）")
    entry = next((a for a in agents() if isinstance(a, dict) and a.get("sessionId") == session_id), None)
    if not entry or entry.get("kind") != "background" or not entry.get("name"):
        raise AskError("依頼を書けるのは claude --bg の worker だけです")
    if entry["name"] == orchestrator_name() or entry["name"] in NOT_WORKERS:
        raise AskError("窓口と見張りは依頼を書きません")
    return entry


def orchestrator_caller():
    """The orchestrator session that runs this command."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    entry = next((a for a in agents() if isinstance(a, dict) and a.get("sessionId") == session_id), None) if session_id else None
    if not entry or entry.get("name") != orchestrator_name():
        raise AskError("窓口の問いを書けるのは窓口（orchestrator）だけです")
    return entry


def process(pid):
    """(parent pid, executable path) of a process, or (None, None)."""
    try:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, None
    ppid, _, path = out.partition(" ")
    try:
        return int(ppid), path.strip()
    except ValueError:
        return None, None


def from_panel(read=process, env=None):
    """Whether this runs from the Hub panel: Orca's plugin host, a child of Orca, no Claude session."""
    env = os.environ if env is None else env
    if env.get("CLAUDE_CODE_SESSION_ID"):
        return False
    ppid, path = read(os.getppid())
    if path != ORCA_HELPER or ppid is None:
        return False
    _, grand = read(ppid)
    return grand == ORCA_MAIN


def check_text(text, limit, what, multiline=False):
    text = (text or "").strip()
    if not text:
        raise AskError(f"{what}が空です")
    if len(text) > limit:
        raise AskError(f"{what}は {limit} 文字までです（{len(text)} 文字）")
    bad = CONTROL.search(text) or (not multiline and "\n" in text)
    if bad:
        raise AskError(f"{what}に改行や見えない文字があります")
    return text


def parse_option(raw):
    label, sep, description = raw.partition("|")
    if not sep:
        raise AskError(f"選択肢は '<label>|<選ばれたら何をするか>' の形で書いてください: {raw}")
    return {
        "label": check_text(label, LIMITS["option_label"], "選択肢の label"),
        "description": check_text(description, LIMITS["option_description"], "選択肢の説明", multiline=True),
    }


def parse_suggestion(raw):
    parts = raw.split("|")
    if len(parts) != 3:
        raise AskError(f"次の作業は '<label>|<依頼文>|<理由>' の形で書いてください: {raw}")
    label, prompt, reason = parts
    prompt = check_text(prompt, LIMITS["suggest_prompt"], "依頼文")
    if prompt.startswith("-"):
        raise AskError("依頼文を - で始めないでください")
    return {
        "label": check_text(label, LIMITS["suggest_label"], "次の作業の label"),
        "prompt": prompt,
        "reason": check_text(reason, LIMITS["suggest_reason"], "理由"),
    }


def report_of(name):
    path = hub_home() / "workers" / name / "report.md"
    return str(path) if path.is_file() else None


def new_ask(kind, entry, case=None, level="B", **fields):
    if case is not None and not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", case):
        raise AskError(f"案件の名前ではありません: {case}")
    if level not in LEVELS:
        raise AskError(f"level は {', '.join(LEVELS)} のどれかです")
    now = time.time()
    return {
        "id": time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:8],
        "kind": kind,
        "created_at": now,
        "worker": entry["name"],
        "session_id": entry["sessionId"],
        "job_id": entry.get("id"),
        "cwd": entry.get("cwd"),
        "case": case,
        "report": report_of(entry["name"]),
        "level": level,
        **fields,
    }


def path_of(ask_id, directory=None):
    if not ID.match(ask_id or ""):
        raise AskError(f"依頼の id ではありません: {ask_id}")
    return (directory or asks_dir()) / f"{ask_id}.json"


def answer_path(path):
    return path.with_name(path.stem + ".answer.json")


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_asks(directory=None, include_answered=False):
    d = directory or asks_dir()
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob("*.json")):
        if path.name.endswith(".answer.json") or not ID.match(path.stem):
            continue
        answered = answer_path(path).exists()
        if answered and not include_answered:
            continue
        ask = load(path)
        if isinstance(ask, dict):
            out.append({**ask, "answered": answered})
    return out


def remove(path):
    for p in (answer_path(path), path):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def save(ask, directory=None, replace=True):
    d = directory or asks_dir()
    d.mkdir(parents=True, exist_ok=True)
    # A new ask replaces what the same session asked before and nobody answered.
    for old in all_asks(d) if replace else []:
        if old.get("session_id") == ask["session_id"]:
            remove(path_of(old["id"], d))
    path = path_of(ask["id"], d)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(ask, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def answer(ask_id, by, choice, shown=None, directory=None, text=None, panel_check=from_panel):
    """Take an ask. Returns (exit code, ask or None)."""
    path = path_of(ask_id, directory)
    if not path.is_file():
        return EXIT_GONE, None
    if shown and sha_file(path) != shown:
        return EXIT_GONE, None
    current = load(path) or {}
    if current.get("kind") == "permission":
        check_permission_answer(current, by, choice, shown, text, panel_check)
    if current.get("kind") == "question" and by == "panel":
        if not shown:
            raise AskError("窓口の問いには、カードに出した中身の hash（--shown）が要ります")
        if not panel_check():
            raise AskError("窓口の問いにパネルとして答えられるのは、Orca の Hub パネルだけです")
    record = {"by": by, "at": time.time(), "choice": choice, "shown_sha256": shown}
    if text is not None:
        record["text"] = check_text(text, 2000, "書いた答え", multiline=True)
    try:
        fd = os.open(answer_path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return EXIT_TAKEN, load(path)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    return 0, load(path)


def check_permission_answer(ask, by, choice, shown, text, panel_check):
    if by != "panel":
        raise AskError("許可の確認に答えられるのは Hub パネルだけです")
    if not shown:
        raise AskError("許可の確認には、カードに出した中身の hash（--shown）が要ります")
    if choice not in PERMISSION_CHOICES:
        raise AskError(f"許可の確認の答えは {', '.join(PERMISSION_CHOICES)} のどれかです")
    if text is not None and choice != "deny":
        raise AskError("理由を書けるのは拒否のときだけです")
    if (ask.get("expires_at") or 0) < time.time():
        raise AskError("許可の確認の期限が過ぎました（ターミナルで答えてください）")
    if not panel_check():
        raise AskError("許可の確認に答えられるのは、Orca の Hub パネルだけです")


def new_permission(entry, tool_name, tool_input, wait, agent_type=None, permission_mode=None, directory=None):
    """Write the ask for a permission dialog of the orchestrator. (path, sha256 of the bytes) or None."""
    if tool_name in NOT_PANEL_TOOLS or not isinstance(tool_input, dict):
        return None
    if len(json.dumps(tool_input, ensure_ascii=False)) > PERMISSION_INPUT_MAX:
        return None  # a card could not show it in full
    ask = new_ask("permission", entry, None, "B", tool_name=tool_name, tool_input=tool_input,
                  agent_type=agent_type, permission_mode=permission_mode)
    ask["expires_at"] = ask["created_at"] + wait
    # The orchestrator may wait on several calls at once.
    path = save(ask, directory, replace=False)
    return path, sha_file(path)


def permission_answer(path, sha):
    """The panel's answer to a permission, once there is one.

    None while there is none; {"choice": "invalid"} when the ask changed after it was written or
    the answer is not the panel's for the ask as written; else {"choice": allow|deny|terminal, "text"}.
    """
    try:
        if sha_file(path) != sha:
            return {"choice": "invalid"}
    except OSError:
        return {"choice": "invalid"}
    answer_file = answer_path(path)
    if not answer_file.exists():
        return None
    record = load(answer_file)
    if record is None:
        return None  # still being written
    if record.get("by") != "panel" or record.get("shown_sha256") != sha or record.get("choice") not in PERMISSION_CHOICES:
        return {"choice": "invalid"}
    text = record.get("text") if record.get("choice") == "deny" else None
    return {"choice": record["choice"], "text": text if isinstance(text, str) else None}


def wait_permission(path, sha, wait, poll=PERMISSION_POLL, clock=time.monotonic, sleep=time.sleep):
    """Waits up to `wait` seconds for the panel's answer; None when none came."""
    end = clock() + wait
    while True:
        got = permission_answer(path, sha)
        if got is not None:
            return got
        if clock() >= end:
            return None
        sleep(poll)


def cmd_decide(args):
    options = [parse_option(o) for o in args.option]
    if not 2 <= len(options) <= 4:
        raise AskError("選択肢は 2〜4 個にしてください")
    if args.recommended is not None and not 1 <= args.recommended <= len(options):
        raise AskError("--recommended は選択肢の番号（1 から）です")
    ask = new_ask(
        "decide", caller(), args.case, args.level,
        question=check_text(args.question, LIMITS["question"], "問い", multiline=True),
        options=options, recommended=args.recommended,
    )
    print(save(ask))
    return 0


def cmd_next(args):
    suggestions = [parse_suggestion(s) for s in args.suggest]
    if not 1 <= len(suggestions) <= 3:
        raise AskError("次の作業は 1〜3 件にしてください")
    print(save(new_ask("next", caller(), args.case, args.level, suggestions=suggestions)))
    return 0


def read_body(file):
    if file is None:
        return None
    try:
        body = open(os.path.expanduser(file), encoding="utf-8").read()
    except OSError as e:
        raise AskError(f"本文のファイルを読めません: {file}: {e.strerror}")
    if not body.strip() or len(body) > BODY_MAX:
        raise AskError(f"本文は空でなく {BODY_MAX} 文字までです: {file}")
    return body


def cmd_question(args):
    options = [parse_option(o) for o in args.option]
    if not 2 <= len(options) <= 9:
        raise AskError("選択肢は 2〜9 個にしてください")
    if args.recommended is not None and not 1 <= args.recommended <= len(options):
        raise AskError("--recommended は選択肢の番号（1 から）です")
    ask = new_ask(
        "question", orchestrator_caller(), args.case, "B",
        question=check_text(args.question, LIMITS["question"] * 4, "問い", multiline=True),
        body=read_body(args.body), body_file=os.path.abspath(os.path.expanduser(args.body)) if args.body else None,
        options=options, recommended=args.recommended, approval=bool(args.approval),
    )
    # The orchestrator may wait on several questions at once.
    print(save(ask, replace=False))
    return 0


def verify(ask_id, directory=None):
    """(exit code, answer or reason) for an orchestrator's question answered in the panel."""
    path = path_of(ask_id, directory)
    ask = load(path) if path.is_file() else None
    if not ask or ask.get("kind") != "question":
        return EXIT_GONE, "窓口の問いが見つかりません"
    record = load(answer_path(path))
    if not record:
        return EXIT_GONE, "まだ答えがありません"
    if record.get("by") != "panel":
        return EXIT_GONE, "パネルの答えではありません"
    if record.get("shown_sha256") != sha_file(path):
        return EXIT_GONE, "パネルに出したあとに問いが変わりました"
    out = {"id": ask_id, "approval": bool(ask.get("approval")), "choice": None, "label": None, "description": None, "text": record.get("text")}
    if record.get("text") is None:
        try:
            index = int(record.get("choice"))
            picked = ask["options"][index - 1]
        except (TypeError, ValueError, IndexError):
            return EXIT_GONE, "答えの選択肢が問いにありません"
        if index < 1:
            return EXIT_GONE, "答えの選択肢が問いにありません"
        out.update(choice=index, label=picked["label"], description=picked["description"])
    return 0, out


def cmd_verify(args):
    code, out = verify(args.id)
    if code == 0:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"asks: {out}", file=sys.stderr)
    return code


def cmd_list(args):
    items = all_asks(include_answered=args.all)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    for ask in items:
        head = ask.get("question") or " / ".join(s["label"] for s in ask.get("suggestions", [])) or f"許可の確認: {ask.get('tool_name')}"
        mark = " (答え済み)" if ask["answered"] else ""
        print(f"{ask['id']}  {ask['kind']:<6} {ask['worker']}  {head.splitlines()[0][:60]}{mark}")
    return 0


def cmd_answer(args):
    code, ask = answer(args.id, args.by, args.choice, args.shown, text=args.text)
    if ask is not None:
        print(json.dumps(ask, ensure_ascii=False))
    if code == EXIT_TAKEN:
        print("ほかの人がもう答えています", file=sys.stderr)
    elif code == EXIT_GONE:
        print("依頼が無いか、カードを出したあとに変わりました", file=sys.stderr)
    return code


def cmd_close(args):
    if args.worker:
        closed = [a["id"] for a in all_asks(include_answered=True) if a.get("worker") == args.worker]
    elif args.id:
        closed = [args.id]
    else:
        raise AskError("<id> か --worker を渡してください")
    for ask_id in closed:
        remove(path_of(ask_id))
        print(ask_id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="asks.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--question", required=True)
    d.add_argument("--option", action="append", required=True)
    d.add_argument("--recommended", type=int)
    n = sub.add_parser("next")
    n.add_argument("--suggest", action="append", required=True)
    for p in (d, n):
        p.add_argument("--case")
        p.add_argument("--level", default="B")
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--all", action="store_true")
    a = sub.add_parser("answer")
    a.add_argument("id")
    a.add_argument("--by", required=True, choices=("panel", "orchestrator"))
    a.add_argument("--choice", required=True)
    a.add_argument("--shown")
    a.add_argument("--text")
    q = sub.add_parser("question")
    q.add_argument("--question", required=True)
    q.add_argument("--option", action="append", required=True)
    q.add_argument("--body")
    q.add_argument("--approval", action="store_true")
    q.add_argument("--recommended", type=int)
    q.add_argument("--case")
    v = sub.add_parser("verify")
    v.add_argument("id")
    c = sub.add_parser("claim")
    c.add_argument("id")
    cl = sub.add_parser("close")
    cl.add_argument("id", nargs="?")
    cl.add_argument("--worker")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "decide":
            return cmd_decide(args)
        if args.cmd == "next":
            return cmd_next(args)
        if args.cmd == "question":
            return cmd_question(args)
        if args.cmd == "verify":
            return cmd_verify(args)
        if args.cmd == "list":
            return cmd_list(args)
        if args.cmd == "answer":
            return cmd_answer(args)
        if args.cmd == "claim":
            args.by, args.choice, args.shown, args.text = "orchestrator", "claimed", None, None
            return cmd_answer(args)
        return cmd_close(args)
    except AskError as e:
        print(f"asks: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
