"""agent-ui-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_agent_ui_guard.py

hook をサブプロセスで呼ぶだけで、orca・osascript・tmux は動かさない。承認の記録は
一時フォルダーに置き、`claude agents --json` は PATH に置いた偽の claude が返す。
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
HOOK = HOOKS / "agent-ui-guard.py"
GATE = HOOKS / "approval-gate.py"
APPROVALS = HOOKS / "approvals.py"

ORCH = "sess-orchestrator"
WORKER = "sess-worker"
WORKER_NAME = "impl-x-y"


class AgentUiGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.dir = root / "approvals"
        bindir = root / "bin"
        bindir.mkdir()
        agents = root / "agents.json"
        agents.write_text(
            json.dumps(
                [
                    {"sessionId": ORCH, "name": "orchestrator", "kind": "background", "status": "busy"},
                    {"sessionId": WORKER, "name": WORKER_NAME, "kind": "background", "status": "busy"},
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

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script, args, command, session=WORKER, tool_name="Bash"):
        payload = {"tool_name": tool_name, "tool_input": {"command": command}, "session_id": session}
        return subprocess.run(
            [sys.executable, str(script), *args],
            input=json.dumps(payload),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def decision(self, command, session=WORKER):
        r = self.run_script(HOOK, [], command, session)
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return None
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]

    def assertStopped(self, command):
        self.assertEqual(self.decision(command), "ask", command)

    def assertPasses(self, command):
        self.assertIsNone(self.decision(command), command)

    # --- Orca の CLI ---

    def test_orca_reads_pass(self):
        for command in (
            "orca status --json",
            "orca worktree ps --json",
            "orca terminal read --terminal t1 --json",
            "orca agent list",
            "orca plugin list",
            "orca plugin logs lettuce222.hub-local",
            "orca plugin validate configs/orca/plugins/hub",
            "orca plugin inspect . --json",
            "orca plugin shot lettuce222.hub-local --out /tmp/x.png --json",
            "orca repo list",
            "orca project list --json",
            "orca agent-context --json",
            "orca plugin dev request --help",
            "orca --help",
            "orca",
            "/Applications/Orca.app/Contents/Resources/bin/orca worktree ps",
            "orca --environment local worktree ps",
        ):
            self.assertPasses(command)

    def test_orca_writes_are_stopped(self):
        for command in (
            "orca computer click --x 10 --y 20",
            "orca computer type-text hello",
            "orca terminal send --terminal t1 --text yes --enter",
            "orca plugin dev request lettuce222.hub-local approve '{}'",
            "orca plugin dev load ~/.config/orca/plugins/hub --approve ap1-x",
            "orca plugin dev reload",
            "orca plugin install ~/.config/orca/plugins/hub",
            "orca plugin update lettuce222.hub-local --approve ap1-x",
            "orca plugin enable lettuce222.hub-local --approve ap1-x",
            "orca plugin catalog add https://example.com/c.json --approve x",
            "orca plugin open lettuce222.hub-local",
            "orca plugin shot lettuce222.hub-local --act '[{\"press\":{\"text\":\"承認\"}}]'",
            "orca plugin shot lettuce222.hub-local --scenario approve",
            "orca repo add --path ~/hub --kind folder",
            "/Applications/Orca.app/Contents/Resources/bin/orca terminal send --text x",
            "cd /tmp && orca computer click --x 1 --y 1",
            "env FOO=1 orca terminal send --text x",
            "sh -c 'orca terminal send --text x'",
            "echo $(orca computer click --x 1 --y 1)",
            "orca --environment local computer click --x 1 --y 1",
        ):
            self.assertStopped(command)

    def test_heredoc_bodies_are_data_unless_a_shell_runs_them(self):
        script = "python3 - <<'EOF'\nprint(\"orca-milestone's card\")\nrun('orca terminal send')\nEOF\necho done"
        self.assertPasses(script)
        self.assertPasses("cat > /tmp/x.md <<EOF\nthe plugin's orca computer click\nEOF")
        self.assertStopped("bash <<'EOF'\norca computer click --x 1 --y 1\nEOF")
        self.assertStopped("python3 - <<'EOF'\nx = 1\nEOF\norca terminal send --text y")

    def test_unreadable_command_is_read_as_text(self):
        self.assertStopped("orca terminal send --text 'it''s")
        self.assertPasses("echo \"orca-milestone's\" 'x")

    def test_orca_in_text_is_not_a_call(self):
        self.assertPasses("echo 'orca computer click'")
        self.assertPasses("git log --grep 'orca terminal send'")
        self.assertPasses("grep -rn orca configs/orca")

    # --- osascript と cliclick ---

    def test_osascript_ui_scripting_is_stopped(self):
        self.assertStopped("osascript -e 'tell application \"System Events\" to keystroke \"1\"'")
        self.assertStopped("osascript -e 'tell application \"Orca\" to activate' -e 'click at {10, 10}'")
        self.assertStopped("osascript -l JavaScript -e \"Application('System Events').keyCode(36)\"")
        self.assertStopped("cliclick c:100,200")

    def test_osascript_script_file_is_read(self):
        ui = self.root / "ui.applescript"
        ui.write_text('tell application "System Events" to key code 36\n')
        plain = self.root / "plain.applescript"
        plain.write_text('display notification "done"\n')
        self.assertStopped(f"osascript {ui}")
        self.assertPasses(f"osascript {plain}")
        self.assertStopped(f"osascript {self.root / 'missing.applescript'}")
        self.assertStopped("osascript < script.applescript")

    def test_osascript_without_ui_passes(self):
        self.assertPasses("osascript -e 'display notification \"done\" with title \"Claude\"'")

    # --- tmux ---

    def test_tmux_typing_is_stopped(self):
        for command in (
            "tmux send-keys -t orchestrator:0.0 1 Enter",
            "tmux send -t %3 y",
            "tmux send-k -t %3 y",
            "tmux paste-buffer -t %3",
            "tmux pasteb -t %3",
            "tmux send-prefix -t %3",
            "tmux source-file /tmp/keys.conf",
            "tmux list-panes \\; send-keys -t %3 y",
            "tmux if-shell true 'send-keys -t %3 y'",
            "tmux -C attach",
            "/usr/bin/tmux -f /dev/null send-keys -t %3 y",
        ):
            self.assertStopped(command)

    def test_tmux_on_another_server_and_reads_pass(self):
        for command in (
            "tmux -L test send-keys -t t:0 hi Enter",
            "tmux -S /tmp/x/sock paste-buffer",
            "tmux list-panes -a",
            "tmux capture-pane -p -t %3",
            "tmux display -p '#{pane_id}'",
        ):
            self.assertPasses(command)

    def test_unrelated_commands_pass(self):
        self.assertPasses("git status")
        self.assertPasses("ls ~/.config/orca/plugins")
        self.assertPasses("python3 -m unittest")

    def test_other_tools_are_ignored(self):
        r = self.run_script(HOOK, [], "orca computer click", tool_name="Write")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    # --- 承認の記録 ---

    def approve(self, command, worker=None):
        args = ["add", "bash", "--command", command] + (["--worker", worker] if worker else [])
        r = subprocess.run(
            [sys.executable, str(APPROVALS), *args],
            env={**self.env, "CLAUDE_CODE_SESSION_ID": ORCH},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def records(self):
        return sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []

    def test_record_lets_the_call_through_once(self):
        command = "orca plugin update lettuce222.hub-local --approve ap1-x"
        self.approve(command, worker=WORKER_NAME)
        self.assertEqual(self.decision(command), "allow")
        self.assertEqual(self.records(), [])
        self.assertEqual(self.decision(command), "ask")

    def test_record_is_for_its_session_only(self):
        command = "orca plugin update lettuce222.hub-local --approve ap1-x"
        self.approve(command, worker=WORKER_NAME)
        self.assertEqual(self.decision(command, session=ORCH), "ask")
        self.assertEqual(len(self.records()), 1)

    def test_gate_leaves_these_calls_to_the_guard(self):
        command = "orca plugin update lettuce222.hub-local --approve ap1-x"
        self.approve(command, worker=WORKER_NAME)
        r = self.run_script(GATE, ["pre"], command)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.decision(command), "allow")


class PanelFirstTest(unittest.TestCase):
    """--panel: 窓口の止めた呼び出しを、ダイアログの前に Hub パネルで聞く（PreToolUse で待つ）。"""

    COMMAND = "orca hub-permission-test"

    def setUp(self):
        AgentUiGuardTest.setUp(self)
        self.asks_dir = self.root / "asks"
        self.env["AGENT_ASKS_DIR"] = str(self.asks_dir)
        self.env["AGENT_PERMISSION_WAIT"] = "5"
        sys.path.insert(0, str(HOOKS))
        import importlib
        self.asks = importlib.import_module("asks")

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, command=COMMAND, session=ORCH, panel=True):
        proc = subprocess.Popen(
            [sys.executable, str(HOOK), *(["--panel"] if panel else [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, text=True,
        )
        proc.stdin.write(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session}))
        proc.stdin.close()
        proc.stdin = None  # Python 3.9 などの古い communicate() は閉じた stdin を flush して ValueError になる
        return proc

    def written(self, proc):
        for _ in range(200):
            found = [p for p in self.asks_dir.glob("*.json") if not p.name.endswith(".answer.json")] if self.asks_dir.is_dir() else []
            if found:
                return found[0]
            if proc.poll() is not None:
                self.fail(proc.stderr.read())
            time.sleep(0.05)
        self.fail("no ask was written")

    def answer(self, path, choice, text=None):
        import hashlib
        from unittest import mock
        shown = hashlib.sha256(path.read_bytes()).hexdigest()
        with mock.patch.dict(os.environ, {"AGENT_ASKS_DIR": str(self.asks_dir)}):
            self.assertEqual(self.asks.answer(path.stem, "panel", choice, shown, text=text, panel_check=lambda: True)[0], 0)

    def finish(self, proc):
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, err)
        return json.loads(out)["hookSpecificOutput"]

    def test_the_panel_answers_before_any_dialog(self):
        proc = self.start()
        path = self.written(proc)
        self.assertEqual(json.loads(path.read_text())["tool_input"], {"command": self.COMMAND})
        self.answer(path, "allow")
        self.assertEqual(self.finish(proc)["permissionDecision"], "allow")
        proc = self.start()
        self.answer(self.written(proc), "deny", text="まだ")
        out = self.finish(proc)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("まだ", out["permissionDecisionReason"])
        self.assertEqual(list(self.asks_dir.glob("*.json")), [])

    def test_without_an_answer_the_dialog_asks(self):
        proc = self.start()
        self.answer(self.written(proc), "terminal")
        self.assertEqual(self.finish(proc)["permissionDecision"], "ask")
        self.env["AGENT_PERMISSION_WAIT"] = "1"
        proc = self.start()
        self.written(proc)
        self.assertEqual(self.finish(proc)["permissionDecision"], "ask")

    def test_only_the_orchestrator_with_panel_waits(self):
        for session, panel in ((WORKER, True), (ORCH, False)):
            r = self.finish(self.start(session=session, panel=panel))
            self.assertEqual(r["permissionDecision"], "ask", (session, panel))
        self.assertFalse(self.asks_dir.exists() and list(self.asks_dir.glob("*.json")))
        # A command the guard lets through never reaches the panel.
        proc = self.start(command="orca status")
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()
