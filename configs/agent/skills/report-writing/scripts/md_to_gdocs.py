#!/usr/bin/env python3
"""Markdown を Google Docs の「Markdown から貼り付け」向けに直してクリップボードに入れる。

使い方: md_to_gdocs.py [FILE] [--stdout]

- FILE を省くか `-` にすると標準入力を読む
- pbcopy があればクリップボードに入れ、無ければ（または --stdout なら）標準出力に出す

直すこと:
- 箇条書きの記号 `- ` を `* ` にする（入れ子も）。Google Docs の貼り付けは
  `- ` の入れ子を正しく読めないことがあるため
- コードブロック（``` と ~~~）の中、表の行、水平線（`---`、`- - -`）は変えない
"""

import os
import re
import shutil
import subprocess
import sys

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
DASH_ITEM = re.compile(r"^(\s*(?:>\s*)*)- ")
THEMATIC_BREAK = re.compile(r"^ {0,3}-(?:[ \t]*-){2,}[ \t]*$")
TABLE_ROW = re.compile(r"^\s*\|")


def convert(text: str) -> str:
    out = []
    fence = None  # 開いているコードブロックの記号（"```" など）
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = FENCE.match(body)
        if fence is not None:
            # 閉じるのは同じ文字で、開いたときと同じ長さ以上の記号だけ
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not body[m.end():].strip():
                fence = None
            out.append(line)
            continue
        if m:
            fence = m.group(1)
            out.append(line)
            continue
        if TABLE_ROW.match(body) or THEMATIC_BREAK.match(body):
            out.append(line)
            continue
        out.append(DASH_ITEM.sub(r"\1* ", line, count=1))
    return "".join(out)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--stdout"]
    force_stdout = len(args) != len(argv)
    if len(args) > 1 or (args and args[0] in ("-h", "--help")):
        print(__doc__.strip(), file=sys.stderr)
        return 0 if args and args[0] in ("-h", "--help") else 2

    if not args or args[0] == "-":
        text = sys.stdin.buffer.read().decode("utf-8")
    else:
        with open(args[0], encoding="utf-8") as f:
            text = f.read()

    result = convert(text)
    pbcopy = None if force_stdout else shutil.which("pbcopy")
    if pbcopy:
        # pbcopy はロケールで文字コードを決めるので、UTF-8 を明示する
        env = {**os.environ, "LANG": "en_US.UTF-8"}
        subprocess.run([pbcopy], input=result.encode("utf-8"), env=env, check=True)
        print("クリップボードにコピーしました。Google Docs で「Markdown から貼り付け」を使ってください。", file=sys.stderr)
    else:
        sys.stdout.buffer.write(result.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
