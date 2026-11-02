"""tmux-socket-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_tmux_socket_guard.py

hook をサブプロセスで呼ぶだけで、tmux は起動しない。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "tmux-socket-guard.py"


def run(command, tool_name="Bash"):
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, check=False
    )


class TmuxSocketGuardTest(unittest.TestCase):
    def assertBlocked(self, command):
        r = run(command)
        self.assertEqual(r.returncode, 2, command)
        self.assertIn("-L", r.stderr)

    def assertAllowed(self, command):
        r = run(command)
        self.assertEqual(r.returncode, 0, f"{command}: {r.stderr}")

    def test_kill_server_without_socket_is_blocked(self):
        self.assertBlocked("tmux kill-server")
        self.assertBlocked("tmux kill-ser")
        self.assertBlocked("TMUX_TMPDIR=/tmp/x/sock tmux kill-server")
        self.assertBlocked("cd /tmp && /usr/bin/tmux -f /dev/null kill-server")
        self.assertBlocked("env -u TMUX tmux kill-server")
        self.assertBlocked("echo ok\ntmux kill-server")

    def test_kill_server_with_socket_is_allowed(self):
        self.assertAllowed("tmux -L test kill-server")
        self.assertAllowed("tmux -Ltest kill-server")
        self.assertAllowed("tmux -S /tmp/x/sock kill-server")
        self.assertAllowed("tmux -f /dev/null -L test kill-server; rm -rf /tmp/x")

    def test_kill_session_is_not_kill_server(self):
        self.assertAllowed("tmux kill-session -t foo")
        self.assertAllowed("tmux kill-window -t @3")

    def test_env_isolation_without_socket_is_blocked(self):
        self.assertBlocked("TMUX_TMPDIR=/tmp/x tmux new-session -d")
        self.assertBlocked("unset TMUX; tmux new-session -d -s t")
        self.assertBlocked("export TMUX_TMPDIR=/tmp/x && tmux -L t new -d && tmux ls")

    def test_env_isolation_with_socket_is_allowed(self):
        self.assertAllowed("TMUX_TMPDIR=/tmp/x tmux -L t new-session -d")

    def test_ordinary_tmux_use_is_allowed(self):
        self.assertAllowed("tmux list-windows -a")
        self.assertAllowed("tmux capture-pane -p -t @1")
        self.assertAllowed("echo 'tmux kill-server'")
        self.assertAllowed("git log --grep tmux")

    def test_other_tools_are_ignored(self):
        r = run("tmux kill-server", tool_name="Write")
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
