"""ask-preview-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_ask_preview_guard.py

hook をサブプロセスで呼ぶ。端末の大きさは tmux と /dev/tty から取れないようにして、
既定の 100x40（見える行 12、折り返し幅 62）で確かめる。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "ask-preview-guard.py"
ENV = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}


def run(args=(), payload=None):
    return subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=None if payload is None else json.dumps(payload),
        capture_output=True,
        text=True,
        env=ENV,
        start_new_session=True,  # /dev/tty を開けなくする
        check=False,
    )


def ask(preview=None, question="送りますか"):
    option = {"label": "承認して実行する（推奨）", "description": "送る"}
    if preview is not None:
        option["preview"] = preview
    return {
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": question, "header": "送信", "multiSelect": False,
                                      "options": [option, {"label": "見送る", "description": "送らない"}]}]},
    }


class AskPreviewGuardTest(unittest.TestCase):
    def assertBlocked(self, payload, reason):
        r = run(payload=payload)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(reason, r.stderr)
        self.assertIn("直前の返事に全文", r.stderr)

    def assertAllowed(self, payload):
        r = run(payload=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def test_short_preview_passes(self):
        self.assertAllowed(ask("宛先: #850\n\n確認しました。来週直します。"))

    def test_no_preview_passes(self):
        self.assertAllowed(ask())

    def test_other_tools_pass(self):
        self.assertAllowed({"tool_name": "Bash", "tool_input": {"command": "x" * 5000}})

    def test_broken_input_passes(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0)

    def test_over_2000_units_is_blocked(self):
        self.assertBlocked(ask("あ" * 2001), "2000 文字を超える")

    def test_2000_units_counts_utf16(self):
        # 絵文字は UTF-16 で 2 単位。1001 個で 2002 単位になる
        self.assertBlocked(ask("😀" * 1001), "2000 文字を超える")

    def test_too_many_lines_is_blocked(self):
        self.assertBlocked(ask("\n".join(f"行 {i}" for i in range(13))), "行になり")

    def test_twelve_lines_pass(self):
        self.assertAllowed(ask("\n".join(f"行 {i}" for i in range(12))))

    def test_long_lines_wrap(self):
        # 全角 31 文字 = 62 幅は 1 行、32 文字は 2 行に折り返す
        self.assertAllowed(ask("\n".join(["あ" * 31] * 12)))
        self.assertBlocked(ask("\n".join(["あ" * 32] * 7)), "行になり")

    def test_wide_table_is_blocked(self):
        table = "| 項目 | 説明 |\n| --- | --- |\n| a | " + "長い説明" * 20 + " |"
        self.assertBlocked(ask(table), "表の行")

    def test_table_borders_count_as_lines(self):
        rows = "\n".join(f"| {i} | x |" for i in range(6))
        # 表の 6 行 + 枠の 7 行 = 13 行
        self.assertBlocked(ask(rows), "行になり")

    def test_combining_run_is_blocked(self):
        self.assertBlocked(ask("a" + "́" * 9), "続く")

    def test_long_question_is_blocked(self):
        self.assertBlocked(ask(question="い" * 2001), "問いの文")

    def test_check_mode(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d, "ok.md")
            ok.write_text("短い本文\n", encoding="utf-8")
            long = Path(d, "long.md")
            long.write_text("あ" * 2500, encoding="utf-8")
            r = run(["--check", str(ok)])
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("preview に全部出る", r.stdout)
            r = run(["--check", str(ok), str(long)])
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("preview に全部は出ない", r.stdout)
            r = run(["--check", str(Path(d, "missing.md"))])
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
