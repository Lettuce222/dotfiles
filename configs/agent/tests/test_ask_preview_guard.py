"""ask-preview-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_ask_preview_guard.py

hook をサブプロセスで呼ぶ。端末の大きさは tmux と /dev/tty から取れないようにして、
既定の 100x40（見える行 12、折り返し幅 62）で確かめる。全角 31 文字 x 12 行が 1 ページになる。
"""

import importlib.util
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


def ask(preview=None, question="送りますか", description="送る", header="送信"):
    option = {"label": "承認して実行する（推奨）", "description": description}
    if preview is not None:
        option["preview"] = preview
    return {
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": question, "header": header, "multiSelect": False,
                                      "options": [option, {"label": "見送る", "description": "送らない"}]}]},
    }


def load_guard():
    spec = importlib.util.spec_from_file_location("ask_preview_guard", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = load_guard()
SIZE = (100, 40)


def normalized(text):
    return "".join(text.replace("\\|", "|").split())


class AskPreviewGuardTest(unittest.TestCase):
    def assertBlocked(self, payload, reason):
        r = run(payload=payload)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn(reason, r.stderr)
        self.assertIn("--pages", r.stderr)
        self.assertNotIn("直前の返事に全文", r.stderr)

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


    def test_back_reference_is_blocked(self):
        # 上のチャットは流れていくので、問いから上の返事を参照させない
        for payload in (
            ask(question="本文は上の返事に全文を載せました。送りますか"),
            ask(description="上記の本文で送る"),
            ask(header="上の返事"),
            ask(question="前の返事を見て、送るか決めてください"),
        ):
            r = run(payload=payload)
            self.assertEqual(r.returncode, 2, payload)
            self.assertIn("ダイアログの外を参照している", r.stderr)

    def test_body_in_preview_may_say_jouki(self):
        # preview は送る本文そのもの。本文の「上記」では止めない
        self.assertAllowed(ask("上記の件、承知しました。"))

    def test_ordinary_words_pass(self):
        self.assertAllowed(ask(question="#850 の返信を送りますか", description="上限を 2 に上げる案で送る"))


class PagesTest(unittest.TestCase):
    def test_pages_fit_and_keep_the_body(self):
        body = "\n\n".join(f"## 節 {i}\n\n" + "本文の段落です。" * 12 for i in range(20))
        pages = GUARD.paginate(body, SIZE)
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertEqual(GUARD.problems(page, SIZE), [], page)
        self.assertEqual(normalized("".join(pages)), normalized(body))

    def test_long_line_is_split(self):
        body = "あ" * 3000
        pages = GUARD.paginate(body, SIZE)
        self.assertGreater(len(pages), 1)
        self.assertEqual("".join(pages), body)
        for page in pages:
            self.assertEqual(GUARD.problems(page, SIZE), [])

    def test_table_stays_on_one_page(self):
        table = "| a | b |\n| --- | --- |\n" + "\n".join(f"| {i} | x |" for i in range(3))
        pages = GUARD.paginate("x\n" * 8 + table, SIZE)
        self.assertEqual(pages[-1], table)

    def test_wide_table_shows_as_plain_lines(self):
        table = "| 項目 | 説明 |\n| --- | --- |\n| a | " + "長い説明" * 20 + " |"
        pages = GUARD.paginate(table, SIZE)
        for page in pages:
            self.assertEqual(GUARD.problems(page, SIZE), [])
        self.assertTrue(pages[0].startswith("\\| 項目 \\| 説明 \\|"))
        self.assertEqual(normalized("".join(pages)), normalized(table))

    def test_calls_hold_pages_and_leave_room_for_approval(self):
        for count in (2, 3, 4, 5, 12, 13, 16, 17, 30):
            named = [(f"p{i}", "\n".join(f"行 {j}" for j in range(12))) for i in range(count)]
            result = GUARD.build_pages(named, SIZE)
            self.assertEqual(len(result["pages"]), count)
            calls = result["calls"]
            shown = [o["preview"] for c in calls for q in c["questions"] for o in q["options"]]
            self.assertEqual(shown, [p["preview"] for p in result["pages"]])
            for call in calls:
                self.assertLessEqual(len(call["questions"]), 4)
                for question in call["questions"]:
                    self.assertTrue(2 <= len(question["options"]) <= 4, question)
                    self.assertLessEqual(len(question["header"]), 12)
                    self.assertIsNone(GUARD.back_reference(question["question"]))
            # 最後の呼び出しには、承認の問いを足す場所が残る
            self.assertLessEqual(len(calls[-1]["questions"]), 3)

    def test_single_page_has_no_call(self):
        result = GUARD.build_pages([("reply", "短い本文")], SIZE)
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["pages"][0]["preview"], "短い本文")

    def test_pages_mode(self):
        with tempfile.TemporaryDirectory() as d:
            long = Path(d, "reply.md")
            long.write_text("あ" * 2500, encoding="utf-8")
            r = run(["--pages", str(long)])
            self.assertEqual(r.returncode, 0, r.stderr)
            result = json.loads(r.stdout)
            self.assertEqual(result["terminal"], "100x40")
            self.assertEqual([p["label"] for p in result["pages"]][:2], ["reply 1/7", "reply 2/7"])
            # 出力の問いは、そのまま hook を通る
            for call in result["calls"]:
                self.assertEqual(run(payload={"tool_name": "AskUserQuestion", "tool_input": call}).returncode, 0)
            self.assertEqual(run(["--pages", str(Path(d, "missing.md"))]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
