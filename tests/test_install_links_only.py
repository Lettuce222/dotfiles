"""install.sh --links-only / --dry-run のテスト。

実行: python3 -m unittest tests/test_install_links_only.py

一時ディレクトリに install.sh と小さな configs を置き、別の一時ディレクトリを HOME にして実行する。
brew・fish・chsh などは PATH の先頭に置いた偽物に差し替え、呼ばれたら記録する。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"
INSTALLERS = ["brew", "fish", "chsh", "sudo", "curl", "mise", "npm", "defaults"]


class InstallTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="install-links-only-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "dotfiles"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.log = self.tmp / "installers.log"
        self.make_repo(self.repo)
        self.make_stubs()

    def make_repo(self, repo):
        configs = repo / "configs"
        (configs / "foo").mkdir(parents=True)
        (configs / "foo" / "config").write_text("foo\n")
        (configs / "bar").mkdir()
        (configs / "claude").mkdir()
        (configs / "claude" / "statusline.sh").write_text("#!/bin/sh\n")
        (configs / "claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"command": "a"}]}}))
        (configs / "agent" / "skills" / "demo").mkdir(parents=True)
        (configs / "agent" / "AGENTS.md").write_text("# agents\n")
        (configs / "agent" / "hooks").mkdir()
        (configs / "agent" / "hooks" / "guard.py").write_text("print()\n")
        (configs / "hammerspoon").mkdir()
        shutil.copy(INSTALL_SH, repo / "install.sh")

    def make_stubs(self):
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in INSTALLERS:
            stub = self.bin / name
            stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.log}"\n')
            stub.chmod(0o755)

    def run_install(self, *args, repo=None, check=True):
        repo = repo or self.repo
        env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join([str(self.bin), str(Path(sys.executable).parent), "/usr/bin", "/bin"]),
            "SHELL": str(self.bin / "fish"),
            "TMPDIR": str(self.tmp),
        }
        r = subprocess.run(
            ["sh", str(repo / "install.sh"), *args], env=env, capture_output=True, text=True, check=False
        )
        if check:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def installer_calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def link(self, rel):
        return os.readlink(self.home / rel)

    def snapshot(self):
        out = {}
        for path in sorted(self.home.rglob("*")):
            rel = str(path.relative_to(self.home))
            if path.is_symlink():
                out[rel] = ("link", os.readlink(path))
            elif path.is_file():
                out[rel] = ("file", path.read_text())
            else:
                out[rel] = ("dir",)
        return out


class InstallLinksOnlyTest(InstallTestCase):
    def test_links_everything_and_reports_each_change(self):
        r = self.run_install("--links-only")
        configs = self.repo / "configs"
        self.assertEqual(self.link(".config/foo"), str(configs / "foo"))
        self.assertEqual(self.link(".config/bar"), str(configs / "bar"))
        self.assertFalse((self.home / ".config" / "claude").exists())
        self.assertFalse((self.home / ".config" / "agent").exists())
        self.assertEqual(self.link(".claude/statusline.sh"), str(configs / "claude" / "statusline.sh"))
        self.assertFalse((self.home / ".claude" / "settings.json").is_symlink())
        self.assertEqual(self.link(".claude/CLAUDE.md"), str(configs / "agent" / "AGENTS.md"))
        self.assertEqual(self.link(".claude/skills/demo"), str(configs / "agent" / "skills" / "demo"))
        self.assertEqual(self.link(".claude/hooks/guard.py"), str(configs / "agent" / "hooks" / "guard.py"))
        self.assertEqual(self.link(".hammerspoon"), str(configs / "hammerspoon"))
        self.assertTrue(os.access(configs / "agent" / "hooks" / "guard.py", os.X_OK))

        settings = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertEqual(settings, {"hooks": {"Stop": [{"command": "a"}]}})

        lines = r.stdout.splitlines()
        self.assertIn(f"link {self.home}/.config/foo -> {configs}/foo", lines)
        self.assertIn(f"write {self.home}/.claude/settings.json", lines)
        self.assertNotIn("変更なし", r.stdout)
        self.assertEqual(self.installer_calls(), "")

    def test_second_run_changes_nothing(self):
        self.run_install("--links-only")
        before = self.snapshot()
        r = self.run_install("--links-only")
        self.assertEqual(r.stdout, "変更なし\n")
        self.assertEqual(self.snapshot(), before)
        r = self.run_install("--dry-run")
        self.assertEqual(r.stdout, "(dry-run) 変更なし\n")

    def test_dry_run_changes_nothing(self):
        r = self.run_install("--dry-run")
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertIn(f"(dry-run) link {self.home}/.config/foo -> {self.repo}/configs/foo", r.stdout.splitlines())
        self.assertIn(f"(dry-run) write {self.home}/.claude/settings.json", r.stdout.splitlines())
        self.assertEqual(self.installer_calls(), "")

    def test_never_replaces_real_files(self):
        (self.home / ".config" / "foo").mkdir(parents=True)
        (self.home / ".config" / "foo" / "mine").write_text("keep\n")
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "CLAUDE.md").write_text("keep\n")
        (self.home / ".hammerspoon").write_text("keep\n")

        r = self.run_install("--links-only")

        self.assertEqual((self.home / ".config" / "foo" / "mine").read_text(), "keep\n")
        self.assertEqual(sorted(p.name for p in (self.home / ".config" / "foo").iterdir()), ["mine"])
        self.assertEqual((self.home / ".claude" / "CLAUDE.md").read_text(), "keep\n")
        self.assertEqual((self.home / ".hammerspoon").read_text(), "keep\n")
        self.assertIn(f"skip: {self.home}/.config/foo is not a symlink", r.stdout)
        self.assertIn(f"skip: {self.home}/.claude/CLAUDE.md is not a symlink", r.stdout)
        self.assertIn(f"skip: {self.home}/.hammerspoon is not a symlink", r.stdout)
        # The rest is still linked.
        self.assertTrue((self.home / ".config" / "bar").is_symlink())

    def test_relinks_symlinks_that_point_elsewhere(self):
        (self.home / ".config").mkdir()
        (self.home / ".config" / "foo").symlink_to("/nonexistent/old")
        r = self.run_install("--links-only")
        self.assertEqual(self.link(".config/foo"), str(self.repo / "configs" / "foo"))
        self.assertIn(
            f"relink {self.home}/.config/foo -> {self.repo}/configs/foo (was /nonexistent/old)", r.stdout.splitlines()
        )

    def test_rewrites_generated_settings_with_a_diff_summary(self):
        self.run_install("--links-only")
        local = self.repo / "configs" / "claude" / "settings.local.json"
        local.write_text(json.dumps({"hooks": {"PreToolUse": [{"command": "guard"}]}, "model": "x"}))

        r = self.run_install("--dry-run")
        self.assertIn(f"(dry-run) rewrite {self.home}/.claude/settings.json:", r.stdout)
        self.assertNotIn("PreToolUse", (self.home / ".claude" / "settings.json").read_text())

        r = self.run_install("--links-only")
        self.assertIn(f"rewrite {self.home}/.claude/settings.json:", r.stdout)
        self.assertIn('    + hooks.PreToolUse: [{"command": "guard"}]', r.stdout)
        self.assertIn('    + model: "x"', r.stdout)
        settings = (self.home / ".claude" / "settings.json").read_text()
        self.assertIn("PreToolUse", settings)
        self.assertEqual((self.home / ".claude" / "settings.json.generated").read_text(), settings)
        self.assertEqual(self.run_install("--links-only").stdout, "変更なし\n")

    def test_keeps_settings_changed_outside_install(self):
        self.run_install("--links-only")
        dest = self.home / ".claude" / "settings.json"
        edited = json.dumps({"hooks": {"Stop": [{"command": "a"}]}, "enabledPlugins": {"p": True}})
        dest.write_text(edited)

        r = self.run_install("--links-only")

        self.assertEqual(dest.read_text(), edited)
        self.assertEqual(list((self.home / ".claude").glob("settings.json.bak.*")), [])
        self.assertIn(f"skip: {dest} was changed outside install.sh", r.stdout)
        self.assertIn("    - enabledPlugins", r.stdout)

    def test_does_not_link_backups(self):
        claude = self.repo / "configs" / "claude"
        (claude / "settings.local.json.bak.20261110142011").write_text("{}")
        (claude / "statusline.sh.bak").write_text("")
        self.run_install("--links-only")
        self.assertEqual(sorted(p.name for p in (self.home / ".claude").glob("*.bak*")), [])
        self.assertTrue((self.home / ".claude" / "statusline.sh").is_symlink())

    def test_replaces_old_settings_symlink(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "settings.json").symlink_to(self.repo / "configs" / "claude" / "settings.json")
        r = self.run_install("--links-only")
        self.assertFalse((self.home / ".claude" / "settings.json").is_symlink())
        self.assertIn(f"replace symlink {self.home}/.claude/settings.json with generated settings", r.stdout)

    def test_refuses_to_run_from_a_worktree(self):
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.hooksPath=/dev/null"]
        subprocess.run([*git, "init", "-q", str(self.repo)], check=True)
        subprocess.run([*git, "-C", str(self.repo), "add", "."], check=True)
        subprocess.run([*git, "-C", str(self.repo), "commit", "-qm", "init"], check=True)
        worktree = self.tmp / "wt"
        subprocess.run([*git, "-C", str(self.repo), "worktree", "add", "-q", str(worktree)], check=True)

        r = self.run_install("--dry-run", repo=worktree, check=False)

        self.assertEqual(r.returncode, 1)
        self.assertIn("not a git worktree", r.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_rejects_unknown_options(self):
        r = self.run_install("--link-only", check=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Usage:", r.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.installer_calls(), "")

    def test_full_install_still_runs_the_installers(self):
        r = self.run_install()
        self.assertIn("Phase 2", r.stdout)
        self.assertIn("fish -c", self.installer_calls())
        self.assertEqual(self.link(".config/foo"), str(self.repo / "configs" / "foo"))


class GitIgnoreTest(InstallTestCase):
    """configs/git/ignore.shared から gitignore 済みの configs/git/ignore を書くテスト。"""

    # Claude Code が ~/.config/git/ignore に書き足す形（空行と 1 行）
    CLAUDE_APPEND = "\n**/.claude/.cc-writes/\n"

    def make_repo(self, repo):
        super().make_repo(repo)
        (repo / "configs" / "git").mkdir()
        self.shared = repo / "configs" / "git" / "ignore.shared"
        self.shared.write_text("**/.claude/settings.local.json\n**/.claude/worktrees/\n")
        self.dest = repo / "configs" / "git" / "ignore"

    def block(self, body):
        return (
            "# >>> dotfiles: configs/git/ignore.shared から install.sh が書く。ここから下の区切りまでは直さない\n"
            f"{body}# <<< dotfiles\n"
        )

    def check_ignore(self, path):
        # git が ~/.config/git/ignore（configs/git への symlink の先）を読むかを、Claude Code と同じ方法で確かめる。
        work = self.tmp / "work"
        if not (work / ".git").exists():
            subprocess.run(["git", "init", "-q", str(work)], check=True)
        env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1"}
        r = subprocess.run(["git", "-C", str(work), "check-ignore", "-q", "--", path], env=env, check=False)
        return r.returncode == 0

    def test_writes_the_shared_rules_into_a_block(self):
        r = self.run_install("--links-only")
        self.assertEqual(self.dest.read_text(), self.block(self.shared.read_text()))
        self.assertIn(f"write {self.dest} from {self.shared}", r.stdout.splitlines())
        self.assertEqual(self.link(".config/git"), str(self.repo / "configs" / "git"))
        self.assertTrue(self.check_ignore(".claude/worktrees/x"))
        self.assertFalse(self.check_ignore(".claude/.cc-writes/sample-file.txt"))

    def test_keeps_lines_appended_by_other_tools(self):
        self.run_install("--links-only")
        with self.dest.open("a") as f:
            f.write(self.CLAUDE_APPEND)
        self.assertTrue(self.check_ignore(".claude/.cc-writes/sample-file.txt"))

        # 変わっていなければ書き直さない
        self.assertEqual(self.run_install("--links-only").stdout, "変更なし\n")

        self.shared.write_text("**/.claude/worktrees/\n.DS_Store\n")
        r = self.run_install("--dry-run")
        self.assertIn(f"(dry-run) update {self.dest} from {self.shared}", r.stdout.splitlines())
        self.assertNotIn(".DS_Store", self.dest.read_text())

        r = self.run_install("--links-only")
        self.assertIn(f"update {self.dest} from {self.shared}", r.stdout.splitlines())
        self.assertEqual(self.dest.read_text(), self.block("**/.claude/worktrees/\n.DS_Store\n") + self.CLAUDE_APPEND)
        self.assertTrue(self.check_ignore(".claude/.cc-writes/sample-file.txt"))
        self.assertTrue(self.check_ignore(".DS_Store"))
        self.assertFalse(self.check_ignore(".claude/settings.local.json"))
        self.assertEqual(self.run_install("--links-only").stdout, "変更なし\n")

    def test_keeps_an_old_file_without_a_block_below_the_block(self):
        self.dest.write_text("**/.claude/worktrees/\n" + self.CLAUDE_APPEND)
        self.run_install("--links-only")
        self.assertEqual(
            self.dest.read_text(), self.block(self.shared.read_text()) + "**/.claude/worktrees/\n" + self.CLAUDE_APPEND
        )

    def test_shared_file_without_a_trailing_newline(self):
        self.shared.write_text("a\nb")
        self.run_install("--links-only")
        self.assertEqual(self.dest.read_text(), self.block("a\nb\n"))

    def test_full_install_writes_the_file(self):
        r = self.run_install()
        self.assertIn(f"Generated {self.dest}", r.stdout)
        self.assertEqual(self.dest.read_text(), self.block(self.shared.read_text()))


class RepositoryLayoutTest(unittest.TestCase):
    def test_global_gitignore_is_not_tracked(self):
        root = INSTALL_SH.parent
        self.assertTrue((root / "configs" / "git" / "ignore.shared").is_file())
        r = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", "--no-index", "configs/git/ignore"], check=False
        )
        self.assertEqual(r.returncode, 0, "configs/git/ignore must be gitignored")

    def test_backups_next_to_config_files_are_not_tracked(self):
        root = INSTALL_SH.parent
        r = subprocess.run(
            [
                "git", "-C", str(root), "check-ignore", "-q", "--no-index",
                "configs/claude/settings.local.json.bak.20261110142011",
            ],
            check=False,
        )
        self.assertEqual(r.returncode, 0, "*.bak.<timestamp> must be gitignored")

    def test_hook_scripts_are_executable_in_git(self):
        # install.sh chmod +x every hook; a 100644 hook leaves a mode change in the checkout.
        root = INSTALL_SH.parent
        r = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-s", "--", "configs/agent/hooks"],
            capture_output=True, text=True, check=True,
        )
        modes = {line.split("\t")[1]: line.split()[0] for line in r.stdout.splitlines()}
        self.assertTrue(modes)
        self.assertEqual({path: mode for path, mode in modes.items() if mode != "100755"}, {})


if __name__ == "__main__":
    unittest.main()
