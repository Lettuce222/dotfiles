#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): keep agents off the buttons people press.

A person approves an operation by pressing a button: an answer in the
orchestrator, a card in the Hub (local) panel of Orca. An agent that could
press those buttons, or type into the session that asks, could approve its
own operation. This hook stops the commands that do that, in every session:

  - the Orca CLI, except the subcommands that only read (status, worktree
    ps/list/show/current, terminal list/read/show, agent list/show/read, the
    plugin commands that check a folder, repo list/show, project list,
    agent-context, help). Writes include `orca computer` (clicks and typing
    in Orca's window), `orca terminal send`, and `orca plugin dev request`,
    `dev load`, `install`, `update`, `enable`, `catalog add`, which call the
    panel's handlers or swap its code. `orca plugin shot --act` presses the
    panel's controls, so only a plain shot passes;
  - `osascript` scripts that drive the UI through System Events (click,
    keystroke, key code), and `cliclick`;
  - tmux commands that type into a pane (send-keys, send-prefix,
    paste-buffer), that run commands from a file or stdin (source-file,
    `tmux -C`), on the server everyone works in. `-L` and `-S` pick another
    server, so tests that use them pass.

With --panel, a stopped command of the orchestrator is first asked in the Hub
panel (asks.panel_decision), up to AGENT_PERMISSION_WAIT seconds: the panel's
allow or deny is returned, and only without one does the hook ask, so the
terminal shows no dialog while the panel can still answer.

When a command is stopped, a one-shot approval for this exact call and this
session (approvals.py) lets it through once, as for gh writes. Without one the
hook asks: a person sees the dialog in an interactive session, and in a worker
approval-gate.py turns the dialog into "report it to the orchestrator".
approval-gate.py leaves these calls to this hook, so the two never take the
same record.

Only the command line is read. Commands inside scripts the command runs, the
Orca CLI started through node, and code written to do the same are not seen:
the agents run as the same user, so this catches mistakes and plain attempts;
it is not a sandbox.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

ORCA_READS = {
    "status": None,
    "agent-context": None,
    "help": None,
    "worktree": {"ps", "list", "show", "current"},
    "terminal": {"list", "read", "show"},
    "agent": {"list", "show", "read"},
    "plugin": {"list", "logs", "validate", "inspect", "test", "check", "types", "release-entry", "shot"},
    "repo": {"list", "show"},
    "project": {"list"},
}
# Global options of the Orca CLI that take a value.
ORCA_VALUE_OPTS = {"--environment", "--pairing-code"}
SHOT_ACTS = {"--act", "--scenario", "--in-place"}

UI_SCRIPT = re.compile(r"system\s+events|\bkeystroke\b|\bkey\s+code\b|\bclick\b", re.I)

TMUX_VALUE_OPTS = set("cfLST")
TMUX_TYPING = re.compile(
    r"(?:^|[\s;'\"{])(send-keys|send|send-prefix|paste-buffer|pasteb|source-file|source)(?=$|[\s;'\"}])"
)
TMUX_TYPING_NAMES = {"send-keys", "send", "send-prefix", "paste-buffer", "pasteb", "source-file", "source"}


def load_guard():
    """external-post-guard.py, for its shell command splitting."""
    spec = importlib.util.spec_from_file_location("external_post_guard", HERE / "external-post-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GUARD = load_guard()


def strip_wrappers(argv):
    i = 0
    while i < len(argv):
        if GUARD.ASSIGNMENT.match(argv[i]):
            i += 1
        elif argv[i] in GUARD.WRAPPERS:
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or GUARD.ASSIGNMENT.match(argv[i])):
                i += 1
        else:
            break
    return argv[i:]


def calls(command, depth=0):
    """argv lists of every simple command, descending into sh -c, eval and $(...)."""
    out = []
    for argv in GUARD.simple_commands(command):
        if depth < 3:
            for tok in argv:
                for inner in GUARD.substitutions(tok):
                    out += calls(inner, depth + 1)
        argv = strip_wrappers(argv)
        if not argv:
            continue
        name = os.path.basename(argv[0])
        if depth < 3 and name in GUARD.SHELLS and "-c" in argv[1:-1]:
            out += calls(argv[argv.index("-c") + 1], depth + 1)
        elif depth < 3 and name == "eval":
            out += calls(" ".join(argv[1:]), depth + 1)
        else:
            out.append(argv)
    return out


def orca_problem(args):
    words = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--help", "-h", "--version"):
            return None
        if arg in ORCA_VALUE_OPTS:
            i += 2
            continue
        if not arg.startswith("-"):
            words.append(arg)
        i += 1
    if not words:
        return None
    group = words[0]
    if group not in ORCA_READS:
        return f"orca {group}"
    subs = ORCA_READS[group]
    if subs is None:
        return None
    sub = words[1] if len(words) > 1 else ""
    if sub not in subs:
        return f"orca {group} {sub}".rstrip()
    if (group, sub) == ("plugin", "shot") and any(a.split("=", 1)[0] in SHOT_ACTS for a in args):
        return "orca plugin shot --act"
    return None


def script_text(args):
    """The AppleScript or JXA that osascript would run, from -e or a file."""
    parts = []
    i = 0
    while i < len(args):
        if args[i] == "-e" and i + 1 < len(args):
            parts.append(args[i + 1])
            i += 2
        elif args[i] in ("-l", "-s") and i + 1 < len(args):
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            path = Path(args[i]).expanduser()
            try:
                parts.append(path.read_text(errors="replace"))
            except OSError:
                return None  # unreadable or stdin: cannot tell
            break
    if not parts:
        return None  # the script comes from stdin
    return "\n".join(parts)


def tmux_problem(args):
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        flags = args[i][1:]
        i += 1
        for j, f in enumerate(flags):
            if f in "LS":
                return None  # another server
            if f == "C":
                return "tmux -C"
            if f in TMUX_VALUE_OPTS:
                if j == len(flags) - 1:
                    i += 1
                break
    rest = args[i:]
    if rest[:1] == ["--"]:
        rest = rest[1:]
    if not rest:
        return None
    sub = rest[0]
    if sub in TMUX_TYPING_NAMES or (len(sub) >= 5 and "send-keys".startswith(sub)):
        return f"tmux {sub}"
    # Later commands of a chain (`\;`), and commands quoted for if-shell, run-shell, bind-key.
    for tok in rest[1:]:
        found = TMUX_TYPING.search(tok)
        if found:
            return f"tmux {found.group(1)}"
    return None


HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
RAW_CALL = re.compile(r"(^|[\s;&|(`])(?:\S*/)?(orca|cliclick|osascript)(?=\s|$)|\btmux\b.*\b(send|paste|source)")


def split_heredocs(command):
    """The command lines without heredoc bodies, and the bodies a shell would run.

    A heredoc body is data for the command's stdin (a script for python, a file for cat), not
    commands, and an apostrophe in it would make the whole line unreadable. A body fed to a shell
    (`sh <<EOF`) is commands, so it is read as such.
    """
    lines = command.split("\n")
    kept, run = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for match in HEREDOC.finditer(line):
            word = match.group(2)
            body = []
            while i < len(lines) and lines[i].strip() != word:
                body.append(lines[i])
                i += 1
            i += 1  # the terminator
            before = line[: match.start()]
            if re.search(r"(^|[\s;&|(])(?:\S*/)?(sh|bash|zsh|dash|fish)(\s+-\S+)*\s*$", before):
                run.append("\n".join(body))
    return "\n".join(kept), run


def problems(command):
    command, scripts = split_heredocs(command)
    out = [p for script in scripts for p in problems(script)]
    try:
        argvs = calls(command)
    except ValueError:
        # Unparsable (unbalanced quotes): look at the raw text conservatively.
        if RAW_CALL.search(command):
            out.append("読めないコマンドの中の orca・osascript・cliclick・tmux")
        return out
    for argv in argvs:
        name = os.path.basename(argv[0])
        args = argv[1:]
        found = None
        if name == "orca":
            found = orca_problem(args)
        elif name == "cliclick":
            found = "cliclick"
        elif name == "osascript":
            text = script_text(args)
            if text is None or UI_SCRIPT.search(text):
                found = "osascript の UI 操作"
        elif name == "tmux":
            found = tmux_problem(args)
        elif name in TMUX_TYPING_NAMES and name.startswith(("send", "paste")):
            # A tmux command after an escaped `\;`, split off by the shell splitter.
            found = f"tmux {name}"
        if found:
            out.append(found)
    return out


def decide(decision, reason):
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                "permissionDecisionReason": reason}},
        sys.stdout,
        ensure_ascii=False,
    )


def take_approval(data):
    sys.path.insert(0, str(HERE))
    sys.dont_write_bytecode = True  # keep __pycache__ out of the hooks directory
    try:
        import approvals
    except ImportError:
        return None, None
    return approvals.take(data.get("tool_name"), data.get("tool_input") or {}, data.get("session_id"))


def ask_panel(data):
    """With --panel, the orchestrator's call goes to the Hub panel before the dialog.

    A PreToolUse hook finishes before the dialog shows, so while this waits the terminal shows
    nothing. The panel's allow or deny is returned; None leaves the call to the dialog.
    """
    sys.path.insert(0, str(HERE))
    sys.dont_write_bytecode = True
    try:
        import approvals
        import asks
    except ImportError:
        return None
    entry = approvals.session_entry(data.get("session_id"))
    if not approvals.is_orchestrator(entry):
        return None
    return asks.panel_decision(entry, data)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if not re.search(r"orca|osascript|cliclick|tmux|send|paste", command):
        return 0
    found = problems(command)
    if not found:
        return 0
    record, why = take_approval(data)
    if record:
        decide("allow", "承認済みの操作です: " + (record.get("note") or record.get("id", "")))
        return 0
    reason = (
        "人が押すボタンや、ほかのセッションへの入力に届く操作です（" + "、".join(dict.fromkeys(found)) + "）。"
        "エージェントが自分の操作を承認できないように止めています。実行してよいか、人が確かめてください。"
    )
    decision = ask_panel(data) if "--panel" in argv else None
    if decision and decision["behavior"] == "allow":
        decide("allow", "Hub (local) のデスクでユーザーが許可しました（今回だけ）。")
        return 0
    if decision:
        decide("deny", decision["message"])
        return 0
    decide("ask", reason + (f"\n\n（{why}）" if why else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
