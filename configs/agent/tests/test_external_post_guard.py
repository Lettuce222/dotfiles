"""external-post-guard.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_external_post_guard.py

hook をサブプロセスで呼ぶ。git と gh は PATH の先頭に置いた偽物に置き換え、
今のブランチと gh pr view の結果を環境変数で与える。
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

FAKE_GIT = """\
#!/bin/sh
# git symbolic-ref --quiet --short HEAD
printf '%s\\n' "$FAKE_BRANCH"
"""

FAKE_GH = """\
#!/bin/sh
# gh pr view [target] --json ...
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
[ -n "$FAKE_PR" ] || exit 1
printf '%s\\n' "$FAKE_PR"
"""


def pr(head="agent/task", draft=True, state="OPEN", cross=False):
    return json.dumps({"headRefName": head, "isDraft": draft, "state": state, "isCrossRepository": cross})


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        for name, body in (("git", FAKE_GIT), ("gh", FAKE_GH)):
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        self.gh_log = Path(self.tmp.name) / "gh.log"
        self.base_env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_BRANCH": "agent/task",
            "FAKE_PR": pr(),
            "FAKE_GH_LOG": str(self.gh_log),
        }

    def run_hook(self, tool_input, tool_name="Bash", worker=True, **env):
        full_env = dict(self.base_env)
        if worker:
            full_env["AGENT_HUB_WORKER"] = "repo.task"
            full_env["AGENT_HUB_BRANCH"] = "agent/task"
        full_env.update(env)
        payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": self.tmp.name}
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
        )

    def bash(self, command, **kw):
        return self.run_hook({"command": command}, **kw)

    def assertAsk(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def assertPass(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")

    def assertBlockedToHub(self, r):
        self.assertEqual(r.returncode, 2)
        self.assertIn("hub", r.stderr)
        self.assertIn("要判断", r.stderr)

    # --- 文面の決まり（hub でも worker でも同じ） ---

    def test_unlinked_ticket_is_blocked_everywhere(self):
        for worker in (True, False):
            r = self.bash("gh pr create --draft --title t --body 'fixes ABC-12'", worker=worker)
            self.assertEqual(r.returncode, 2)
            self.assertIn("ABC-12", r.stderr)

    def test_date_without_weekday_is_blocked(self):
        r = self.bash("gh pr comment --body 'due 11/4'")
        self.assertEqual(r.returncode, 2)
        self.assertIn("11/4", r.stderr)

    # --- hub とそれ以外のセッション ---

    def test_non_worker_gets_ask(self):
        self.assertAsk(self.bash("gh pr create --draft --title t --body ok", worker=False))
        self.assertAsk(self.run_hook({"text": "hello"}, tool_name="mcp__slack__send", worker=False))

    def test_non_gh_command_passes(self):
        self.assertPass(self.bash("git status", worker=False))

    def test_gh_api_read_passes(self):
        self.assertPass(self.bash("gh api repos/o/r/pulls", worker=False))
        self.assertPass(self.bash("gh api -X GET search/issues -f q=x", worker=False))

    def test_gh_api_write_asks(self):
        self.assertAsk(self.bash("gh api repos/o/r/issues -f title=x -f body=ok", worker=False))

    # --- worker: 承認範囲の中 ---

    def test_worker_own_draft_create_passes(self):
        self.assertPass(self.bash("gh pr create --draft --title t --body ok"))
        self.assertPass(self.bash("gh pr create -d --title t --body-file /nonexistent"))

    def test_worker_branch_falls_back_to_worker_name(self):
        self.assertPass(self.bash("gh pr create --draft --title t --body ok", AGENT_HUB_BRANCH=""))

    def test_worker_own_draft_edit_and_comment_pass(self):
        self.assertPass(self.bash("gh pr edit --title new --body ok"))
        self.assertPass(self.bash("gh pr comment --body ok"))
        self.assertPass(self.bash("gh pr comment 12 --body ok"))
        self.assertIn("pr view 12 --json", self.gh_log.read_text())

    def test_heredoc_in_quoted_body_passes(self):
        command = textwrap.dedent(
            """\
            gh pr create --draft --title t --body "$(cat <<'EOF'
            概要 && 詳細
            EOF
            )"
            """
        )
        self.assertPass(self.bash(command))

    # --- worker: 承認範囲の外 ---

    def test_worker_non_draft_create_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr create --title t --body ok"))

    def test_worker_create_on_other_branch_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr create --draft --body ok", FAKE_BRANCH="main"))
        self.assertBlockedToHub(self.bash("gh pr create --draft --head other --body ok"))

    def test_worker_other_repo_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr create --draft -R o/other --body ok"))

    def test_worker_compound_command_is_blocked(self):
        self.assertBlockedToHub(self.bash("cd /elsewhere && gh pr create --draft --body ok"))

    def test_worker_others_pr_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr comment 7 --body ok", FAKE_PR=pr(head="feature/x")))
        self.assertBlockedToHub(self.bash("gh pr comment 7 --body ok", FAKE_PR=pr(cross=True)))

    def test_worker_ready_or_closed_pr_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr edit --body ok", FAKE_PR=pr(draft=False)))
        self.assertBlockedToHub(self.bash("gh pr comment --body ok", FAKE_PR=pr(state="MERGED")))

    def test_worker_unknown_pr_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr comment --body ok", FAKE_PR=""))

    def test_worker_reviewer_is_blocked(self):
        self.assertBlockedToHub(self.bash("gh pr edit --add-reviewer someone"))

    def test_worker_issue_review_and_api_are_blocked(self):
        self.assertBlockedToHub(self.bash("gh issue create --title t --body ok"))
        self.assertBlockedToHub(self.bash("gh pr review 3 --approve --body ok"))
        self.assertBlockedToHub(self.bash("gh api repos/o/r/issues -f body=ok"))

    def test_worker_mcp_post_is_blocked(self):
        self.assertBlockedToHub(self.run_hook({"text": "hello"}, tool_name="mcp__slack__send"))

    def test_worker_mcp_without_prose_passes(self):
        self.assertPass(self.run_hook({"query": "x"}, tool_name="mcp__slack__search"))


if __name__ == "__main__":
    unittest.main()
