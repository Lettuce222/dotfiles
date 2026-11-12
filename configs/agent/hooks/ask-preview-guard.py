#!/usr/bin/env python3
"""Claude Code PreToolUse hook (AskUserQuestion): keep previews readable in full.

Claude Code (checked on 2.1.322) shows an option's preview only when all of
it can be shown:

  - A preview longer than 2000 UTF-16 code units, or with a run of more than
    8 combining marks or zero-width characters, is withheld entirely. The pane
    then reads "(preview cannot be shown in full - compare the option labels
    and descriptions instead)".
  - A shown preview is wrapped at (terminal columns - 38) and cut after
    (terminal rows - 26) lines; the rest becomes "N lines hidden".

A question text longer than 2000 code units is cut with an ellipsis.

This hook blocks (exit 2) an AskUserQuestion call whose preview would be
withheld or cut, or whose question text would be cut, so the body goes into
the reply above the question instead. The terminal size comes from the tmux
pane of the session ($TMUX_PANE), then from the controlling terminal, then
from DEFAULT_SIZE.

`ask-preview-guard.py --check <file>...` applies the same limits to drafts:
it prints one line per file and exits 1 if any file does not fit, 2 if a file
is missing, 0 otherwise.
"""

import json
import os
import re
import subprocess
import sys
import unicodedata

MAX_UNITS = 2000
MAX_MARK_RUN = 8
# Columns and rows that the AskUserQuestion dialog takes besides the preview
# text, plus a little margin for the banner rows Claude Code adds.
WIDTH_TAKEN = 38
HEIGHT_TAKEN = 26 + 2
DEFAULT_SIZE = (100, 40)
TABLE_ROW = re.compile(r"^\s*\|")

ADVICE = (
    "本文は AskUserQuestion の直前の返事に全文を載せ、preview には要点と下書きの "
    "file:// のリンクだけを置く（agents-orchestrator の「承認をもらって実行する」の 1）。"
    "本文を切って preview に押し込まない。"
)


def units(text):
    return len(text.encode("utf-16-le")) // 2


def width(text):
    total = 0
    for ch in text:
        if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def zero_width(ch):
    return unicodedata.category(ch) in ("Mn", "Me", "Mc", "Cf") or ch in "︎️⠀"


def longest_mark_run(text):
    best = run = 0
    for ch in text:
        run = run + 1 if zero_width(ch) else 0
        best = max(best, run)
    return best


def terminal_size():
    pane = os.environ.get("TMUX_PANE")
    if pane and os.environ.get("TMUX"):
        try:
            out = subprocess.run(
                ["tmux", "display-message", "-p", "-t", pane, "#{pane_width} #{pane_height}"],
                capture_output=True, text=True, timeout=3, check=True,
            ).stdout.split()
            return int(out[0]), int(out[1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
        try:
            size = os.get_terminal_size(fd)
            return size.columns, size.lines
        finally:
            os.close(fd)
    except OSError:
        return DEFAULT_SIZE


def shown_lines(text, wrap):
    lines = text.split("\n")
    table_rows = sum(1 for line in lines if TABLE_ROW.match(line))
    count = sum(max(1, -(-width(line) // wrap)) for line in lines)
    # A rendered Markdown table gets border lines between and around the rows.
    return count + (table_rows + 1 if table_rows else 0)


def problems(text, size):
    """Return the reasons a preview of `text` would not be shown in full."""
    cols, rows = size
    wrap = max(1, cols - WIDTH_TAKEN)
    limit = max(1, rows - HEIGHT_TAKEN)
    found = []
    n = units(text)
    if n > MAX_UNITS:
        found.append(f"{n} 文字あり、{MAX_UNITS} 文字を超えるので preview が丸ごと伏せられる")
    if longest_mark_run(text) > MAX_MARK_RUN:
        found.append(f"結合文字やゼロ幅の文字が {MAX_MARK_RUN} 個より多く続くので preview が丸ごと伏せられる")
    if any(TABLE_ROW.match(line) and width(line) > wrap for line in text.split("\n")):
        found.append(f"表の行が幅 {wrap} を超え、表が崩れる")
    lines = shown_lines(text, wrap)
    if lines > limit:
        found.append(f"折り返して {lines} 行になり、見える {limit} 行（端末 {cols}x{rows}）を超えた分が切られる")
    return found


def check_tool_input(tool_input, size):
    messages = []
    for q_index, question in enumerate(tool_input.get("questions") or [], 1):
        if not isinstance(question, dict):
            continue
        text = question.get("question")
        if isinstance(text, str) and units(text) > MAX_UNITS:
            messages.append(f"問い {q_index}: 問いの文が {MAX_UNITS} 文字を超えるので末尾が切られる")
        for option in question.get("options") or []:
            if not isinstance(option, dict) or not isinstance(option.get("preview"), str):
                continue
            for reason in problems(option["preview"], size):
                messages.append(f"問い {q_index} の「{option.get('label', '')}」の preview: {reason}")
    return messages


def main_hook():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("tool_name") != "AskUserQuestion":
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    messages = check_tool_input(tool_input, terminal_size())
    if not messages:
        return 0
    print("AskUserQuestion の本文がユーザーに全部は見えない。", file=sys.stderr)
    for message in messages:
        print(f"- {message}", file=sys.stderr)
    print(ADVICE, file=sys.stderr)
    return 2


def main_check(paths):
    size = terminal_size()
    status = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError as e:
            print(f"{path}: 読めない（{e.strerror}）")
            status = 2
            continue
        found = problems(text, size)
        if found:
            print(f"{path}: preview に全部は出ない: " + " / ".join(found))
            status = max(status, 1)
        else:
            print(f"{path}: preview に全部出る（{units(text)} 文字、{shown_lines(text, max(1, size[0] - WIDTH_TAKEN))} 行、端末 {size[0]}x{size[1]}）")
    return status


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        if len(sys.argv) < 3:
            print("usage: ask-preview-guard.py --check <file>...", file=sys.stderr)
            sys.exit(2)
        sys.exit(main_check(sys.argv[2:]))
    sys.exit(main_hook())
