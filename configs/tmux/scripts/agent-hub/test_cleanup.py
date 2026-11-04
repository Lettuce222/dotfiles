"""cleanup.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_cleanup.py

git は一時ディレクトリの本物のリポジトリ（origin は bare リポジトリ）を使う。gh と tmux は偽物のスクリプトにする。
本物の tmux を使うテストは、どの tmux コマンドにも -L で専用のソケットを付ける。
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup  # noqa: E402

TASK = "some-task"
BRANCH = f"agent/{TASK}"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}

FAKE_GH = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ -n "$FAKE_GH_FAIL" ]; then echo "gh: auth required" >&2; exit 1; fi
cat "$FAKE_GH_JSON"
"""

# list-panes は FAKE_TMUX_PANES の行を出す。kill-window は記録して、その window の行を消す
FAKE_TMUX = """#!/bin/sh
echo "tmux $@" >> "$FAKE_LOG"
case "$1" in
  list-panes) cat "$FAKE_TMUX_PANES" ;;
  kill-window)
    grep -v "^$3	" "$FAKE_TMUX_PANES" > "$FAKE_TMUX_PANES.new"; mv "$FAKE_TMUX_PANES.new" "$FAKE_TMUX_PANES" ;;
  *) exit 1 ;;
esac
"""


def sh(*args, cwd=None):
    env = {**os.environ, **GIT_ENV}
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise AssertionError(f"{args}: {res.stderr}")
    return res.stdout.strip()


class Base(unittest.TestCase):
    owner_repo = "Lettuce222/dotfiles"  # 既定は main に直接 push する運用

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cleanup-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = mock.patch.dict(os.environ, {
            **GIT_ENV,
            "XDG_STATE_HOME": str(self.tmp / "state"),
            "AGENT_HUB_GH": str(self.write_exec("bin/gh", FAKE_GH)),
            "AGENT_HUB_TMUX": str(self.write_exec("bin/tmux", FAKE_TMUX)),
            "FAKE_LOG": str(self.tmp / "log"),
            "FAKE_GH_JSON": str(self.tmp / "gh.json"),
            "FAKE_TMUX_PANES": str(self.tmp / "panes"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("FAKE_GH_FAIL", None)
        patch = mock.patch.object(cleanup, "owner_repo_from_url", lambda url: self.owner_repo)
        patch.start()
        self.addCleanup(patch.stop)
        (self.tmp / "log").write_text("")
        self.write_gh([])

        self.origin = self.tmp / "origin.git"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.repo = self.tmp / "src" / "dotfiles"
        sh("git", "clone", "-q", str(self.origin), str(self.repo))
        self.commit(self.repo, "init")
        sh("git", "push", "-q", "-u", "origin", "main", cwd=self.repo)
        sh("git", "remote", "set-head", "origin", "--auto", cwd=self.repo)

        self.worktree = self.tmp / "src" / "dotfiles.worktrees" / BRANCH
        sh("git", "worktree", "add", "-q", "-b", BRANCH, str(self.worktree), "origin/main", cwd=self.repo)
        self.commit(self.worktree, "work")
        self.session = f"dotfiles.{TASK}"
        self.record = self.tmp / "state" / "agent-hub" / f"{self.session}.md"
        self.record.parent.mkdir(parents=True)
        self.record.write_text(textwrap.dedent(f"""\
            窓口（hub）のセッション名: hub
            あなたのセッション名: {self.session}
            作業場所: {self.worktree}
            作業ブランチ: {BRANCH}

            指示の本文
            """))
        self.set_panes([("@1", self.session, str(self.worktree)), ("@0", "", str(self.tmp))])

    # --- 道具

    def write_exec(self, rel, body):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        path.chmod(0o755)
        return path

    def commit(self, repo, msg):
        (Path(repo) / f"{msg}.txt").write_text(msg)
        sh("git", "add", ".", cwd=repo)
        sh("git", "commit", "-q", "-m", msg, cwd=repo)
        return sh("git", "rev-parse", "HEAD", cwd=repo)

    def set_panes(self, rows):
        Path(os.environ["FAKE_TMUX_PANES"]).write_text("".join(f"{a}\t{b}\t{c}\n" for a, b, c in rows))

    def write_gh(self, prs):
        Path(os.environ["FAKE_GH_JSON"]).write_text(json.dumps(prs))

    def log(self):
        return (self.tmp / "log").read_text()

    def push_to_main(self):
        sh("git", "push", "-q", "origin", f"{BRANCH}:main", cwd=self.worktree)

    def push_branch(self):
        sh("git", "push", "-q", "origin", BRANCH, cwd=self.worktree)

    def remote_has_branch(self):
        return bool(sh("git", "ls-remote", "--heads", str(self.origin), BRANCH))

    def local_has_branch(self):
        return bool(sh("git", "branch", "--list", BRANCH, cwd=self.repo))

    def run_cleanup(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cleanup.main([*args, self.session])
        return code, out.getvalue(), err.getvalue()

    def assert_untouched(self):
        self.assertTrue(self.worktree.exists())
        self.assertTrue(self.local_has_branch())
        self.assertTrue(self.record.exists())
        self.assertNotIn("kill-window", self.log())


class DirectPushTest(Base):
    def test_merged_cleans_everything_and_pulls(self):
        self.push_branch()
        self.push_to_main()
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 0, err)
        self.assertFalse(self.worktree.exists())
        self.assertFalse(self.local_has_branch())
        self.assertFalse(self.remote_has_branch())
        self.assertFalse(self.record.exists())
        self.assertIn("tmux kill-window -t @1", self.log())
        self.assertNotIn("-t @0", self.log())
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=self.repo), sh("git", "rev-parse", "origin/main", cwd=self.repo))
        for expected in ["merge 済み", "window @1 を閉じました", "worktree", "手元のブランチ", "origin のブランチ", "記録ファイル", "pull しました"]:
            self.assertIn(expected, out)

    def test_unmerged_stops_without_changes(self):
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("何も消さずに止まります", err)
        self.assertIn("--force-unmerged", err)
        self.assert_untouched()

    def test_branch_without_commits_is_not_merged(self):
        # 作ったばかりのブランチは origin/main の祖先だが、merge 済みとは扱わない
        sh("git", "reset", "-q", "--hard", "origin/main", cwd=self.worktree)
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("作ったときからのコミットがありません", err)
        self.assert_untouched()

    def test_force_unmerged_keeps_remote_branch(self):
        self.push_branch()
        code, out, err = self.run_cleanup("--force-unmerged")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.worktree.exists())
        self.assertFalse(self.local_has_branch())
        self.assertTrue(self.remote_has_branch())
        self.assertFalse(self.record.exists())
        self.assertIn("origin のブランチ agent/some-task は残しました", out)

    def test_dry_run_changes_nothing(self):
        self.push_branch()
        self.push_to_main()
        code, out, err = self.run_cleanup("--dry-run")
        self.assertEqual(code, 0, err)
        self.assert_untouched()
        self.assertTrue(self.remote_has_branch())
        self.assertNotEqual(sh("git", "rev-parse", "HEAD", cwd=self.repo), sh("git", "rev-parse", "origin/main", cwd=self.repo))
        lines = out.splitlines()
        self.assertTrue(lines and all(line.startswith("予定: ") for line in lines), out)
        self.assertIn("git pull --ff-only", out)

    def test_other_window_stops_then_kill_other_windows(self):
        self.push_to_main()
        self.set_panes([("@1", self.session, str(self.worktree)), ("@5", "", str(self.worktree / "sub"))])
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("@5", err)
        self.assert_untouched()

        code, out, err = self.run_cleanup("--kill-other-windows")
        self.assertEqual(code, 0, err)
        self.assertIn("tmux kill-window -t @1", self.log())
        self.assertIn("tmux kill-window -t @5", self.log())

    def test_dirty_worktree_stops_before_anything(self):
        self.push_to_main()
        (self.worktree / "untracked.txt").write_text("x")
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("commit されていない変更", err)
        self.assertIn("untracked.txt", err)
        self.assert_untouched()

    def test_no_pull_when_repo_not_on_default_branch(self):
        self.push_to_main()
        sh("git", "switch", "-q", "-c", "other", cwd=self.repo)
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 0, err)
        self.assertIn("'other' を checkout しているので pull しません", out)

    def test_no_pull_when_repo_dirty(self):
        self.push_to_main()
        (self.repo / "init.txt").write_text("changed")
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 0, err)
        self.assertIn("作業ツリーに変更があるので pull しません", out)

    def test_already_removed_worktree_is_pruned(self):
        self.push_to_main()
        shutil.rmtree(self.worktree)
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 0, err)
        self.assertIn("登録を外しました", out)
        self.assertFalse(self.local_has_branch())

    def test_bad_session_and_missing_record(self):
        for name in ["../x", "a/b", ""]:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(cleanup.main([name]), 1)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cleanup.main(["dotfiles.nothing"]), 1)
        self.assertIn("記録ファイルがありません", err.getvalue())


class PullRequestTest(Base):
    owner_repo = "someone/project"

    def pr(self, number, state, oid):
        sh("git", "push", "-q", "origin", f"{oid}:refs/pull/{number}/head", cwd=self.worktree)
        return {"number": number, "state": state, "headRefOid": oid, "url": f"https://example.invalid/{number}"}

    def test_merged_pr_containing_branch(self):
        self.push_branch()
        head = sh("git", "rev-parse", "HEAD", cwd=self.worktree)
        self.write_gh([self.pr(3, "MERGED", head)])
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 0, err)
        self.assertIn("PR #3 が MERGED", out)
        self.assertIn("pr list --head agent/some-task --state all", self.log())
        self.assertIn("-R someone/project", self.log())
        self.assertFalse(self.remote_has_branch())
        self.assertFalse(self.record.exists())

    def test_open_pr_stops(self):
        head = sh("git", "rev-parse", "HEAD", cwd=self.worktree)
        self.write_gh([self.pr(4, "OPEN", head)])
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("#4 OPEN", err)
        self.assert_untouched()

    def test_local_commits_missing_from_merged_pr_stop(self):
        old = sh("git", "rev-parse", "HEAD", cwd=self.worktree)
        self.write_gh([self.pr(5, "MERGED", old)])
        self.commit(self.worktree, "later")
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("含む PR がありません", err)
        self.assert_untouched()

    def test_no_pr_and_gh_failure_stop(self):
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("PR がありません", err)
        os.environ["FAKE_GH_FAIL"] = "1"
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn("gh pr list に失敗しました", err)
        self.assert_untouched()

    def test_closed_pr_with_force_unmerged(self):
        self.push_branch()
        head = sh("git", "rev-parse", "HEAD", cwd=self.worktree)
        self.write_gh([self.pr(6, "CLOSED", head)])
        code, out, err = self.run_cleanup("--force-unmerged")
        self.assertEqual(code, 0, err)
        self.assertTrue(self.remote_has_branch())
        self.assertFalse(self.worktree.exists())


class UrlTest(unittest.TestCase):
    def test_owner_repo_from_url(self):
        for url in ["git@github.com:Lettuce222/dotfiles.git", "https://github.com/Lettuce222/dotfiles",
                    "ssh://git@github.com/Lettuce222/dotfiles.git\n"]:
            self.assertEqual(cleanup.owner_repo_from_url(url), "Lettuce222/dotfiles")
        self.assertEqual(cleanup.owner_repo_from_url("/tmp/x.git"), "")


@unittest.skipUnless(shutil.which("tmux"), "tmux がありません")
class RealTmuxTest(Base):
    """本物の tmux を、専用のソケット（-L）の上でだけ動かす。"""

    def setUp(self):
        super().setUp()
        self.socket = f"cleanup-test-{uuid.uuid4().hex[:8]}"
        real = shutil.which("tmux")
        wrapper = self.write_exec("bin/tmux-real", f'#!/bin/sh\nexec "{real}" -L {self.socket} "$@"\n')
        os.environ["AGENT_HUB_TMUX"] = str(wrapper)
        self.addCleanup(subprocess.run, [real, "-L", self.socket, "kill-server"], capture_output=True)
        self.tmux = lambda *a: sh(str(wrapper), *a)
        self.tmux("new-session", "-d", "-s", "t", "-c", str(self.tmp))
        self.worker_window = self.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-c", str(self.worktree))
        self.tmux("set-option", "-w", "-t", self.worker_window, "@agent-hub-worker", self.session)

    def windows(self):
        return self.tmux("list-windows", "-a", "-F", "#{window_id}").split()

    def test_kills_worker_window_only(self):
        self.push_to_main()
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 0, err)
        self.assertNotIn(self.worker_window, self.windows())
        self.assertEqual(len(self.windows()), 1)

    def test_other_window_in_worktree_blocks(self):
        self.push_to_main()
        other = self.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-c", str(self.worktree))
        code, out, err = self.run_cleanup()
        self.assertEqual(code, 1)
        self.assertIn(other, err)
        self.assertIn(self.worker_window, self.windows())


if __name__ == "__main__":
    unittest.main()
