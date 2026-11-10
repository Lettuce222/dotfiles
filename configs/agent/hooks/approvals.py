#!/usr/bin/env python3
"""One-shot approvals for operations the user approved in the orchestrator.

The orchestrator writes one record per approved operation right after the user
approves it (AskUserQuestion). external-post-guard.py and approval-gate.py
then let exactly that operation run without a permission prompt, once, before
the record expires.

Records live in ~/hub/state/approvals/<id>.json (AGENT_APPROVALS_DIR, or
$AGENT_ORCHESTRATOR_HOME/state/approvals). A record is honored only when:

  - it has not expired (default 30 minutes),
  - the call matches it exactly:
      Bash: the whole command string (surrounding whitespace aside), and every
            body file the command reads (--body-file, -F key=@file, --input)
            still has the hash it had when the record was written;
      MCP:  the tool name, every non-prose top-level field, and the hash of
            the prose (Slack text, comment body, ...) taken from the draft
            (a record without a draft matches only calls without prose),
  - the call comes from the session the record is for. The hook's
    session_id is looked up in `claude agents --json`:
      a record without --thread is for the orchestrator (the entry named
        "orchestrator", AGENT_ORCHESTRATOR_NAME);
      a record with --thread <name> is for that background worker only, so
        a worker can run an operation the user approved in the orchestrator
        without a dialog nobody would answer.

A matching record is deleted before the call runs, so it works once.

Only the orchestrator writes records: `add` refuses unless the calling
session (CLAUDE_CODE_SESSION_ID) is the orchestrator, and approval-gate.py
denies tool calls from other sessions that would write records. Workers run as
the same user, so these checks catch mistakes; they are not a sandbox.

CLI (run by the orchestrator):
  approvals.py add bash --command '<exact command>' [--thread NAME] [--ttl SECONDS] [--note TEXT]
  approvals.py add mcp --tool <tool name> --params '<json of the other fields>'
                       [--body-file <draft> [--body-key text]] [--thread NAME] [--ttl] [--note]
  approvals.py list
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

DEFAULT_TTL = 30 * 60
PROSE_KEY = re.compile(r"^(body|description|commentBody|comment|text|message)$", re.I)


def approvals_dir():
    explicit = os.environ.get("AGENT_APPROVALS_DIR")
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("AGENT_ORCHESTRATOR_HOME") or "~/hub"
    return Path(home).expanduser() / "state" / "approvals"


def normalize(text):
    return text.replace("\r\n", "\n").strip()


def sha_text(text):
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def sha_file(path):
    p = Path(path).expanduser()
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def body_files(command):
    """Files a command reads its payload from: --body-file F, -F k=@F, --input F."""
    try:
        args = shlex.split(command)
    except ValueError:
        return []
    out = []
    for i, a in enumerate(args):
        nxt = args[i + 1] if i + 1 < len(args) else None
        if a in ("--body-file", "--input") and nxt is not None and nxt != "-":
            out.append(nxt)
        elif a.startswith(("--body-file=", "--input=")):
            out.append(a.split("=", 1)[1])
        elif a in ("-F", "--field") and nxt is not None:
            _, _, val = nxt.partition("=")
            if val.startswith("@") and val != "@-":
                out.append(val[1:])
    return list(dict.fromkeys(out))


# --- records ---------------------------------------------------------------


def new_record(kind, ttl, note, thread=None, **fields):
    now = time.time()
    return {
        "id": time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:8],
        "kind": kind,
        "created_at": now,
        "expires_at": now + ttl,
        "note": note or "",
        "thread": thread or None,
        **fields,
    }


def bash_record(command, ttl=DEFAULT_TTL, note="", thread=None):
    files = {}
    for f in body_files(command):
        digest = sha_file(f)
        if digest is None:
            raise ValueError(f"本文のファイルが読めません: {f}")
        files[f] = digest
    return new_record("bash", ttl, note, thread, command=command.strip(), files=files)


def mcp_record(tool, params, body_file=None, body_key=None, ttl=DEFAULT_TTL, note="", thread=None):
    if not isinstance(params, dict):
        raise ValueError("--params は JSON の object にする")
    if any(PROSE_KEY.match(k) for k in params):
        raise ValueError("本文は --params に入れず --body-file で渡す")
    if body_file is None:
        if body_key is not None:
            raise ValueError("--body-key には --body-file も付ける")
        # A call without prose (a reaction, a status change).
        return new_record("mcp", ttl, note, thread, tool=tool, params=params, body_key=None, body_sha256=None)
    p = Path(body_file).expanduser()
    if not p.is_file():
        raise ValueError(f"本文のファイルが読めません: {body_file}")
    if body_key is not None and not PROSE_KEY.match(body_key):
        raise ValueError(f"--body-key は本文の key にする: {body_key}")
    return new_record(
        "mcp",
        ttl,
        note,
        thread,
        tool=tool,
        params=params,
        body_key=body_key,
        body_sha256=sha_text(p.read_text()),
        body_file=str(p),
    )


def save(record, directory=None):
    d = directory or approvals_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{record['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    tmp.replace(path)
    return path


def load_all(directory=None, now=None):
    """Yield (path, record) for live records; delete expired or broken ones."""
    d = directory or approvals_dir()
    now = time.time() if now is None else now
    if not d.is_dir():
        return
    for path in sorted(d.glob("*.json")):
        try:
            rec = json.loads(path.read_text())
            expired = float(rec.get("expires_at", 0)) <= now
        except (OSError, ValueError, TypeError, AttributeError):
            expired = True
            rec = None
        if expired:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        yield path, rec


# --- matching --------------------------------------------------------------


def same_value(actual, expected):
    if actual == expected:
        return True
    return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def match(rec, tool_name, tool_input):
    """Return (matched, near_miss_reason)."""
    if rec.get("kind") == "bash":
        if tool_name != "Bash":
            return False, None
        if (tool_input.get("command") or "").strip() != rec.get("command"):
            return False, None
        for f, digest in (rec.get("files") or {}).items():
            if sha_file(f) != digest:
                return False, f"承認のあとに本文のファイルが変わりました: {f}"
        return True, None

    if rec.get("kind") == "mcp":
        if tool_name != rec.get("tool"):
            return False, None
        prose = {k: v for k, v in tool_input.items() if PROSE_KEY.match(k)}
        others = {k: v for k, v in tool_input.items() if not PROSE_KEY.match(k)}
        params = rec.get("params") or {}
        if set(others) != set(params) or not all(same_value(others[k], params[k]) for k in params):
            return False, None
        if rec.get("body_sha256") is None:
            return not prose, None
        key = rec.get("body_key")
        if key is not None:
            if set(prose) != {key}:
                return False, None
        elif len(prose) != 1:
            return False, None
        value = next(iter(prose.values()))
        if not isinstance(value, str) or sha_text(value) != rec.get("body_sha256"):
            return False, "承認のあとに本文が変わりました"
        return True, None

    return False, None


# --- sessions --------------------------------------------------------------


def orchestrator_name():
    return os.environ.get("AGENT_ORCHESTRATOR_NAME") or "orchestrator"


def agents(include_stopped=False):
    """Entries of `claude agents --json` (empty when claude is unavailable)."""
    claude = shutil.which("claude")
    if not claude:
        return []
    cmd = [claude, "agents", "--json"] + (["--all"] if include_stopped else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False).stdout
        data = json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def session_entry(session_id):
    """The `claude agents --json` entry of the running session with this id, or None."""
    if not session_id:
        return None
    for a in agents():
        if a.get("sessionId") == session_id:
            return a
    return None


def session_name(session_id):
    """Name of the running Claude Code session with this id, or None."""
    entry = session_entry(session_id)
    return entry.get("name") if entry else None


def is_orchestrator(entry):
    return bool(entry) and entry.get("name") == orchestrator_name()


def is_thread(entry):
    """A background session other than the orchestrator: a worker it started."""
    return (
        bool(entry)
        and entry.get("kind") == "background"
        and entry.get("name") not in (None, "", orchestrator_name())
    )


def allowed_for(rec, entry):
    """Whether the session described by entry may use the record."""
    thread = rec.get("thread")
    if thread:
        return is_thread(entry) and entry.get("name") == thread
    return is_orchestrator(entry)


def take(tool_name, tool_input, session_id, directory=None, now=None):
    """Consume the record that approves this call for this session.

    Returns (record, None) when approved, else (None, reason or None).
    """
    near_miss = None
    candidates = []
    for path, rec in load_all(directory, now):
        ok, why = match(rec, tool_name, tool_input)
        if ok:
            candidates.append((path, rec))
        elif why and not near_miss:
            near_miss = why
    if not candidates:
        return None, near_miss
    entry = session_entry(session_id)
    mine = [(p, r) for p, r in candidates if allowed_for(r, entry)]
    if not mine:
        return None, "承認の記録は、窓口か記録に書いた worker のセッションでだけ使えます"
    for path, rec in mine:
        try:
            path.unlink()
        except FileNotFoundError:
            continue  # someone else took it first
        return rec, None
    return None, near_miss


def has_records(directory=None):
    return any(True for _ in load_all(directory))


def writer_is_orchestrator():
    """`add` is run by the orchestrator's Bash, which sets CLAUDE_CODE_SESSION_ID."""
    return is_orchestrator(session_entry(os.environ.get("CLAUDE_CODE_SESSION_ID")))


def known_thread(name):
    return any(is_thread(a) and a.get("name") == name for a in agents(include_stopped=True))


# --- CLI -------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(prog="approvals.py", description="窓口で承認した操作を 1 回だけ通す記録")
    sub = ap.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add")
    kinds = add.add_subparsers(dest="kind", required=True)
    for name in ("bash", "mcp"):
        p = kinds.add_parser(name)
        p.add_argument("--ttl", type=int, default=DEFAULT_TTL, help="有効な秒数（既定 1800）")
        p.add_argument("--note", default="", help="何を承認したか（ダイアログの代わりに記録に残す）")
        p.add_argument("--thread", default=None, help="この記録を使える worker の名前（付けなければ窓口だけ）")
        if name == "bash":
            p.add_argument("--command", required=True, help="実行するコマンドそのもの")
        else:
            p.add_argument("--tool", required=True, help="MCP のツール名（mcp__…）")
            p.add_argument("--params", default="{}", help="本文以外の引数の JSON")
            p.add_argument("--body-file", default=None, help="本文の下書き（本文の無い呼び出しでは付けない）")
            p.add_argument("--body-key", default=None, help="本文を入れる key（text、body など）")

    sub.add_parser("list")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for _, rec in load_all():
            print(json.dumps(rec, ensure_ascii=False))
        return 0

    if not writer_is_orchestrator():
        print("approvals.py: 承認の記録を書けるのは窓口（orchestrator）のセッションだけです", file=sys.stderr)
        return 3
    if args.thread and not known_thread(args.thread):
        print(
            f"approvals.py: worker が見つかりません: {args.thread}（claude agents --json --all の name を書く）",
            file=sys.stderr,
        )
        return 2
    try:
        if args.kind == "bash":
            rec = bash_record(args.command, args.ttl, args.note, args.thread)
        else:
            rec = mcp_record(
                args.tool, json.loads(args.params), args.body_file, args.body_key, args.ttl, args.note, args.thread
            )
    except ValueError as e:
        print(f"approvals.py: {e}", file=sys.stderr)
        return 2
    print(save(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
