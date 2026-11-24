#!/usr/bin/env python3
"""Claude Code の hook: エージェントが hub v2 の項目（<GTD_HOME>/items/<id>.md）を書く前後の見張り。

- PreToolUse（Write|Edit）: 書く前に、まだコミットしていない人の変更を user のコミットにまとめる
  （記録係の「エージェントが書く前」の時機。人の直しとエージェントの直しを別のコミットにする）。
- PostToolUse（Write|Edit）: 書いたファイルの形（frontmatter の必須の項目・値・壊れた参照）と
  本文の正規形を gtd.py の lint で確かめ、変更を agent:<worker 名> のコミットにする。
  形が違えば、指摘を返して（exit 2）書き直させる。末尾の改行と frontmatter のあとの空行は問わない。

項目のファイルでなければ何もしない。gtd.py は agents-orchestrator のスキルにある（このファイルの
実体からの相対で探す。無ければ ~/.claude/skills/ の下）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

WORKER_RE = re.compile(r"(?:/hub/workers|/\.claude/worktrees)/([A-Za-z0-9][A-Za-z0-9._-]*)")


def gtd_script() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "skills" / "agents-orchestrator" / "scripts" / "gtd.py",
                 Path.home() / ".claude" / "skills" / "agents-orchestrator" / "scripts" / "gtd.py"):
        if cand.exists():
            return cand
    raise FileNotFoundError("gtd.py")


def load_gtd():
    spec = importlib.util.spec_from_file_location("hub_gtd", gtd_script())
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hub_gtd"] = mod
    spec.loader.exec_module(mod)
    return mod


def writer(cwd: str) -> str:
    m = WORKER_RE.search(cwd or "")
    return f"agent:{m.group(1)}" if m else "agent"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    path_s = (data.get("tool_input") or {}).get("file_path") or ""
    if not path_s.endswith(".md"):
        return 0
    try:
        gtd = load_gtd()
    except FileNotFoundError:
        return 0
    r = gtd.root()
    path = Path(path_s).expanduser()
    try:
        items = gtd.items_dir(r).resolve()
        if path.resolve().parent != items:
            return 0
    except OSError:
        return 0
    by = writer(data.get("cwd") or "")
    event = data.get("hook_event_name") or ""
    try:
        if event == "PreToolUse":
            with gtd.locked(r):
                gtd.commit(r, "user", "記録係: エージェントが書く前に人の変更をまとめる")
            return 0
        if not path.exists():
            return 0
        found = gtd.lint(r, [path]).get(str(path), [])
        gtd.log_change(r, path.stem, "edit", by)
        with gtd.locked(r):
            gtd.commit(r, by, f"edit {path.stem}: {by} が直接書いた")
    except gtd.GtdError as e:
        print(f"gtd-lint: {e}", file=sys.stderr)
        return 0
    if not found:
        return 0
    lines = [f"{path}:{f.line}: {f.message}{'（gtd.py lint --fix で直る）' if f.fixable else ''}" for f in found]
    print("hub の項目の形が違います。直してください。\n" + "\n".join(lines), file=sys.stderr)
    if any(f.fixable for f in found):
        print(f"本文の正規形は python3 {gtd_script()} lint --fix {path} で直せます。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
