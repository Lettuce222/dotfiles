"""docs/overview.md が追跡しているファイルと食い違っていないかのテスト。

実行: python3 -m unittest tests/test_overview.py

- 追跡しているファイルは、どれもページにパスで載っているか、載っているフォルダ（末尾が `/`）の下にある。
- ページに載っているリポジトリのパスは、実在するか、gitignore 済み（そのマシンだけのファイル）である。
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERVIEW = ROOT / "docs" / "overview.md"

# リポジトリのパスとみなすコード片。プレースホルダ（<app> など）や glob は除く。
PATH_PATTERN = re.compile(
    r"`((?:configs|docs|tests|hooks)/[^`<>*\s]*|install\.sh|README\.md|CLAUDE\.md|\.gitignore)`"
)


def tracked_files():
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def mentioned_paths():
    return set(PATH_PATTERN.findall(OVERVIEW.read_text(encoding="utf-8")))


def is_ignored(path):
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", path],
        capture_output=True,
    )
    return result.returncode == 0


class OverviewTest(unittest.TestCase):
    def test_every_tracked_file_is_listed(self):
        mentioned = mentioned_paths()
        dirs = [p for p in mentioned if p.endswith("/")]
        missing = [
            f
            for f in tracked_files()
            if f not in mentioned and not any(f.startswith(d) for d in dirs)
        ]
        self.assertEqual(
            missing, [], "docs/overview.md に載っていない追跡中のファイル"
        )

    def test_every_listed_path_exists(self):
        stale = sorted(
            p
            for p in mentioned_paths()
            # 末尾の / は残す。フォルダだけに効く ignore（`local/` など）は、
            # フォルダが無いマシンでは / 付きでないと当たらない
            if not (ROOT / p).exists() and not is_ignored(p)
        )
        self.assertEqual(
            stale, [], "docs/overview.md に載っているが無いパス"
        )


if __name__ == "__main__":
    unittest.main()
