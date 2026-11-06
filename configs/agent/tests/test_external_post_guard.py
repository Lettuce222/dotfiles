"""external-post-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_external_post_guard.py

hook をサブプロセスで呼ぶ。
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "external-post-guard.py"


class GuardTest(unittest.TestCase):
    def setUp(self):
        # 承認の記録は空の場所を見る（本物の ~/hub/state/approvals に触らない）
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "AGENT_APPROVALS_DIR": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, tool_input, tool_name="Bash"):
        payload = {"tool_name": tool_name, "tool_input": tool_input}
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            env=self.env,
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

    def reason(self, r):
        self.assertAsk(r)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_ask_shows_body_file_and_destination(self):
        draft = Path(self.tmp.name) / "reply.md"
        draft.write_text("レビューありがとうございます。直しました。", encoding="utf-8")
        why = self.reason(self.bash(f"gh pr comment 809 -R o/r --body-file {draft}"))
        self.assertIn("gh pr comment 809 -R o/r", why)
        self.assertIn("レビューありがとうございます。直しました。", why)

    def test_ask_shows_field_file_body(self):
        draft = Path(self.tmp.name) / "c.md"
        draft.write_text("行コメントの本文", encoding="utf-8")
        why = self.reason(self.bash(f"gh api repos/o/r/pulls/3/comments -F body=@{draft}"))
        self.assertIn("repos/o/r/pulls/3/comments", why)
        self.assertIn("行コメントの本文", why)

    def test_ask_shows_inline_body_once(self):
        why = self.reason(self.bash("gh pr comment 12 --body 'これで直りました'"))
        self.assertIn("gh pr comment 12 --body '<本文>'", why)
        self.assertEqual(why.count("これで直りました"), 1)

    def test_ask_shows_mcp_body_and_destination(self):
        why = self.reason(
            self.run_hook(
                {"channel_id": "C123", "thread_ts": "1.2", "text": "お知らせです"},
                tool_name="mcp__slack__send",
            )
        )
        self.assertIn("mcp__slack__send", why)
        self.assertIn("channel_id: C123", why)
        self.assertIn("thread_ts: 1.2", why)
        self.assertIn("お知らせです", why)

    def test_long_body_is_cut_with_a_note(self):
        draft = Path(self.tmp.name) / "long.md"
        draft.write_text("あ" * 5000 + "末尾", encoding="utf-8")
        why = self.reason(self.bash(f"gh pr comment 1 --body-file {draft}"))
        self.assertNotIn("末尾", why)
        self.assertIn("切りました", why)

    def test_state_change_without_body_shows_command(self):
        why = self.reason(self.bash("gh pr ready 12"))
        self.assertIn("gh pr ready 12", why)
        self.assertNotIn("本文:", why)

    def test_state_changes_ask(self):
        # permissions.ask で確認していた操作は、hook が ask を返す
        for cmd in (
            "gh pr merge 12",
            "gh pr ready 12",
            "gh pr edit 12 --add-reviewer someone",
            "gh pr close 12",
            "gh issue reopen 3",
            "gh api -X DELETE repos/o/r/issues/comments/1",
            "gh api graphql -f query='mutation { x }'",
        ):
            with self.subTest(cmd=cmd):
                self.assertAsk(self.bash(cmd))

    def test_gh_inside_compound_commands_asks(self):
        self.assertAsk(self.bash("git push && gh pr ready 12"))
        self.assertAsk(self.bash("git status\ngh pr merge 12"))
        self.assertAsk(self.bash('echo "$(gh pr comment 12 -b ok)"'))
        self.assertAsk(self.bash("bash -c 'gh pr ready 12'"))
        self.assertAsk(self.bash("GH_TOKEN=x gh pr ready 12"))

    def test_gh_text_inside_an_argument_passes(self):
        self.assertPass(self.bash("echo 'gh pr merge 12'"))
        self.assertPass(self.bash("gh pr view 12 && gh pr checks 12"))

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


class CheckFileTest(unittest.TestCase):
    """--check <file>: 送る前の下書きに、hook と同じ文面の決まりを当てる。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, name, text):
        p = Path(self.tmp.name) / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def check(self, *paths):
        return subprocess.run(
            [sys.executable, str(HOOK), "--check", *paths],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_clean_draft_passes(self):
        path = self.draft("ok.md", "[ABC-12](https://example.com/ABC-12) は 11/4(水) に直す。<https://x|#3>\n")
        r = self.check(path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")

    def test_problems_are_listed_per_file(self):
        bad = self.draft("bad.md", "ABC-12 と #34 は 11/4 に直す。\n")
        ok = self.draft("ok.md", "問題なし\n")
        r = self.check(ok, bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn(bad, r.stdout)
        self.assertNotIn(ok, r.stdout)
        for word in ("ABC-12", "#34", "11/4"):
            self.assertIn(word, r.stdout)

    def test_missing_file_is_an_error(self):
        r = self.check(str(Path(self.tmp.name) / "none.md"))
        self.assertEqual(r.returncode, 2)

    def test_no_file_is_an_error(self):
        self.assertEqual(self.check().returncode, 2)


if __name__ == "__main__":
    unittest.main()
