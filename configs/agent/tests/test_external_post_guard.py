"""external-post-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_external_post_guard.py

hook をサブプロセスで呼ぶ。
"""

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "external-post-guard.py"


class GuardTest(unittest.TestCase):
    def run_hook(self, tool_input, tool_name="Bash"):
        payload = {"tool_name": tool_name, "tool_input": tool_input}
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )

    def bash(self, command):
        return self.run_hook({"command": command})

    def assertAsk(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def assertPass(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")

    # --- 文面の決まり ---

    def test_unlinked_ticket_is_blocked(self):
        r = self.bash("gh pr create --draft --title t --body 'fixes ABC-12'")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ABC-12", r.stderr)

    def test_date_without_weekday_is_blocked(self):
        r = self.bash("gh pr comment --body 'due 11/4'")
        self.assertEqual(r.returncode, 2)
        self.assertIn("11/4", r.stderr)

    # --- 確認を求めるもの、素通りするもの ---

    def test_post_gets_ask(self):
        self.assertAsk(self.bash("gh pr create --draft --title t --body ok"))
        self.assertAsk(self.bash("gh pr comment 12 --body ok"))
        self.assertAsk(self.run_hook({"text": "hello"}, tool_name="mcp__slack__send"))

    def test_non_gh_command_passes(self):
        self.assertPass(self.bash("git status"))

    def test_gh_api_read_passes(self):
        self.assertPass(self.bash("gh api repos/o/r/pulls"))
        self.assertPass(self.bash("gh api -X GET search/issues -f q=x"))

    def test_gh_api_write_asks(self):
        self.assertAsk(self.bash("gh api repos/o/r/issues -f title=x -f body=ok"))

    def test_gh_called_by_path_is_checked_the_same(self):
        gh = "~/.local/share/gh-ghtkn/bin/gh"
        self.assertPass(self.bash(f"{gh} api repos/o/r/pulls/1"))
        self.assertAsk(self.bash(f"{gh} pr comment 12 --body ok"))

    def test_heredoc_in_quoted_body_asks(self):
        command = textwrap.dedent(
            """\
            gh pr create --draft --title t --body "$(cat <<'EOF'
            概要 && 詳細
            EOF
            )"
            """
        )
        self.assertAsk(self.bash(command))

    def test_mcp_without_prose_passes(self):
        self.assertPass(self.run_hook({"query": "x"}, tool_name="mcp__slack__search"))


if __name__ == "__main__":
    unittest.main()
