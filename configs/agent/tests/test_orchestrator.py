"""orchestrator の構成と、窓口・スレッドのスキルの決まりのテスト。

実行: python3 -m unittest configs/agent/tests/test_orchestrator.py

- スレッドは AskUserQuestion を使わず、やりとりを窓口に集約する。
- orchestrator コマンドは claude agents のペインを開かず、窓口とケースボードの 2 枚にする。
  レイアウトは専用の tmux ソケット（-L）で確かめる。fish か tmux が無ければ飛ばす。
"""

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "configs" / "agent" / "skills"
THREAD = SKILLS / "agents-thread" / "SKILL.md"
ORCH = SKILLS / "agents-orchestrator" / "SKILL.md"
FISH_FN = ROOT / "configs" / "fish" / "functions" / "orchestrator.fish"


class SkillRulesTest(unittest.TestCase):
    def test_thread_does_not_use_ask_user_question(self):
        for line in THREAD.read_text(encoding="utf-8").splitlines():
            if "AskUserQuestion" in line:
                self.assertIn("使わない", line, line)

    def test_thread_reports_decisions_to_orchestrator(self):
        text = THREAD.read_text(encoding="utf-8")
        self.assertIn("要判断", text)
        self.assertIn("窓口で問いに答える", text)
        self.assertNotIn("一覧で", text)

    def test_orchestrator_relays_decisions(self):
        text = ORCH.read_text(encoding="utf-8")
        self.assertIn("### スレッドの要判断を聞く", text)
        self.assertIn("### スレッドがブロックしたとき", text)
        self.assertNotIn("代わりに答えない", text)
        self.assertNotIn("を開いて答える", text)
        self.assertNotIn("右下", text)
        self.assertNotIn("右上", text)


HARNESS = r"""
set -l sock $argv[1]
set -l fn $argv[2]
set -l mode $argv[3]
function tmux --inherit-variable sock; command tmux -L $sock $argv; end
function claude; sleep 600; end
mkdir -p $HOME/.claude/skills/agents-orchestrator/scripts
echo 'import time; time.sleep(600)' > $HOME/.claude/skills/agents-orchestrator/scripts/cases.py
source $fn
set -x TMUX dummy
if test "$mode" = old
    tmux new-session -d -x 200 -y 50 -s orchestrator -n orchestrator 'sleep 600'
    set -l right (tmux split-window -h -d -l 45% -P -F '#{pane_id}' -t orchestrator 'fish -c "claude agents --permission-mode auto"')
    tmux split-window -v -b -d -l 50% -t $right 'sleep 600'
    tmux set-option -p -t (tmux list-panes -t orchestrator -F '#{pane_id}')[2] @orchestrator_role cases
end
orchestrator >/dev/null 2>&1
orchestrator >/dev/null 2>&1
tmux list-panes -t '=orchestrator:^' -F '#{pane_left} #{@orchestrator_role} #{pane_active} #{pane_start_command}'
"""


@unittest.skipUnless(shutil.which("fish") and shutil.which("tmux"), "fish と tmux が要る")
class LayoutTest(unittest.TestCase):
    def run_layout(self, mode):
        sock = f"orchtest-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as home:
            harness = Path(home) / "harness.fish"
            harness.write_text(HARNESS, encoding="utf-8")
            env = {**os.environ, "HOME": home, "AGENT_ORCHESTRATOR_HOME": str(Path(home) / "hub")}
            try:
                out = subprocess.run(
                    ["fish", "--no-config", str(harness), sock, str(FISH_FN), mode],
                    env=env, capture_output=True, text=True, timeout=30, check=True,
                ).stdout
            finally:
                subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
        panes = []
        for line in out.splitlines():
            left, role, active, cmd = (line.split(" ", 3) + [""])[:4]
            panes.append({"left": int(left), "role": role, "active": active == "1", "cmd": cmd})
        return sorted(panes, key=lambda p: p["left"])

    def assert_two_panes(self, panes):
        self.assertEqual(len(panes), 2, panes)
        main, board = panes
        self.assertEqual(board["role"], "cases")
        self.assertIn("cases.py", board["cmd"])
        self.assertGreater(board["left"], main["left"])
        self.assertTrue(main["active"])
        for p in panes:
            self.assertNotIn("claude agents", p["cmd"])

    def test_new_session(self):
        panes = self.run_layout("new")
        self.assert_two_panes(panes)
        self.assertIn("/agents-orchestrator", panes[0]["cmd"])

    def test_old_session_drops_agents_pane(self):
        panes = [p for p in self.run_layout("old")]
        self.assertEqual(len(panes), 2, panes)
        self.assertNotIn("claude agents", " ".join(p["cmd"] for p in panes))
        self.assertEqual(panes[1]["role"], "cases")


if __name__ == "__main__":
    unittest.main()
