"""窓口の承認の記録（approvals.py）と、それを使う hook（external-post-guard.py、
approval-gate.py）のテスト。

実行: python3 -m unittest configs/agent/tests/test_approvals.py

hook と approvals.py をサブプロセスで呼ぶ。`claude agents --json` は PATH に置いた
偽の claude が返す。approvals.py add は CLAUDE_CODE_SESSION_ID で呼んだセッションを見る。
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
GATE = HOOKS / "approval-gate.py"
APPROVALS = HOOKS / "approvals.py"

ORCH = "sess-orchestrator"
THREAD = "sess-thread"
OTHER_THREAD = "sess-other-thread"
INTERACTIVE = "sess-interactive"
THREAD_NAME = "impl-x-y"
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
                    {"sessionId": ORCH, "name": "orchestrator", "kind": "background", "status": "busy"},
                    {"sessionId": THREAD, "name": THREAD_NAME, "kind": "background", "status": "busy"},
                    {"sessionId": OTHER_THREAD, "name": "impl-x-z", "kind": "background", "status": "busy"},
                    {"sessionId": INTERACTIVE, "name": "dotfiles-1a", "kind": "interactive", "status": "busy"},
                ]
            )
        )
        fake = bindir / "claude"
        fake.write_text(f"#!/bin/sh\ncat '{agents}'\n")
        fake.chmod(0o755)
        self.env = {
            **{k: v for k, v in os.environ.items() if k not in ("AGENT_ORCHESTRATOR_NAME", "CLAUDE_CODE_SESSION_ID")},
            "AGENT_APPROVALS_DIR": str(self.dir),
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        }
        self.draft = root / "draft.md"
        self.draft.write_text("レビューありがとうございます。直しました。\n")

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def add(self, *args, writer=ORCH):
        return subprocess.run(
            [sys.executable, str(APPROVALS), "add", *args],
            env={**self.env, "CLAUDE_CODE_SESSION_ID": writer},
            capture_output=True,
            text=True,
            check=False,
        )

    def approve(self, *args):
        r = self.add(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return Path(r.stdout.strip())

    def run_hook(self, script, mode, tool_input, tool_name, session):
        payload = {"tool_name": tool_name, "tool_input": tool_input, "session_id": session}
        return subprocess.run(
            [sys.executable, str(script), *mode],
            input=json.dumps(payload),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def hook(self, tool_input, tool_name="Bash", session=ORCH):
        return self.run_hook(GUARD, [], tool_input, tool_name, session)

    def gate(self, mode, tool_input, tool_name="Bash", session=THREAD):
        return self.run_hook(GATE, [mode], tool_input, tool_name, session)

    def decision(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]

    def permission(self, r):
        """PermissionRequest の behavior。決めなかったとき（ダイアログのまま）は None。"""
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return None
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PermissionRequest")
        return out["decision"]["behavior"]

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
        r = self.add("bash", "--command", "gh pr comment 1 --body-file /nope.md")
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
        r = self.add(
            "mcp", "--tool", SLACK, "--params", json.dumps({"channel_id": "C1", "text": "x"}), "--body-file", str(self.draft)
        )
        self.assertEqual(r.returncode, 2)

    # --- 記録を書けるのは窓口だけ ---

    def test_only_the_orchestrator_can_write_records(self):
        for writer in (THREAD, INTERACTIVE, "sess-unknown"):
            r = self.add("bash", "--command", "gh pr ready 12", writer=writer)
            self.assertEqual(r.returncode, 3, writer)
            self.assertIn("窓口", r.stderr)
        r = subprocess.run(
            [sys.executable, str(APPROVALS), "add", "bash", "--command", "gh pr ready 12"],
            env=self.env,  # CLAUDE_CODE_SESSION_ID が無い（Claude Code の外）
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.records(), [])

    def test_thread_name_must_exist(self):
        r = self.add("bash", "--command", "git push --force", "--worker", "impl-nope")
        self.assertEqual(r.returncode, 2)
        r = self.add("bash", "--command", "git push --force", "--worker", "orchestrator")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.records(), [])

    def test_gate_denies_record_writes_outside_the_orchestrator(self):
        cmds = [
            "python3 ~/.claude/hooks/approvals.py add bash --command 'git push --force'",
            "cp x.json ~/hub/state/approvals/x.json",
            f"cp x.json {self.dir}/x.json",
        ]
        for cmd in cmds:
            for session in (THREAD, INTERACTIVE):
                self.assertEqual(self.decision(self.gate("pre", {"command": cmd}, session=session)), "deny", cmd)
        write = {"file_path": str(self.dir / "x.json"), "content": "{}"}
        self.assertEqual(self.decision(self.gate("pre", write, tool_name="Write", session=THREAD)), "deny")
        # 窓口では止めない。worker が記録を list するのも止めない
        r = self.gate("pre", {"command": cmds[0]}, session=ORCH)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.gate("pre", {"command": "python3 ~/.claude/hooks/approvals.py list"}, session=THREAD)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        other = {"file_path": str(Path(self.tmp.name) / "notes.md"), "content": "x"}
        r = self.gate("pre", other, tool_name="Write", session=THREAD)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    # --- worker の確認ダイアログ（PermissionRequest） ---

    def test_thread_dialog_is_denied_with_guidance(self):
        r = self.gate("permission", {"command": "git push --force origin HEAD"})
        self.assertEqual(self.permission(r), "deny")
        message = json.loads(r.stdout)["hookSpecificOutput"]["decision"]["message"]
        self.assertIn("要判断", message)
        self.assertIn("窓口", message)
        self.assertIn("git push --force origin HEAD", message)
        self.assertIn("1 文字も変えずに実行し直して", message)

    def test_orchestrator_and_interactive_sessions_keep_the_dialog(self):
        for session in (ORCH, INTERACTIVE, "sess-unknown"):
            r = self.gate("permission", {"command": "git push --force origin HEAD"}, session=session)
            self.assertIsNone(self.permission(r), session)

    def test_thread_record_allows_that_thread_once(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd, "--worker", THREAD_NAME)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "allow")
        self.assertEqual(self.records(), [])
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")

    def test_thread_record_allows_in_pre_tool_use(self):
        cmd = "rm -rf build"
        self.approve("bash", "--command", cmd, "--worker", THREAD_NAME)
        self.assertEqual(self.decision(self.gate("pre", {"command": cmd})), "allow")
        self.assertEqual(self.records(), [])
        r = self.gate("pre", {"command": cmd})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_thread_record_is_not_for_other_sessions_or_commands(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd, "--worker", THREAD_NAME)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd}, session=OTHER_THREAD)), "deny")
        self.assertIsNone(self.permission(self.gate("permission", {"command": cmd}, session=ORCH)))
        self.assertIsNone(self.permission(self.gate("permission", {"command": cmd}, session=INTERACTIVE)))
        r = self.gate("pre", {"command": cmd}, session=OTHER_THREAD)
        self.assertEqual(r.stdout, "")
        other = self.gate("permission", {"command": "git push --force origin main"})
        self.assertEqual(self.permission(other), "deny")
        self.assertEqual(len(self.records()), 1)

    def test_orchestrator_record_is_not_for_threads(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")
        self.assertEqual(len(self.records()), 1)

    def test_expired_thread_record_is_denied(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd, "--worker", THREAD_NAME, "--ttl", "1")
        time.sleep(1.2)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")
        self.assertEqual(self.records(), [])

    def test_thread_gh_write_with_record_is_allowed_by_the_guard(self):
        cmd = f"gh pr comment 12 --body-file {self.draft}"
        self.approve("bash", "--command", cmd, "--worker", THREAD_NAME)
        # gh の書き込みは external-post-guard.py が記録を使う。gate の pre は触らない
        r = self.gate("pre", {"command": cmd})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.decision(self.hook({"command": cmd}, session=THREAD)), "allow")
        self.assertEqual(self.records(), [])

    def test_thread_gh_write_without_record_asks_then_is_denied(self):
        cmd = f"gh pr comment 12 --body-file {self.draft}"
        self.assertEqual(self.decision(self.hook({"command": cmd}, session=THREAD)), "ask")
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")

    def test_old_thread_option_and_record_still_work(self):
        # 名前を変える前の --thread と、"thread" の key で書かれた記録も通す
        cmd = "git push --force origin HEAD"
        path = self.approve("bash", "--command", cmd, "--thread", THREAD_NAME)
        rec = json.loads(path.read_text())
        self.assertEqual(rec["worker"], THREAD_NAME)
        self.assertNotIn("thread", rec)
        rec["thread"] = rec.pop("worker")
        path.write_text(json.dumps(rec))
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd}, session=OTHER_THREAD)), "deny")
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "allow")
        self.assertEqual(self.records(), [])

    def test_thread_mcp_record_without_body(self):
        tool = "mcp__slack__add_reaction"
        params = {"channel_id": "C1", "timestamp": "1.2", "name": "eyes"}
        self.approve("mcp", "--tool", tool, "--params", json.dumps(params), "--worker", THREAD_NAME)
        self.assertEqual(self.permission(self.gate("permission", {**params, "name": "+1"}, tool_name=tool)), "deny")
        self.assertEqual(self.permission(self.gate("permission", params, tool_name=tool)), "allow")
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
