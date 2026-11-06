"""configs/tmux/scripts/open-link.sh のテスト。

実行: python3 -m unittest tests/test_open_link.py

tmux・open・xdg-open・uname は PATH の先頭に置いた偽物に差し替え、呼ばれたら引数を記録する。
"""

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

OPEN_LINK = Path(__file__).resolve().parents[1] / "configs" / "tmux" / "scripts" / "open-link.sh"


class OpenLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="open-link-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "calls.log"
        for name in ["tmux", "open", "xdg-open"]:
            self.stub(name, f'printf "%s\\n" "{name} $*" >> "{self.log}"')
        self.stub("uname", "echo Darwin")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    def run_open_link(self, url):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        subprocess.run(["bash", str(OPEN_LINK), "client0", url], env=env, check=True)

    def calls(self, wait=False):
        # xdg-open はバックグラウンドで呼ばれるので、wait のときは記録されるまで待つ。
        for _ in range(50 if wait else 1):
            if self.log.exists() and self.log.read_text():
                break
            time.sleep(0.1)
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_directory_opens_in_finder(self):
        folder = self.tmp / "my dir"
        folder.mkdir()
        self.run_open_link("file://" + str(folder).replace(" ", "%20"))
        self.assertEqual(self.calls(), [f"open {folder}"])

    def test_directory_on_linux_uses_xdg_open(self):
        self.stub("uname", "echo Linux")
        folder = self.tmp / "d"
        folder.mkdir()
        self.run_open_link(f"file://{folder}")
        self.assertEqual(self.calls(wait=True), [f"xdg-open {folder}"])

    def test_text_file_opens_in_popup_nvim(self):
        text = self.tmp / "note.md"
        text.write_text("hello\n")
        self.run_open_link(f"file://{text}#L3")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("tmux display-popup "), calls[0])
        self.assertIn(f"-d {self.tmp}", calls[0])
        self.assertTrue(calls[0].endswith(f"nvim +3 -- {text}"), calls[0])

    def test_binary_file_opens_with_system_opener(self):
        image = self.tmp / "a.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\xff\x00")
        self.run_open_link(f"file://{image}")
        self.assertEqual(self.calls(), [f"open {image}"])


if __name__ == "__main__":
    unittest.main()
