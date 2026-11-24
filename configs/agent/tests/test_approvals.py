"""窓口の承認の記録（approvals.py）と、それを使う hook（external-post-guard.py、
approval-gate.py）のテスト。

実行: python3 -m unittest configs/agent/tests/test_approvals.py

hook と approvals.py をサブプロセスで呼ぶ。`claude agents --json` は PATH に置いた
偽の claude が返す。approvals.py add は CLAUDE_CODE_SESSION_ID で呼んだセッションを見る。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
GUARD = HOOKS / "external-post-guard.py"
GATE = HOOKS / "approval-gate.py"
APPROVALS = HOOKS / "approvals.py"

ORCH = "sess-orchestrator"
WORKER = "sess-worker"
OTHER_WORKER = "sess-other-worker"
INTERACTIVE = "sess-interactive"
WORKER_NAME = "impl-x-y"
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
                    {"sessionId": WORKER, "name": WORKER_NAME, "kind": "background", "status": "busy"},
                    {"sessionId": OTHER_WORKER, "name": "impl-x-z", "kind": "background", "status": "busy"},
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
            "AGENT_ASKS_DIR": str(root / "asks"),
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

    def gate(self, mode, tool_input, tool_name="Bash", session=WORKER):
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

    def test_worker_session_cannot_use_the_record(self):
        self.approve("bash", "--command", "gh pr ready 12")
        r = self.hook({"command": "gh pr ready 12"}, session=WORKER)
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
        for writer in (WORKER, INTERACTIVE, "sess-unknown"):
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

    def test_worker_name_must_exist(self):
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
            for session in (WORKER, INTERACTIVE):
                self.assertEqual(self.decision(self.gate("pre", {"command": cmd}, session=session)), "deny", cmd)
        write = {"file_path": str(self.dir / "x.json"), "content": "{}"}
        self.assertEqual(self.decision(self.gate("pre", write, tool_name="Write", session=WORKER)), "deny")
        # 窓口では止めない。worker が記録を list するのも止めない
        r = self.gate("pre", {"command": cmds[0]}, session=ORCH)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.gate("pre", {"command": "python3 ~/.claude/hooks/approvals.py list"}, session=WORKER)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        other = {"file_path": str(Path(self.tmp.name) / "notes.md"), "content": "x"}
        r = self.gate("pre", other, tool_name="Write", session=WORKER)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_gate_denies_answering_asks_outside_the_orchestrator(self):
        for command in ("python3 ~/.claude/hooks/asks.py answer 20261119-000000-deadbeef --by panel --choice 1",
                        "python3 ~/.claude/hooks/asks.py claim 20261119-000000-deadbeef",
                        "echo '{}' > ~/hub/state/asks/20261119-000000-deadbeef.answer.json"):
            for session in (WORKER, INTERACTIVE):
                self.assertEqual(self.decision(self.gate("pre", {"command": command}, session=session)), "deny", (command, session))
        for command in ("python3 ~/.claude/hooks/asks.py answer 20261119-000000-deadbeef --by orchestrator --choice 1",
                        "python3 ~/.claude/hooks/asks.py claim 20261119-000000-deadbeef"):
            r = self.gate("pre", {"command": command}, session=ORCH)
            self.assertEqual((r.returncode, r.stdout), (0, ""), command)
        write = {"file_path": "/h/hub/state/asks/x.answer.json", "content": "{}"}
        self.assertEqual(self.decision(self.gate("pre", write, tool_name="Write", session=WORKER)), "deny")
        ask = "python3 ~/.claude/hooks/asks.py decide --question q --option 'a|b' --option 'c|d'"
        r = self.gate("pre", {"command": ask}, session=WORKER)
        self.assertEqual((r.returncode, r.stdout), (0, ""), "a worker still writes its own asks")

    # --- worker の確認ダイアログ（PermissionRequest） ---

    def test_worker_dialog_is_denied_with_guidance(self):
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

    def test_worker_record_allows_that_worker_once(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd, "--worker", WORKER_NAME)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "allow")
        self.assertEqual(self.records(), [])
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")

    def test_worker_record_allows_in_pre_tool_use(self):
        cmd = "rm -rf build"
        self.approve("bash", "--command", cmd, "--worker", WORKER_NAME)
        self.assertEqual(self.decision(self.gate("pre", {"command": cmd})), "allow")
        self.assertEqual(self.records(), [])
        r = self.gate("pre", {"command": cmd})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_worker_record_is_not_for_other_sessions_or_commands(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd, "--worker", WORKER_NAME)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd}, session=OTHER_WORKER)), "deny")
        self.assertIsNone(self.permission(self.gate("permission", {"command": cmd}, session=ORCH)))
        self.assertIsNone(self.permission(self.gate("permission", {"command": cmd}, session=INTERACTIVE)))
        r = self.gate("pre", {"command": cmd}, session=OTHER_WORKER)
        self.assertEqual(r.stdout, "")
        other = self.gate("permission", {"command": "git push --force origin main"})
        self.assertEqual(self.permission(other), "deny")
        self.assertEqual(len(self.records()), 1)

    def test_orchestrator_record_is_not_for_workers(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")
        self.assertEqual(len(self.records()), 1)

    def test_expired_worker_record_is_denied(self):
        cmd = "git push --force origin HEAD"
        self.approve("bash", "--command", cmd, "--worker", WORKER_NAME, "--ttl", "1")
        time.sleep(1.2)
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")
        self.assertEqual(self.records(), [])

    def test_worker_gh_write_with_record_is_allowed_by_the_guard(self):
        cmd = f"gh pr comment 12 --body-file {self.draft}"
        self.approve("bash", "--command", cmd, "--worker", WORKER_NAME)
        # gh の書き込みは external-post-guard.py が記録を使う。gate の pre は触らない
        r = self.gate("pre", {"command": cmd})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.decision(self.hook({"command": cmd}, session=WORKER)), "allow")
        self.assertEqual(self.records(), [])

    def test_worker_gh_write_without_record_asks_then_is_denied(self):
        cmd = f"gh pr comment 12 --body-file {self.draft}"
        self.assertEqual(self.decision(self.hook({"command": cmd}, session=WORKER)), "ask")
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "deny")

    def test_old_thread_option_and_record_still_work(self):
        # 名前を変える前の --thread と、"thread" の key で書かれた記録も通す
        cmd = "git push --force origin HEAD"
        path = self.approve("bash", "--command", cmd, "--thread", WORKER_NAME)
        rec = json.loads(path.read_text())
        self.assertEqual(rec["worker"], WORKER_NAME)
        self.assertNotIn("thread", rec)
        rec["thread"] = rec.pop("worker")
        path.write_text(json.dumps(rec))
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd}, session=OTHER_WORKER)), "deny")
        self.assertEqual(self.permission(self.gate("permission", {"command": cmd})), "allow")
        self.assertEqual(self.records(), [])

    def test_worker_mcp_record_without_body(self):
        tool = "mcp__slack__add_reaction"
        params = {"channel_id": "C1", "timestamp": "1.2", "name": "eyes"}
        self.approve("mcp", "--tool", tool, "--params", json.dumps(params), "--worker", WORKER_NAME)
        self.assertEqual(self.permission(self.gate("permission", {**params, "name": "+1"}, tool_name=tool)), "deny")
        self.assertEqual(self.permission(self.gate("permission", params, tool_name=tool)), "allow")
        self.assertEqual(self.records(), [])


class PanelPermissionTest(ApprovalTest):
    """窓口の確認ダイアログを Hub パネルのカードで答える（approval-gate.py permission --panel）。"""

    CALL = {"command": "rm -rf build", "description": "build を消す"}

    def setUp(self):
        super().setUp()
        self.asks_dir = Path(self.env["AGENT_ASKS_DIR"])
        self.env["AGENT_PERMISSION_WAIT"] = "5"
        sys.path.insert(0, str(HOOKS))
        import importlib
        self.asks = importlib.import_module("asks")

    def start(self, tool_input=None, tool_name="Bash", session=ORCH, panel=True, extra=None):
        payload = {"tool_name": tool_name, "tool_input": tool_input or self.CALL, "session_id": session,
                   "permission_mode": "auto", **(extra or {})}
        proc = subprocess.Popen(
            [sys.executable, str(GATE), "permission", *(["--panel"] if panel else [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, text=True,
        )
        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()
        proc.stdin = None  # Python 3.9 などの古い communicate() は閉じた stdin を flush して ValueError になる
        return proc

    def written(self, proc, timeout=10):
        """The ask the hook wrote, once it is there."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = [p for p in self.asks_dir.glob("*.json") if not p.name.endswith(".answer.json")] if self.asks_dir.is_dir() else []
            if found:
                time.sleep(0.05)  # written with os.replace, so whole once seen
                return found[0]
            if proc.poll() is not None:
                self.fail(f"the hook ended without an ask: {proc.stderr.read()}")
            time.sleep(0.05)
        self.fail("no ask was written")

    def finish(self, proc):
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, err)
        if not out.strip():
            return None
        out = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PermissionRequest")
        return out["decision"]

    def answer(self, path, choice, text=None, shown=None):
        shown = shown or hashlib.sha256(path.read_bytes()).hexdigest()
        with mock.patch.dict(os.environ, {"AGENT_ASKS_DIR": str(self.asks_dir)}):
            return self.asks.answer(path.stem, "panel", choice, shown, text=text, panel_check=lambda: True)

    def test_the_panels_allow_allows_once(self):
        proc = self.start()
        path = self.written(proc)
        ask = json.loads(path.read_text())
        self.assertEqual((ask["kind"], ask["worker"], ask["session_id"], ask["tool_name"]), ("permission", "orchestrator", ORCH, "Bash"))
        self.assertEqual(ask["tool_input"], self.CALL)
        self.assertGreater(ask["expires_at"], ask["created_at"])
        self.assertEqual(self.answer(path, "allow")[0], 0)
        self.assertEqual(self.finish(proc), {"behavior": "allow"}, "no updatedPermissions: this once only")
        self.assertEqual(list(self.asks_dir.glob("*.json")), [], "the ask and its answer are removed")

    def test_the_panels_deny_carries_the_reason(self):
        proc = self.start()
        path = self.written(proc)
        self.answer(path, "deny", text="まだ消さないで")
        decision = self.finish(proc)
        self.assertEqual(decision["behavior"], "deny")
        self.assertIn("Hub (local) のデスク", decision["message"])
        self.assertIn("まだ消さないで", decision["message"])
        self.assertNotIn("interrupt", decision)

    def test_terminal_and_no_answer_leave_the_dialog(self):
        proc = self.start()
        self.answer(self.written(proc), "terminal")
        self.assertIsNone(self.finish(proc))
        self.env["AGENT_PERMISSION_WAIT"] = "1"
        proc = self.start()
        self.written(proc)
        self.assertIsNone(self.finish(proc), "no answer in time")
        self.assertEqual(list(self.asks_dir.glob("*.json")), [])

    def test_an_answer_not_for_the_ask_as_written_leaves_the_dialog(self):
        # The card showed other bytes than the hook wrote.
        proc = self.start()
        path = self.written(proc)
        self.assertEqual(self.answer(path, "allow", shown="0" * 64)[0], self.asks.EXIT_GONE)
        (path.with_name(path.stem + ".answer.json")).write_text(json.dumps({"by": "panel", "choice": "allow", "shown_sha256": "0" * 64}))
        self.assertIsNone(self.finish(proc))
        # The ask was changed after the hook wrote it, and the answer is for the changed one.
        proc = self.start()
        path = self.written(proc)
        raw = json.loads(path.read_text())
        raw["tool_input"] = {"command": "ls"}
        path.write_text(json.dumps(raw))
        self.answer(path, "allow")
        self.assertIsNone(self.finish(proc))
        # Not the panel's answer.
        proc = self.start()
        path = self.written(proc)
        shown = hashlib.sha256(path.read_bytes()).hexdigest()
        (path.with_name(path.stem + ".answer.json")).write_text(json.dumps({"by": "orchestrator", "choice": "allow", "shown_sha256": shown}))
        self.assertIsNone(self.finish(proc))

    def test_only_the_panel_answers_a_permission(self):
        proc = self.start()
        path = self.written(proc)
        shown = hashlib.sha256(path.read_bytes()).hexdigest()
        with mock.patch.dict(os.environ, {"AGENT_ASKS_DIR": str(self.asks_dir)}):
            for by, choice, check in (("orchestrator", "allow", lambda: True), ("panel", "allow", lambda: False),
                                      ("panel", "1", lambda: True)):
                with self.assertRaises(self.asks.AskError, msg=(by, choice)):
                    self.asks.answer(path.stem, by, choice, shown, panel_check=check)
            with self.assertRaises(self.asks.AskError):
                self.asks.answer(path.stem, "panel", "allow", shown, text="理由", panel_check=lambda: True)
        self.answer(path, "terminal")
        self.finish(proc)

    def test_others_are_not_asked_in_the_panel(self):
        # Workers are still turned to the orchestrator; other sessions and questions keep the dialog.
        r = subprocess.run([sys.executable, str(GATE), "permission", "--panel"], input=json.dumps(
            {"tool_name": "Bash", "tool_input": self.CALL, "session_id": WORKER}), env=self.env, capture_output=True, text=True)
        self.assertEqual(self.permission(r), "deny")
        for session, tool, panel in ((INTERACTIVE, "Bash", True), (ORCH, "AskUserQuestion", True),
                                     (ORCH, "ExitPlanMode", True), (ORCH, "Bash", False)):
            proc = self.start(tool_name=tool, session=session, panel=panel)
            self.assertIsNone(self.finish(proc), (session, tool, panel))
        self.assertFalse(self.asks_dir.exists() and list(self.asks_dir.glob("*.json")))

    def test_a_too_long_call_is_left_to_the_terminal(self):
        proc = self.start(tool_input={"command": "echo " + "x" * 60000})
        self.assertIsNone(self.finish(proc))

    def test_a_stopped_hook_removes_its_ask(self):
        self.env["AGENT_PERMISSION_WAIT"] = "60"
        proc = self.start()
        self.written(proc)
        proc.terminate()
        proc.communicate(timeout=10)
        self.assertEqual(list(self.asks_dir.glob("*.json")), [])

    def test_the_orchestrator_cannot_write_the_panels_answer(self):
        for command in ("python3 ~/.claude/hooks/asks.py answer 20261119-000000-deadbeef --by panel --choice allow --shown x",
                        "python3 ~/.claude/hooks/asks.py answer 20261119-000000-deadbeef --by=panel --choice allow",
                        "echo '{}' > ~/hub/state/asks/20261119-000000-deadbeef.answer.json"):
            self.assertEqual(self.decision(self.gate("pre", {"command": command}, session=ORCH)), "deny", command)
        write = {"file_path": "/h/hub/state/asks/x.answer.json", "content": "{}"}
        self.assertEqual(self.decision(self.gate("pre", write, tool_name="Write", session=ORCH)), "deny")


if __name__ == "__main__":
    unittest.main()
