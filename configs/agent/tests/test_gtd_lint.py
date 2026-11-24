"""gtd-lint（hub v2 の項目の形と本文の正規形）のテスト。

実行: python3 -m unittest configs/agent/tests/test_gtd_lint.py

正規形の規則は gtd.py の lint、hook の配線は configs/agent/hooks/gtd-lint.py。
一時ディレクトリを GTD_HOME にし、hook はサブプロセスで JSON を渡して動かす。
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1]
SCRIPT = AGENT / "skills" / "agents-orchestrator" / "scripts" / "gtd.py"
HOOK = AGENT / "hooks" / "gtd-lint.py"

spec = importlib.util.spec_from_file_location("gtd_for_lint", SCRIPT)
gtd = importlib.util.module_from_spec(spec)
sys.modules["gtd_for_lint"] = gtd
spec.loader.exec_module(gtd)


def codes(body):
    return [f.code for f in gtd.body_findings(body)]


class BodyRulesTest(unittest.TestCase):
    def assertFixes(self, before, after, code):
        self.assertIn(code, codes(before))
        self.assertEqual(gtd.fix_body(before), after)
        self.assertEqual(codes(after), [])

    def test_canonical_body_has_no_findings(self):
        body = ("# 見出し\n\n段落の *強調* と **太字**、[リンク](https://example.com/a_b_c)。\n\n"
                "- 1 つ目\n  - 入れ子\n- [ ] チェック\n\n1. 番号\n2. 番号\n\n---\n\n"
                "```py\nx = a_b_c * 2\n~~~\n```\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
                "> 引用\n\n[https://example.com](https://example.com) と `<b>` と `https://x`")
        self.assertEqual(codes(body), [])
        self.assertEqual(gtd.fix_body(body), body)

    def test_bullets(self):
        self.assertFixes("* a\n+ b", "- a\n- b", "bullet")

    def test_nested_indent_two_spaces(self):
        self.assertFixes("- a\n    - b\n      続き\n        - c", "- a\n  - b\n    続き\n    - c", "indent")

    def test_ordered_paren(self):
        self.assertFixes("1) a\n2) b", "1. a\n2. b", "ordered")

    def test_setext_headings(self):
        self.assertFixes("題\n===\n\n小見出し\n---", "# 題\n\n## 小見出し", "setext")

    def test_rules(self):
        self.assertFixes("a\n\n***\n\nb\n\n_ _ _", "a\n\n---\n\nb\n\n---", "rule")

    def test_blank_lines_collapse_outside_code(self):
        self.assertFixes("a\n\n\n\nb\n\n```\n\n\n```", "a\n\nb\n\n```\n\n\n```", "blank")

    def test_tilde_fences(self):
        self.assertFixes("~~~sh\nls\n~~~", "```sh\nls\n```", "fence")

    def test_emphasis_underscores(self):
        self.assertFixes("_a_ と __b__ と snake_case_name", "*a* と **b** と snake_case_name", "inline")

    def test_autolinks_and_bare_urls(self):
        self.assertFixes("<https://a.example/x> と https://b.example/y。",
                         "[https://a.example/x](https://a.example/x) と [https://b.example/y](https://b.example/y)。", "inline")

    def test_code_is_left_alone(self):
        body = "`* x` と `_y_` と `https://z`\n\n```\n* a\n_b_\nhttps://c\n```"
        self.assertEqual(codes(body), [])

    def test_forbidden_constructs_are_not_fixable(self):
        for body, code in (("[a][b]\n\n[b]: https://x", "reflink"), ("本文[^1]", "footnote"),
                           ("<!-- 注 -->", "html"), ("<details>x</details>", "html")):
            found = gtd.body_findings(body)
            self.assertIn(code, [f.code for f in found], body)
            self.assertFalse(any(f.fixable for f in found if f.code == code))

    def test_final_newline_and_blank_after_frontmatter_are_not_asked(self):
        self.assertEqual(codes("\n- a\n"), [])
        self.assertEqual(codes("- a"), [])

    def test_indented_fences_and_code_are_left_alone(self):
        body = "- 手順\n\n    ```sh\n    curl https://x.com/a_b_c\n    * star\n    def __init__(self):\n    ```\n\n段落\n\n    https://indented.example/x_y_z"
        self.assertEqual(gtd.fix_body(body), body)
        self.assertEqual(codes(body), [])

    def test_tilde_fence_holding_backticks_gets_a_longer_fence(self):
        self.assertEqual(gtd.fix_body("~~~\n```\nx\n```\n~~~"), "````\n```\nx\n```\n````")

    def test_existing_links_and_definitions_stay(self):
        for line in ("[a](https://x.com 'title')", "[a](https://x.com (title))", "[1]: https://x.example/a",
                     '<a href="https://x.com">x</a>', "[w](https://en.wikipedia.org/wiki/Foo_(bar))"):
            self.assertEqual(gtd.fix_body(line), line, line)
        self.assertEqual(gtd.fix_body("see https://en.wikipedia.org/wiki/Foo_(bar)."),
                         "see [https://en.wikipedia.org/wiki/Foo_(bar)](https://en.wikipedia.org/wiki/Foo_(bar)).")

    def test_rule_after_a_paragraph_stays_a_rule(self):
        self.assertEqual(gtd.fix_body("__s__\n***"), "**s**\n\n---")

    def test_setext_takes_the_whole_paragraph(self):
        self.assertEqual(gtd.fix_body("line1\nline2\n---"), "## line1 line2")

    def test_fix_is_idempotent_on_random_bodies(self):
        import random
        parts = ["text", "_em_", "__st__", "https://a.example/x_y", "<https://b.example>", "* item", "+ item",
                 "    * nested", "1) one", "***", "---", "===", "", "", "~~~", "```", "`code_x`", "[l](http://u)",
                 "> quote", "# head", "  - two", "- [ ] task", "| a | b |"]
        rnd = random.Random(7)
        for _ in range(3000):
            body = "\n".join(rnd.choice(parts) for _ in range(rnd.randint(1, 8)))
            once = gtd.fix_body(body)
            self.assertEqual(gtd.fix_body(once), once, repr(body))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "gtd"
        self.items = self.root / "items"
        self.env = mock.patch.dict(os.environ, {"GTD_HOME": str(self.root), "GTD_TODAY": "2026-11-24"})
        self.env.start()
        gtd.init(self.root)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.items / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        return path

    def findings(self, path):
        return [(f.code, f.message) for f in gtd.lint(self.root, [path]).get(str(path), [])]


class FrontmatterRulesTest(Base):
    def test_required_keys_and_values(self):
        path = self.write("x1", "---\nid: x2\nlist: later\nactor: bot\ndue: 11/20\n---\n")
        found = self.findings(path)
        self.assertIn(("required", "frontmatter に title が無い"), found)
        self.assertIn("id", [c for c, _ in found])
        self.assertIn("list", [c for c, _ in found])
        self.assertIn("actor", [c for c, _ in found])
        self.assertIn("date", [c for c, _ in found])

    def test_missing_frontmatter(self):
        self.assertEqual([c for c, _ in self.findings(self.write("x1", "本文だけ"))], ["frontmatter"])

    def test_done_needs_its_date(self):
        found = self.findings(self.write("x1", "---\nid: x1\ntitle: t\nlist: done\n---\n"))
        self.assertEqual([c for c, _ in found], ["required"])

    def test_broken_references(self):
        self.write("p1", "---\nid: p1\ntitle: p\nlist: project\nsteps:\n  - s1\n  - gone\n  - s1\n  - s2\n---\n")
        self.write("s1", "---\nid: s1\ntitle: s\nlist: next\nproject: p1\n---\n")
        self.write("s2", "---\nid: s2\ntitle: s\nlist: planned\nproject: other\n---\n")
        self.write("n1", "---\nid: n1\ntitle: n\nlist: next\nproject: s1\nsteps:\n  - s1\n---\n")
        result = gtd.lint(self.root)
        p1 = [m for f in result[str(self.items / "p1.md")] for m in [f.message]]
        self.assertIn("steps の gone が無い", p1)
        self.assertIn("steps に s1 が 2 回ある", p1)
        self.assertIn("steps の s2 の project が p1 でない", p1)
        n1 = [f.message for f in result[str(self.items / "n1.md")]]
        self.assertIn("project の s1 はプロジェクト（list: project）でない", n1)
        self.assertIn("steps を持てるのはプロジェクト（list: project）だけ", n1)
        self.assertIn("project の other が無い", [f.message for f in result[str(self.items / "s2.md")]])
        self.assertNotIn(str(self.items / "s1.md"), result)

    def test_line_numbers_count_the_frontmatter(self):
        path = self.write("x1", "---\nid: x1\ntitle: t\nlist: next\n---\n* a")
        self.assertEqual([f.line for f in gtd.lint(self.root, [path])[str(path)]], [6])


class HookTest(Base):
    def hook(self, event, path, cwd="/Users/me/hub/workers/research-x"):
        payload = {"hook_event_name": event, "tool_name": "Edit", "tool_input": {"file_path": str(path)}, "cwd": cwd}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=os.environ.copy())

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout

    def test_pre_folds_human_changes_and_post_commits_as_the_worker(self):
        human = self.write("h1", "---\nid: h1\ntitle: 人が直した\nlist: next\n---\n")
        target = self.items / "a1.md"
        res = self.hook("PreToolUse", target)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.git("log", "-1", "--format=%an|%s").startswith("user|記録係: エージェントが書く前"))
        self.assertIn("items/h1.md", self.git("show", "--name-only", "--format=", "HEAD"))
        target.write_text("---\nid: a1\ntitle: エージェントが書いた\nlist: next\n---\n- ok", encoding="utf-8")
        res = self.hook("PostToolUse", target)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%an|%s").strip(), "agent:research-x|edit a1: agent:research-x が直接書いた")
        self.assertEqual(self.git("status", "--porcelain"), "")
        log = [json.loads(l) for l in (self.root / ".log" / "changes.jsonl").read_text().splitlines()]
        self.assertEqual(log[-1]["by"], "agent:research-x")
        self.assertTrue(human.exists())

    def test_post_returns_findings_with_exit_2(self):
        target = self.write("a1", "---\nid: a1\nlist: next\n---\n* a")
        res = self.hook("PostToolUse", target)
        self.assertEqual(res.returncode, 2)
        self.assertIn("frontmatter に title が無い", res.stderr)
        self.assertIn("リストの印は - にする（gtd.py lint --fix で直る）", res.stderr)
        self.assertIn("lint --fix", res.stderr)

    def test_other_files_are_ignored(self):
        for path in (self.base / "notes.md", self.items / "a1" / "report.md", self.items / "a1.txt"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("* not checked", encoding="utf-8")
            res = self.hook("PostToolUse", path)
            self.assertEqual((res.returncode, res.stderr), (0, ""), path)
        self.assertEqual(self.git("log", "--format=%s").count("\n"), 1)  # init のコミットだけ

    def test_worker_name_from_a_worktree(self):
        target = self.write("a1", "---\nid: a1\ntitle: t\nlist: next\n---\n")
        self.hook("PostToolUse", target, cwd="/r/.claude/worktrees/impl-y/sub")
        self.assertTrue(self.git("log", "-1", "--format=%an").startswith("agent:impl-y"))


if __name__ == "__main__":
    unittest.main()
