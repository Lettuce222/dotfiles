"""orchestrator の構成と、窓口・worker のスキルの決まりのテスト。

実行: python3 -m unittest configs/agent/tests/test_orchestrator.py

- worker は AskUserQuestion を使わず、やりとりを窓口に集約する。
- orchestrator コマンドは tmux を使わず、選んだ CLI を窓口のディレクトリで今のターミナルに開く。
  fish が無ければ飛ばす。
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "configs" / "agent" / "skills"
WORKER = SKILLS / "agents-worker" / "SKILL.md"
OLD_WORKER = SKILLS / "agents-thread" / "SKILL.md"
ORCH = SKILLS / "agents-orchestrator" / "SKILL.md"
FISH_FN = ROOT / "configs" / "fish" / "functions" / "orchestrator.fish"


@unittest.skipUnless(shutil.which("fish"), "fish が要る")
class LauncherTest(unittest.TestCase):
    def test_cw_dispatches_to_selected_cli_with_extra_directories(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            config = root / ".config"
            config.mkdir()
            assets = config / "dotfiles-agent"
            assets.mkdir()
            shutil.copy(ROOT / "configs/agent/select-cli.sh", assets)
            choice = assets / "cli.local"
            choice.write_text("codex\n")
            (config / "dotfiles-agent-cli").symlink_to(choice)
            for name in ("claude", "codex", "ghq"):
                command = root / name
                output = 'printf "%s\\n" "$0" "$@"' if name != "ghq" else 'echo "/repos/with spaces"'
                command.write_text(f"#!/bin/sh\n{output}\n")
                command.chmod(0o755)
            env = {**os.environ, "HOME": home, "PATH": f"{home}{os.pathsep}{os.environ['PATH']}"}
            env.pop("DOTFILES_AGENT", None)
            script = "source $argv[1]/agent.fish; source $argv[1]/cw.fish; cw spaces"
            command = ["fish", "--no-config", "-c", script, str(FISH_FN.parent)]
            for provider, override in (("codex", {}), ("claude", {"DOTFILES_AGENT": "claude"})):
                with self.subTest(provider=provider):
                    out = subprocess.run(
                        command, env={**env, **override}, capture_output=True, text=True, check=True
                    ).stdout.splitlines()
                    self.assertEqual(out, [str(root / provider), "--add-dir", "/repos/with spaces"])


class SkillRulesTest(unittest.TestCase):
    def test_worker_does_not_use_ask_user_question(self):
        for line in WORKER.read_text(encoding="utf-8").splitlines():
            if "AskUserQuestion" in line:
                self.assertIn("使わない", line, line)

    def test_old_skill_name_defers_to_agents_worker(self):
        # 名前を変える前に起動した worker の /agents-thread を、agents-worker に回す
        text = OLD_WORKER.read_text(encoding="utf-8")
        self.assertIn("name: agents-thread", text)
        self.assertIn("disable-model-invocation: true", text)
        self.assertIn("Skill ツールで `agents-worker` を読み込み", text)
        self.assertNotIn("/agents-thread", ORCH.read_text(encoding="utf-8"))

    def test_worker_reports_decisions_to_orchestrator(self):
        text = WORKER.read_text(encoding="utf-8")
        self.assertIn("要判断", text)
        self.assertIn("窓口で問いに答える", text)
        self.assertNotIn("一覧で", text)

    def test_orchestrator_relays_decisions(self):
        text = ORCH.read_text(encoding="utf-8")
        self.assertIn("### worker の要判断を聞く", text)
        self.assertIn("### worker がブロックしたとき", text)
        self.assertNotIn("代わりに答えない", text)
        self.assertNotIn("を開いて答える", text)
        self.assertNotIn("右下", text)
        self.assertNotIn("右上", text)

    def test_worker_checks_drafts_before_reporting(self):
        text = WORKER.read_text(encoding="utf-8")
        self.assertIn("external-post-guard.py --check <下書き>", text)
        self.assertIn("このチェックの手順は、報告に書かない", text)

    def test_orchestrator_fixes_format_without_asking(self):
        text = ORCH.read_text(encoding="utf-8")
        section = text.split("## 外に出す文面を送る", 1)[1].split("\n## ", 1)[0]
        self.assertIn("文面のチェック", section)
        self.assertIn("ユーザーに聞かず", section)
        self.assertIn("形式の直しのことは書かず", section)


    def test_worker_keeps_commits_signed(self):
        # 署名は外さない。止まったら報告する
        text = WORKER.read_text(encoding="utf-8")
        section = text.split("## コミット", 1)[1].split("\n## ", 1)[0]
        self.assertIn("-c commit.gpgsign=false", section)
        self.assertIn("「ブロック」で報告", section)
        self.assertIn("%G?", section)
        push = text.split("## push", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`origin/main` に rebase し", push)
        self.assertIn("git merge-base --is-ancestor origin/main HEAD", push)

    def test_agent_skills_do_not_assume_a_bash_sandbox(self):
        # Bash の sandbox は入れていない。sandbox を前提にした手順を書かない
        for path in (ORCH, WORKER):
            self.assertNotIn("sandbox", path.read_text(encoding="utf-8"), path)

    def test_worker_asks_orchestrator_to_approve_runs(self):
        text = WORKER.read_text(encoding="utf-8")
        section = text.split("## 実行の承認を求める", 1)[1].split("\n## ", 1)[0]
        self.assertIn("要判断", section)
        self.assertIn("1 文字も変えずに実行し直す", section)
        self.assertIn("コマンドの全文", section)
        self.assertNotIn("窓口が `claude agents --json` で気づいて", text)

    def test_orchestrator_approves_worker_runs_without_attach(self):
        text = ORCH.read_text(encoding="utf-8")
        section = text.split("### worker の実行を承認する", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        self.assertIn("AskUserQuestion", section)
        self.assertIn("--worker <worker 名>", section)
        self.assertIn("preview", section)
        self.assertNotIn("claude attach", text)
        self.assertNotIn("その worker を選んでダイアログに答えて", text)

    def test_orchestrator_shows_body_when_asking_approval(self):
        text = ORCH.read_text(encoding="utf-8")
        section = text.split("### 承認をもらって実行する", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        self.assertIn("preview", section)
        self.assertIn("本文そのもの", section)
        self.assertIn("承認の記録で確認ダイアログを省くときも", section)
        # preview は 2000 文字を超えると丸ごと伏せられる。全部出ない本文はページに分けて preview に載せる
        self.assertIn("ask-preview-guard.py --check", section)
        self.assertIn("ask-preview-guard.py --pages", section)
        self.assertIn("<下書き>.diff", section)
        self.assertNotIn("長い本文も切らずに載せる", text)

    def test_orchestrator_does_not_point_back_to_earlier_replies(self):
        # 上のチャットは動き続けていて遡りにくい。本文を前の返事に載せて参照させる決まりに戻さない
        text = ORCH.read_text(encoding="utf-8")
        for old in ("直前の返事に、本文の全文", "直前の返事に全文", "本文は上の返事に全文」を置く", "長くても全文を載せる"):
            self.assertNotIn(old, text)
        replies = text.split("## ユーザーへの返事", 1)[1].split("\n## ", 1)[0]
        self.assertIn("ダイアログだけで答えられる", replies)
        self.assertIn("参照させない", replies)

    def test_other_approvals_follow_the_same_body_rule(self):
        text = ORCH.read_text(encoding="utf-8")
        worker_run = text.split("### worker の実行を承認する", 1)[1].split("\n## ", 1)[0]
        outbound = text.split("## 外に出す文面を送る", 1)[1].split("\n## ", 1)[0]
        for section in (worker_run, outbound):
            self.assertIn("「承認をもらって実行する」の 1", section)
            self.assertIn("--pages", section)

    def test_worker_leaves_a_diff_when_fixing_a_draft(self):
        text = WORKER.read_text(encoding="utf-8")
        section = text.split("## 外に出す文面", 1)[1].split("\n## ", 1)[0]
        self.assertIn("<下書き>.before", section)
        self.assertIn("<下書き>.diff", section)


    def test_orchestrator_cleans_up_finished_workers_without_asking(self):
        # worker は 1 つのゴールで終わる。用が済んだ worker は聞かずに消し、続きは資料から始める
        text = ORCH.read_text(encoding="utf-8")
        section = text.split("## 片付け", 1)[1].split("\n## ", 1)[0]
        self.assertIn("ユーザーに聞かず、提案もせずに", section)
        self.assertIn("方針が変わって", section)
        self.assertIn("案件に移す", section)
        self.assertIn("`git worktree remove --force` は使わない", section)
        self.assertNotIn("AskUserQuestion", section)
        proposal = text.split("## 次の行動を提案する", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("送信、片付け）", proposal)
        resume = text.split("## 続きを頼む", 1)[1].split("\n## ", 1)[0]
        self.assertIn("新しい worker を起こして案件の資料から始める", resume)
        self.assertIn("`--resume` は、短い続きに限る", resume)
        self.assertNotIn("新しく起動せずに `--resume`", text)

    def test_worker_leaves_report_for_the_next_worker(self):
        text = WORKER.read_text(encoding="utf-8")
        section = text.split("## 報告と成果物を残す", 1)[1].split("\n## ", 1)[0]
        self.assertIn("~/hub/workers/<worker 名>/report.md", section)
        self.assertIn("続けるときの最初の一手", section)
        self.assertIn("worktree の中だけに置かない", section)

    def test_worker_runs_a_whole_goal_and_decides_reversible_choices(self):
        # worker はゴールを通しで進め、取り消せる判断は推奨で決めて「決めたこと」にまとめる
        text = WORKER.read_text(encoding="utf-8")
        self.assertIn("## ゴールまで通しで進める", text)
        section = text.split("## 迷ったら推奨で進む", 1)[1].split("\n## ", 1)[0]
        self.assertIn("「要判断」で止まるのは、次の 3 つのときだけ", section)
        self.assertIn("外に出す操作", section)
        self.assertIn("取り消せない操作", section)
        self.assertIn("依頼の前提が崩れたとき", section)
        self.assertIn("先に済ませる", section)
        report = text.split("## 報告と成果物を残す", 1)[1].split("\n## ", 1)[0]
        self.assertIn("決めたこと", report)
        self.assertNotIn("short session", text)

    def test_orchestrator_hands_goals_and_batches_reports(self):
        text = ORCH.read_text(encoding="utf-8")
        launch = text.split("## worker を起動する", 1)[1].split("\n## ", 1)[0]
        for key in ("ゴール:", "完了の条件:", "やってよい範囲:"):
            self.assertIn(key, launch)
        self.assertIn("小さな worker を細かく起こさない", launch)
        batch = text.split("## 報告をまとめて渡す", 1)[1].split("\n## ", 1)[0]
        self.assertIn("### すぐに伝えるもの", batch)
        self.assertIn("期日がその日", batch)
        self.assertIn("「どうなった？」", batch)
        self.assertIn("未報告", batch)
        self.assertNotIn("short session", text)
        self.assertNotIn("報告を受けて状況が変わったとき", text)

    def test_watch_marks_urgency(self):
        text = (SKILLS / "agents-watch" / "SKILL.md").read_text(encoding="utf-8")
        section = text.split("## 急ぎかどうか", 1)[1].split("\n## ", 1)[0]
        self.assertIn("期日がその日のものだけ", section)
        self.assertIn("自分宛てのメンションでも", section)
        self.assertIn("- 急ぎでない: ", text)


@unittest.skipUnless(shutil.which("fish"), "fish が要る")
class LaunchTest(unittest.TestCase):
    """orchestrator は tmux を使わず、選んだ CLI を窓口のディレクトリで今のターミナルに開く。"""

    def launch(self, provider):
        with tempfile.TemporaryDirectory() as home:
            assets = Path(home) / ".config/dotfiles-agent"
            assets.mkdir(parents=True)
            for filename in ("select-cli.sh", "codex-orchestrator.md"):
                shutil.copy(ROOT / "configs/agent" / filename, assets)
            # agent-env.fish は窓口のディレクトリに移ってから読む（direnv がそこの .envrc を読むため）。
            fish_conf = Path(home) / ".config/fish"
            fish_conf.mkdir(parents=True)
            (fish_conf / "agent-env.fish").write_text("set -gx ORCH_ENV_DIR (pwd)\n")
            bin_dir = Path(home) / "bin"
            bin_dir.mkdir()
            for cli in ("claude", "codex", "aider", "tmux"):
                executable = bin_dir / cli
                executable.write_text('#!/bin/sh\nprintf "%s\\n" "$ORCH_ENV_DIR" "$(pwd)" "$(basename "$0")" "$@"\n')
                executable.chmod(0o755)
            hub = Path(home) / "hub with spaces"
            env = {
                **os.environ,
                "HOME": home,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "DOTFILES_AGENT": provider,
                "AGENT_ORCHESTRATOR_HOME": str(hub),
            }
            script = "source $argv[1]/agent.fish; source $argv[1]/orchestrator.fish; orchestrator"
            result = subprocess.run(
                ["fish", "--no-config", "-c", script, str(FISH_FN.parent)],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(hub.is_dir())
            lines = result.stdout.splitlines()
            self.assertEqual([Path(line).resolve() for line in lines[:2]], [hub.resolve()] * 2)
            return lines[2:]

    def test_claude_opens_the_orchestrator_skill(self):
        self.assertEqual(
            self.launch("claude"), ["claude", "-n", "orchestrator", "--permission-mode", "auto", "/agents-orchestrator"]
        )

    def test_codex_gets_the_orchestrator_prompt(self):
        out = self.launch("codex")
        self.assertEqual(out[0], "codex")
        prompt = (ROOT / "configs/agent/codex-orchestrator.md").read_text(encoding="utf-8").rstrip("\n")
        self.assertEqual("\n".join(out[1:]), prompt)

    def test_custom_cli_launches_as_is(self):
        self.assertEqual(self.launch("aider"), ["aider"])


if __name__ == "__main__":
    unittest.main()
