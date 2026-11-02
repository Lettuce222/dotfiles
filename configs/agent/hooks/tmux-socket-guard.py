#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): keep tmux experiments off the real server.

Inside tmux the TMUX variable decides which server a client talks to, and it
wins over TMUX_TMPDIR. A test that sets TMUX_TMPDIR (or unsets TMUX in a
different place than intended) and then runs `tmux kill-server` stops the
server everyone is working in. Only `-L <name>` and `-S <path>` reliably pick
another server.

Blocks with exit 2:
  1. `tmux kill-server` without -L or -S, in any session.
  2. A command that relies on TMUX_TMPDIR or `unset TMUX` to isolate tmux and
     runs tmux without -L or -S.

Only the command line is inspected; tmux calls inside scripts that the
command runs are not seen, so the rule in worker-rules.md still applies.
"""

import json
import re
import shlex
import sys

SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;", "\n"}
PREFIXES = {"env", "command", "exec", "builtin", "nohup", "time", "sudo"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# tmux global options that take a value (see tmux(1)).
VALUE_OPTS = set("cfLST")


def segments(command):
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    seg = []
    for tok in lexer:
        if tok in SEPARATORS:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def tmux_call(seg):
    """Return (has_socket, subcommand) if the segment runs tmux, else None."""
    i = 0
    while i < len(seg) and (ASSIGNMENT.match(seg[i]) or seg[i] in PREFIXES):
        if seg[i] == "env":
            # env -i, env -u NAME, ...
            while i + 1 < len(seg) and seg[i + 1].startswith("-"):
                i += 2 if seg[i + 1] in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string") else 1
        i += 1
    if i >= len(seg) or seg[i].rsplit("/", 1)[-1] != "tmux":
        return None
    has_socket = False
    i += 1
    while i < len(seg) and seg[i].startswith("-") and seg[i] != "--":
        flags = seg[i][1:]
        i += 1
        for j, f in enumerate(flags):
            if f in VALUE_OPTS:
                if f in "LS":
                    has_socket = True
                if j == len(flags) - 1:
                    i += 1  # value is the next word
                break
    if i < len(seg) and seg[i] == "--":
        i += 1
    sub = seg[i] if i < len(seg) else ""
    return has_socket, sub


def is_kill_server(sub):
    # tmux accepts any unambiguous prefix; "kill-ser" is the shortest.
    return sub == "kill-server" or (len(sub) >= len("kill-ser") and "kill-server".startswith(sub))


def problems(command):
    try:
        segs = list(segments(command))
    except ValueError:
        return []
    calls = [c for c in (tmux_call(s) for s in segs) if c is not None]
    out = []
    if any(is_kill_server(sub) and not sock for sock, sub in calls):
        out.append("-L も -S も付けない tmux kill-server は、いま使っている tmux サーバーを止めます。")
    relies_on_env = "TMUX_TMPDIR" in command or re.search(r"\bunset\s+(-\w+\s+)*TMUX\b|\benv\s+-u\s*TMUX\b", command)
    if relies_on_env and any(not sock for sock, _ in calls):
        out.append("TMUX_TMPDIR や unset TMUX では tmux サーバーを分けられません。tmux の中では TMUX が優先されます。")
    return out


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command", "")
    if "tmux" not in command:
        return 0
    found = problems(command)
    if not found:
        return 0
    print(
        "tmux のコマンドをブロックしました。\n" + "\n".join(found)
        + "\nテストや検証では、どの tmux コマンドにも -L <専用の名前> か -S <ソケットのパス> を付けてください。"
        "\nいつも使っているサーバーを本当に止めたいときは、ユーザーが自分で実行します。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
