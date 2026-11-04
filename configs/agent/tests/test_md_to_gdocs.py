"""report-writing スキルの md_to_gdocs.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_md_to_gdocs.py

変換の部分と、--stdout での出力だけを確かめる。クリップボードには触れない。
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "report-writing" / "scripts" / "md_to_gdocs.py"

spec = importlib.util.spec_from_file_location("md_to_gdocs", SCRIPT)
md_to_gdocs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md_to_gdocs)
convert = md_to_gdocs.convert


class ConvertTest(unittest.TestCase):
    def test_top_level_and_nested_items(self):
        src = "- 現状\n  - 進捗は予定どおり\n    - 詳細\n- 見立て\n"
        want = "* 現状\n  * 進捗は予定どおり\n    * 詳細\n* 見立て\n"
        self.assertEqual(convert(src), want)

    def test_tab_indent_and_task_list(self):
        self.assertEqual(convert("\t- [ ] 確認\n"), "\t* [ ] 確認\n")

    def test_only_the_marker_changes(self):
        self.assertEqual(convert("- A - B - C\n"), "* A - B - C\n")

    def test_blockquote_item(self):
        self.assertEqual(convert("> - 引用の項目\n"), "> * 引用の項目\n")

    def test_non_items_untouched(self):
        src = "本文 - ダッシュ\n-5 度\n--option\n1. 番号付き\n"
        self.assertEqual(convert(src), src)

    def test_code_block_untouched(self):
        src = "```sh\n- not item\n```\n- item\n"
        self.assertEqual(convert(src), "```sh\n- not item\n```\n* item\n")

    def test_tilde_fence_and_longer_fence(self):
        src = "~~~\n- a\n```\n- b\n~~~\n````md\n```\n- c\n````\n- d\n"
        want = "~~~\n- a\n```\n- b\n~~~\n````md\n```\n- c\n````\n* d\n"
        self.assertEqual(convert(src), want)

    def test_indented_fence_in_list(self):
        src = "- item\n  ```\n  - code\n  ```\n  - nested\n"
        want = "* item\n  ```\n  - code\n  ```\n  * nested\n"
        self.assertEqual(convert(src), want)

    def test_table_untouched(self):
        src = "| 到達点 | 状態 |\n| --- | --- |\n| - 未定 | 済 |\n"
        self.assertEqual(convert(src), src)

    def test_thematic_break_untouched(self):
        src = "---\n- - -\n  ---\n"
        self.assertEqual(convert(src), src)

    def test_crlf_and_no_trailing_newline(self):
        self.assertEqual(convert("- a\r\n- b"), "* a\r\n* b")


class CliTest(unittest.TestCase):
    def test_stdout_from_stdin(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--stdout"],
            input="- 日本語\n".encode("utf-8"),
            capture_output=True,
            check=True,
        )
        self.assertEqual(r.stdout.decode("utf-8"), "* 日本語\n")

    def test_stdout_from_file(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as f:
            f.write("- a\n  - b\n")
        try:
            r = subprocess.run([sys.executable, str(SCRIPT), f.name, "--stdout"], capture_output=True, check=True)
            self.assertEqual(r.stdout.decode("utf-8"), "* a\n  * b\n")
        finally:
            Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main()
