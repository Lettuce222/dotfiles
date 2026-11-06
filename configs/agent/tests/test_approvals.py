"""窓口の承認の記録（approvals.py）と external-post-guard.py の allow のテスト。

実行: python3 -m unittest configs/agent/tests/test_approvals.py

hook と approvals.py をサブプロセスで呼ぶ。`claude agents --json` は PATH に置いた
偽の claude が返す。
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
GUARD = HOOKS / "external-post-guard.py"
APPROVALS = HOOKS / "approvals.py"

ORCH = "sess-orchestrator"
THREAD = "sess-thread"
SLACK = "mcp__slack__send_message"


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dir = root / "approvals"
        bindir = root / "bin"
        bindir.mkdir()
        agents = root / "agents.json"
        agents.write_text(
            json.dumps(
                [
                    {"sessionId": ORCH, "name": "orchestrator", "status": "busy"},
                    {"sessionId": THREAD, "name": "impl-x-y", "status": "busy"},
                ]
            )
        )
        fake = bindir / "claude"
        fake.write_text(f"#!/bin/sh\ncat '{agents}'\n")
        fake.chmod(0o755)
        self.env = {
            **os.environ,
            "AGENT_APPROVALS_DIR": str(self.dir),
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        }
        self.draft = root / "draft.md"
        self.draft.write_text("レビューありがとうございます。直しました。\n")

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def approve(self, *args):
        r = subprocess.run(
            [sys.executable, str(APPROVALS), "add", *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return Path(r.stdout.strip())

    def hook(self, tool_input, tool_name="Bash", session=ORCH):
        payload = {"tool_name": tool_name, "tool_input": tool_input, "session_id": session}
        return subprocess.run(
            [sys.executable, str(GUARD)],
            input=json.dumps(payload),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def decision(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]

    def records(self):
        return sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []

    # --- Bash ---

    def test_matching_command_is_allowed_once(self):
        cmd = f"gh pr comment 12 --body-file {self.draft}"
        self.approve("bash", "--command", cmd, "--note", "#12 への返信")
        self.assertEqual(self.decision(self.hook({"command": cmd})), "allow")
        self.assertEqual(self.records(), [])
        # 2 回目はダイアログに戻る
        self.assertEqual(self.decision(self.hook({"command": cmd})), "ask")

    def test_command_without_body_is_allowed(self):
        self.approve("bash", "--command", "gh pr ready 12")
        self.assertEqual(self.decision(self.hook({"command": "  gh pr ready 12 "})), "allow")

    def test_other_command_asks_and_keeps_the_record(self):
        self.approve("bash", "--command", "gh pr ready 12")
        self.assertEqual(self.decision(self.hook({"command": "gh pr ready 13"})), "ask")
        self.assertEqual(self.decision(self.hook({"command": "gh pr merge 12"})), "ask")
        self.assertEqual(len(self.records()), 1)

    def test_expired_record_asks_and_is_removed(self):
        self.approve("bash", "--command", "gh pr ready 12", "--ttl", "1")
        time.sleep(1.2)
        self.assertEqual(self.decision(self.hook({"command": "gh pr ready 12"})), "ask")
        self.assertEqual(self.records(), [])

    def test_changed_body_file_asks(self):
        cmd = f"gh pr comment 12 --body-file {self.draft}"
        self.approve("bash", "--command", cmd)
        self.draft.write_text("書き換えた本文\n")
        r = self.hook({"command": cmd})
        self.assertEqual(self.decision(r), "ask")
        self.assertIn("変わりました", r.stdout)

    def test_thread_session_cannot_use_the_record(self):
        self.approve("bash", "--command", "gh pr ready 12")
        r = self.hook({"command": "gh pr ready 12"}, session=THREAD)
        self.assertEqual(self.decision(r), "ask")
        self.assertIn("窓口", r.stdout)
        self.assertEqual(len(self.records()), 1)

    def test_text_rules_still_block_approved_commands(self):
        cmd = "gh pr comment 12 --body 'see ABC-1'"
        self.approve("bash", "--command", cmd)
        r = self.hook({"command": cmd})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(self.records()), 1)

    def test_writing_the_record_is_not_a_gh_write(self):
        cmd = f"python3 ~/.claude/hooks/approvals.py add bash --command 'gh pr comment 12 --body-file {self.draft}'"
        r = self.hook({"command": cmd})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_missing_body_file_is_rejected(self):
        r = subprocess.run(
            [sys.executable, str(APPROVALS), "add", "bash", "--command", "gh pr comment 1 --body-file /nope.md"],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.records(), [])

    # --- MCP ---

    def slack_input(self, text=None, **extra):
        return {
            "channel_id": "C1",
            "thread_ts": "1730000000.000100",
            "text": self.draft.read_text().strip() if text is None else text,
            **extra,
        }

    def approve_slack(self):
        self.approve(
            "mcp",
            "--tool",
            SLACK,
            "--params",
            json.dumps({"channel_id": "C1", "thread_ts": "1730000000.000100"}),
            "--body-file",
            str(self.draft),
            "--body-key",
            "text",
        )

    def test_mcp_matching_call_is_allowed_once(self):
        self.approve_slack()
        self.assertEqual(self.decision(self.hook(self.slack_input(), tool_name=SLACK)), "allow")
        self.assertEqual(self.decision(self.hook(self.slack_input(), tool_name=SLACK)), "ask")

    def test_mcp_other_destination_asks(self):
        self.approve_slack()
        other = {**self.slack_input(), "channel_id": "C2"}
        self.assertEqual(self.decision(self.hook(other, tool_name=SLACK)), "ask")
        extra = self.slack_input(reply_broadcast=True)
        self.assertEqual(self.decision(self.hook(extra, tool_name=SLACK)), "ask")
        self.assertEqual(self.decision(self.hook(self.slack_input(), tool_name="mcp__slack__other")), "ask")
        self.assertEqual(len(self.records()), 1)

    def test_mcp_changed_text_asks(self):
        self.approve_slack()
        r = self.hook(self.slack_input(text="別の文面"), tool_name=SLACK)
        self.assertEqual(self.decision(r), "ask")
        self.assertIn("変わりました", r.stdout)

    def test_mcp_params_must_not_hold_the_body(self):
        r = subprocess.run(
            [
                sys.executable,
                str(APPROVALS),
                "add",
                "mcp",
                "--tool",
                SLACK,
                "--params",
                json.dumps({"channel_id": "C1", "text": "x"}),
                "--body-file",
                str(self.draft),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
