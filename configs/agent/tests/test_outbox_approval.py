"""ペインで承認済みの提案を確認なしで通す仕組みのテスト。

実行: python3 -m unittest configs/agent/tests/test_outbox_approval.py

external-post-guard.py（承認済みなら allow）と outbox-guard.py（モデルが
.approved を書くのを deny）を、偽の入力でサブプロセスとして呼ぶ。
AGENT_HUB_HOME を一時ディレクトリに向けるので、本物の ~/hub には触れない。
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
POST_GUARD = HOOKS / "external-post-guard.py"
OUTBOX_GUARD = HOOKS / "outbox-guard.py"

SLACK = "mcp__example__send_message"
SLACK_DEST = {"channel_id": "C123", "thread_ts": "1700000000.000100"}
TEXT = "リリースノートを更新しました。確認をお願いします。\n"


def iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class HookCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "hub"
        self.outbox = self.home / "outbox"
        self.outbox.mkdir(parents=True)
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": tmp.name,
            "AGENT_HUB_HOME": str(self.home),
        }

    def run_hook(self, hook, tool_name, tool_input, **env):
        payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(self.home)}
        return subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**self.env, **env},
            check=False,
        )

    def decision(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return None
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]


class ApprovedPostTest(HookCase):
    def propose(self, pid, text, dest, approved_ago=60):
        """hub が書く .md と .json、ペインが書く .approved を用意する。"""
        (self.outbox / f"{pid}.md").write_text(text)
        (self.outbox / f"{pid}.json").write_text(json.dumps(dest))
        if approved_ago is not None:
            mark = self.outbox / f"{pid}.approved"
            mark.write_text(iso(approved_ago) + "\n")
            # ペインは提案を書いたあとに承認する。
            later = time.time() + 1
            os.utime(mark, (later, later))

    def send_slack(self, message=TEXT.rstrip("\n"), **dest):
        return self.run_hook(POST_GUARD, SLACK, {**(dest or SLACK_DEST), "message": message})

    def send_gh(self, command):
        return self.run_hook(POST_GUARD, "Bash", {"command": command})

    def test_approved_mcp_post_is_allowed_once(self):
        self.propose("P7", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        self.assertEqual(self.decision(self.send_slack()), "allow")
        self.assertFalse((self.outbox / "P7.approved").exists())
        self.assertTrue((self.outbox / "P7.sent").exists())
        # 同じ承認では二度送れない。
        self.assertEqual(self.decision(self.send_slack()), "ask")

    def test_trailing_newlines_are_ignored(self):
        self.propose("P1", "本文です。\n\n", {"tool": SLACK, "input": SLACK_DEST})
        self.assertEqual(self.decision(self.send_slack("本文です。")), "allow")

    def test_other_text_asks(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        self.assertEqual(self.decision(self.send_slack("リリースノートを更新しました。")), "ask")
        self.assertTrue((self.outbox / "P1.approved").exists())

    def test_other_destination_asks(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        for dest in (
            {"channel_id": "C999", "thread_ts": SLACK_DEST["thread_ts"]},
            {"channel_id": "C123"},
            {**SLACK_DEST, "reply_broadcast": True},
        ):
            with self.subTest(dest=dest):
                self.assertEqual(self.decision(self.send_slack(**dest)), "ask")
        r = self.run_hook(POST_GUARD, "mcp__other__send_message", {**SLACK_DEST, "message": TEXT})
        self.assertEqual(self.decision(r), "ask")
        self.assertTrue((self.outbox / "P1.approved").exists())

    def test_unapproved_proposal_asks(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST}, approved_ago=None)
        self.assertEqual(self.decision(self.send_slack()), "ask")

    def test_approval_expires_after_30_minutes(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST}, approved_ago=29 * 60)
        self.assertEqual(self.decision(self.send_slack()), "allow")
        self.propose("P2", TEXT, {"tool": SLACK, "input": SLACK_DEST}, approved_ago=31 * 60)
        self.assertEqual(self.decision(self.send_slack()), "ask")
        self.assertTrue((self.outbox / "P2.approved").exists())

    def test_approval_in_the_future_asks(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST}, approved_ago=-10 * 60)
        self.assertEqual(self.decision(self.send_slack()), "ask")

    def test_broken_approval_asks(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        (self.outbox / "P1.approved").write_text("yes\n")
        self.assertEqual(self.decision(self.send_slack()), "ask")

    def test_proposal_edited_after_approval_asks(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        md = self.outbox / "P1.md"
        later = time.time() + 5
        os.utime(md, (later, later))
        self.assertEqual(self.decision(self.send_slack()), "ask")

    def test_existing_checks_run_before_allow(self):
        text = "PROJ-12 を直しました。"
        self.propose("P1", text, {"tool": SLACK, "input": SLACK_DEST})
        r = self.send_slack(text)
        self.assertEqual(r.returncode, 2)
        self.assertIn("PROJ-12", r.stderr)
        # 止めた送信で承認を使い切らない。
        self.assertTrue((self.outbox / "P1.approved").exists())

    def test_worker_is_never_allowed_by_approval(self):
        self.propose("P1", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        r = self.run_hook(
            POST_GUARD, SLACK, {**SLACK_DEST, "message": TEXT},
            AGENT_HUB_WORKER="repo.task", AGENT_HUB_BRANCH="agent/task",
        )
        self.assertEqual(r.returncode, 2)
        self.assertTrue((self.outbox / "P1.approved").exists())

    def test_gh_pr_comment_with_body_file(self):
        self.propose("P3", TEXT, {"tool": "gh", "repo": "owner/repo", "pr": 12, "action": "comment"})
        body = self.outbox / "P3.md"
        cmd = f"~/.local/share/gh-ghtkn/bin/gh pr comment 12 -R owner/repo --body-file {body}"
        self.assertEqual(self.decision(self.send_gh(cmd)), "allow")
        self.assertEqual(self.decision(self.send_gh(cmd)), "ask")

    def test_gh_pr_review(self):
        self.propose("P4", TEXT, {"tool": "gh", "repo": "owner/repo", "pr": "12", "action": "review-comment"})
        body = self.outbox / "P4.md"
        self.assertEqual(
            self.decision(self.send_gh(f"gh pr review 12 --approve -R owner/repo --body-file {body}")), "ask"
        )
        self.assertEqual(
            self.decision(self.send_gh(f"gh pr review 12 --comment --repo=owner/repo --body-file {body}")), "allow"
        )

    def test_gh_commands_that_do_not_match_ask(self):
        self.propose("P5", TEXT, {"tool": "gh", "repo": "owner/repo", "pr": 12, "action": "comment"})
        body = self.outbox / "P5.md"
        for cmd in (
            f"gh pr comment 13 -R owner/repo --body-file {body}",
            f"gh pr comment 12 -R other/repo --body-file {body}",
            f"gh pr comment 12 --body-file {body}",
            f"gh pr comment 12 -R owner/repo --edit-last --body-file {body}",
            f"gh pr comment 12 -R owner/repo --body-file {body} && gh pr comment 13 -R owner/repo -b x",
            f"cd /tmp && gh pr comment 12 -R owner/repo --body-file {body}",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(self.send_gh(cmd)), "ask")
        self.assertTrue((self.outbox / "P5.approved").exists())

    def test_picks_the_matching_proposal(self):
        self.propose("P1", "別の文面\n", {"tool": SLACK, "input": SLACK_DEST})
        self.propose("P2", TEXT, {"tool": SLACK, "input": SLACK_DEST})
        r = self.send_slack()
        self.assertEqual(self.decision(r), "allow")
        self.assertIn("P2", r.stdout)
        self.assertTrue((self.outbox / "P1.approved").exists())
        self.assertTrue((self.outbox / "P2.sent").exists())


class OutboxGuardTest(HookCase):
    def test_file_tools_cannot_write_marks(self):
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            for path in (str(self.outbox / "P1.approved"), "outbox/P1.approved", "~/hub/outbox/P2.APPROVED"):
                with self.subTest(tool=tool, path=path):
                    r = self.run_hook(OUTBOX_GUARD, tool, {key: path, "content": iso(0)})
                    self.assertEqual(self.decision(r), "deny")

    def test_file_tools_can_write_proposals(self):
        for path in (self.outbox / "P1.md", self.outbox / "P1.json", self.home / "notes" / "x.approved"):
            with self.subTest(path=path):
                r = self.run_hook(OUTBOX_GUARD, "Write", {"file_path": str(path), "content": "x"})
                self.assertIsNone(self.decision(r))

    def test_bash_cannot_touch_marks(self):
        for cmd in (
            "date -u +%FT%TZ > ~/hub/outbox/P1.approved",
            "touch outbox/P1.approved",
            "mv ~/hub/outbox/P1.sent ~/hub/outbox/P1.approved",
            "cd ~/hub/outbox && cp P1.md P1.approv''ed",
            "printf x | tee ~/hub/outbox/P1.appr?ved",
            "touch -t 202601010000 ~/hub/outbox/P1.md",
            "python3 -c 'open(\"x.approved\",\"w\")'",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(self.run_hook(OUTBOX_GUARD, "Bash", {"command": cmd})), "deny")

    def test_bash_can_read_outbox(self):
        for cmd in (
            "ls ~/hub/outbox",
            "cat ~/hub/outbox/P1.md 2>/dev/null",
            "mkdir -p ~/hub/outbox",
            "rm ~/hub/outbox/P1.md ~/hub/outbox/P1.json",
            "git status",
        ):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.decision(self.run_hook(OUTBOX_GUARD, "Bash", {"command": cmd})))


if __name__ == "__main__":
    unittest.main()
