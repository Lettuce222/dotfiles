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

The user reads the body only in the question dialog: the chat above it keeps
moving, so a question must not send the user back to an earlier reply.

This hook blocks (exit 2) an AskUserQuestion call whose preview would be
withheld or cut, whose question text would be cut, or whose question, header,
label or description points the user to an earlier reply ("上の返事" and the
like). A long body is split into pages, one page per option preview, with
`--pages`. The terminal size comes from the tmux pane of the session
($TMUX_PANE), then from the controlling terminal, then from DEFAULT_SIZE.

`ask-preview-guard.py --check <file>...` applies the same limits to drafts:
it prints one line per file and exits 1 if any file does not fit, 2 if a file
is missing, 0 otherwise.

`ask-preview-guard.py --pages <file>...` splits the drafts into pages that fit
a preview and prints JSON: the pages, and the AskUserQuestion calls that show
them (page questions with 2-4 page options each). The last call keeps one
question free for the approval question. Lines are kept as they are, except
that a line too long for one page is split across pages and the pipes of a
table that is too wide are escaped so that it shows as plain lines.
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
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
MAX_OPTIONS = 4
MAX_QUESTIONS = 4
MAX_HEADER = 12
# Words that send the user to an earlier reply instead of the dialog itself.
BACK_REFERENCE = re.compile(
    r"(上|前|直前|先)の(返事|返信|メッセージ|チャット|会話|回答|出力|説明|本文)"
    r"|上記"
    r"|(上|前)に(全文|載せ|書い|示し|出し|貼っ)"
    r"|上を(見|参照|確認)"
    r"|本文は上"
)

ADVICE = (
    "ユーザーは問いのダイアログだけで本文を読む（上のチャットは流れていくので参照させない）。"
    "長い本文は `ask-preview-guard.py --pages <下書き>` でページに分け、ページごとに選択肢の "
    "preview に載せる（agents-orchestrator の「承認をもらって実行する」の 1）。"
    "本文を切ったり縮めたりして 1 つの preview に押し込まない。"
)
BACK_ADVICE = (
    "問いの文・header・選択肢の label と説明で、上の返事やそれまでの会話を参照させない。"
    "要る中身は preview に載せる（agents-orchestrator の「承認をもらって実行する」の 1）。"
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


def wrap_and_limit(size):
    cols, rows = size
    return max(1, cols - WIDTH_TAKEN), max(1, rows - HEIGHT_TAKEN)


def shown_lines(text, wrap):
    lines = text.split("\n")
    table_rows = sum(1 for line in lines if TABLE_ROW.match(line))
    count = sum(max(1, -(-width(line) // wrap)) for line in lines)
    # A rendered Markdown table gets border lines between and around the rows.
    return count + (table_rows + 1 if table_rows else 0)


def problems(text, size):
    """Return the reasons a preview of `text` would not be shown in full."""
    cols, rows = size
    wrap, limit = wrap_and_limit(size)
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


def back_reference(text):
    match = BACK_REFERENCE.search(text) if isinstance(text, str) else None
    return match.group(0) if match else None


def check_tool_input(tool_input, size):
    """Return (problems with previews and question texts, back references)."""
    messages, back = [], []
    for q_index, question in enumerate(tool_input.get("questions") or [], 1):
        if not isinstance(question, dict):
            continue
        text = question.get("question")
        if isinstance(text, str) and units(text) > MAX_UNITS:
            messages.append(f"問い {q_index}: 問いの文が {MAX_UNITS} 文字を超えるので末尾が切られる")
        for field, name in (("question", "問いの文"), ("header", "header")):
            word = back_reference(question.get(field))
            if word:
                back.append(f"問い {q_index} の{name}が「{word}」と、ダイアログの外を参照している")
        for option in question.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = option.get("label", "")
            for field, name in (("label", "label"), ("description", "説明")):
                word = back_reference(option.get(field))
                if word:
                    back.append(f"問い {q_index} の「{label}」の{name}が「{word}」と、ダイアログの外を参照している")
            # The preview holds the body itself, which may say 上記; it is not checked for back references.
            if isinstance(option.get("preview"), str):
                for reason in problems(option["preview"], size):
                    messages.append(f"問い {q_index} の「{label}」の preview: {reason}")
    return messages, back


def fits(text, size):
    return not problems(text, size)


def split_long_line(line, size):
    """Split a line that does not fit a page by itself into pieces that do."""
    pieces, current = [], ""
    for ch in line:
        if current and not fits(current + ch, size):
            pieces.append(current)
            current = ""
        current += ch
    pieces.append(current)
    return pieces


def units_of(lines, size):
    """Group lines into units that a page keeps together.

    A table that fits a page is one unit, so it is not cut away from its
    header row. A table that is too wide or too tall for a page has its pipes
    escaped and shows as plain lines. A line too long for a page is split.
    """
    out, i = [], 0
    while i < len(lines):
        if not TABLE_ROW.match(lines[i]):
            line = lines[i]
            out.extend([[line]] if fits(line, size) else [[piece] for piece in split_long_line(line, size)])
            i += 1
            continue
        j = i
        while j < len(lines) and TABLE_ROW.match(lines[j]):
            j += 1
        block = lines[i:j]
        if fits("\n".join(block), size):
            out.append(block)
        else:
            out.extend(units_of([UNESCAPED_PIPE.sub(r"\\|", line) for line in block], size))
        i = j
    return out


def paginate(text, size):
    """Split `text` into pages that each fit a preview of the given size."""
    pages, current = [], []
    for unit in units_of(text.split("\n"), size):
        if current and not fits("\n".join(current + unit), size):
            pages.append(current)
            current = []
        current.extend(unit)
    if current:
        pages.append(current)
    result = []
    for page in pages:
        # Blank lines at the edges of a page only take up rows.
        while len(page) > 1 and not page[0].strip():
            page.pop(0)
        while len(page) > 1 and not page[-1].strip():
            page.pop()
        result.append("\n".join(page))
    return result


def even_chunks(items, size):
    """Split items into the fewest chunks of at most `size`, as even as possible."""
    if not items:
        return []
    count = -(-len(items) // size)
    base, extra = divmod(len(items), count)
    chunks, start = [], 0
    for index in range(count):
        end = start + base + (1 if index < extra else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


def excerpt(text, limit=40):
    first = next((line.strip() for line in text.split("\n") if line.strip()), "")
    return first if len(first) <= limit else first[: limit - 1] + "…"


def page_question(group, total):
    first, last = group[0]["number"], group[-1]["number"]
    span = f"{first}" if first == last else f"{first}〜{last}"
    header = f"本文 {first}/{total}" if first == last else f"本文 {first}-{last}/{total}"
    return {
        "question": (
            f"送る本文の {span} ページ目です（全 {total} ページ）。"
            "選択肢を上下に移ると、そのページが preview に出ます。読み終えたら、どれかを選んでください。"
        ),
        "header": header if len(header) <= MAX_HEADER else f"{first}-{last}/{total}"[:MAX_HEADER],
        "multiSelect": False,
        "options": [
            {
                "label": page["label"],
                "description": f"{page['number']}/{total} ページ: {excerpt(page['preview'])}",
                "preview": page["preview"],
            }
            for page in group
        ],
    }


def build_pages(named_texts, size):
    """Return the pages of the drafts and the AskUserQuestion calls that show them.

    Each page question has 2-4 page options. The calls hold at most 4
    questions, and the last call keeps one question free for the approval
    question. A single page gets no call: it goes into the preview of the
    approval option itself.
    """
    pages = []
    for name, text in named_texts:
        parts = paginate(text, size)
        for index, part in enumerate(parts, 1):
            label = name if len(parts) == 1 else f"{name} {index}/{len(parts)}"
            pages.append({"label": label, "preview": part})
    for number, page in enumerate(pages, 1):
        page["number"] = number
    if len(pages) < 2:
        return {"pages": pages, "calls": []}
    questions = [page_question(group, len(pages)) for group in even_chunks(pages, MAX_OPTIONS)]
    slots = questions + [None]  # None stands for the approval question.
    calls = [[q for q in chunk if q is not None] for chunk in even_chunks(slots, MAX_QUESTIONS)]
    return {"pages": pages, "calls": [{"questions": call} for call in calls]}


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
    messages, back = check_tool_input(tool_input, terminal_size())
    if not messages and not back:
        return 0
    if messages:
        print("AskUserQuestion の本文がユーザーに全部は見えない。", file=sys.stderr)
        for message in messages:
            print(f"- {message}", file=sys.stderr)
        print(ADVICE, file=sys.stderr)
    if back:
        print("AskUserQuestion がダイアログの外（上の返事）を参照している。", file=sys.stderr)
        for message in back:
            print(f"- {message}", file=sys.stderr)
        print(BACK_ADVICE, file=sys.stderr)
    return 2


def read_draft(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def main_check(paths):
    size = terminal_size()
    status = 0
    for path in paths:
        try:
            text = read_draft(path)
        except OSError as e:
            print(f"{path}: 読めない（{e.strerror}）")
            status = 2
            continue
        found = problems(text, size)
        if found:
            print(f"{path}: preview に全部は出ない（--pages でページに分ける）: " + " / ".join(found))
            status = max(status, 1)
        else:
            wrap, _ = wrap_and_limit(size)
            print(f"{path}: preview に全部出る（{units(text)} 文字、{shown_lines(text, wrap)} 行、端末 {size[0]}x{size[1]}）")
    return status


def main_pages(paths):
    size = terminal_size()
    named = []
    for path in paths:
        try:
            named.append((os.path.splitext(os.path.basename(path))[0], read_draft(path)))
        except OSError as e:
            print(f"{path}: 読めない（{e.strerror}）", file=sys.stderr)
            return 2
    result = build_pages(named, size)
    result["terminal"] = f"{size[0]}x{size[1]}"
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--check", "--pages"):
        if len(sys.argv) < 3:
            print(f"usage: ask-preview-guard.py {sys.argv[1]} <file>...", file=sys.stderr)
            sys.exit(2)
        sys.exit((main_check if sys.argv[1] == "--check" else main_pages)(sys.argv[2:]))
    sys.exit(main_hook())
