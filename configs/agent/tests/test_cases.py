"""agents-orchestrator スキルの cases.py（案件の一覧）のテスト。

実行: python3 -m unittest configs/agent/tests/test_cases.py

gh は呼ばない（sweep には PR の状態を返す関数を渡す）。
"""

import datetime as dt
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "agents-orchestrator" / "scripts" / "cases.py"

spec = importlib.util.spec_from_file_location("cases", SCRIPT)
cases = importlib.util.module_from_spec(spec)
sys.modules["cases"] = cases  # dataclass が自分のモジュールを引くため
spec.loader.exec_module(cases)

PR1 = "https://github.com/o/r/pull/1"
PR2 = "https://github.com/o/r/pull/2"
PR3 = "https://github.com/o/r/pull/3"

SAMPLE = f"""# 架空の案件

## TODO
- [#3]({PR3}) を Ready にする

## Waiting
- [#1]({PR1}) の merge 待ち → 続きの PR の base を main に向ける
- [#1]({PR1})・[#2]({PR2}) のチェック待ち
- シートの申請中
  （11/05 に申請）

## Later
- [#1]({PR1}) が merge されたらチケットを閉じる

## 資料
- [report.md](file:///tmp/report.md)
"""

ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")


def plain(s: str) -> str:
    return ANSI.sub("", s)


def states(**by_url):
    return lambda urls: {u: {"state": by_url.get(u, "OPEN"), "reviewDecision": None, "isDraft": False} for u in urls}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "cases"
        self.dir.mkdir()
        env = mock.patch.dict(os.environ, {"AGENT_ORCHESTRATOR_HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name="x", text=SAMPLE):
        p = self.dir / f"{name}.md"
        p.write_text(text, encoding="utf-8")
        return p


class ParseTest(Base):
    def test_round_trip_keeps_text(self):
        p = self.write()
        self.assertEqual(cases.parse(p).dump(), SAMPLE)

    def test_items_and_continuation(self):
        c = cases.parse(self.write())
        self.assertEqual(c.title, "架空の案件")
        waits = [it.text for it in c.items(cases.WAITING)]
        self.assertEqual(len(waits), 3)
        self.assertEqual(waits[2], "シートの申請中 （11/05 に申請）")

    def test_split_next(self):
        self.assertEqual(cases.split_next("a → b"), ("a", "b"))
        self.assertEqual(cases.split_next("a"), ("a", None))


class SweepTest(Base):
    def test_removes_wait_when_all_prs_closed_and_moves_next(self):
        p = self.write()
        actions = cases.sweep(self.dir, states(**{PR1: "MERGED"}))
        removed = [a for a in actions if a["action"] == "removed"]
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["next"], "続きの PR の base を main に向ける")
        c = cases.parse(p)
        mine = [it.text for it in c.items(cases.MINE)]
        self.assertIn("続きの PR の base を main に向ける", mine)
        # #2 が開いているので、2 つの PR を待つ項目は残る
        waits = [it.text for it in c.items(cases.WAITING)]
        self.assertEqual(len(waits), 2)
        # Later は消さずに stale として知らせる
        stale = [a for a in actions if a["action"] == "stale"]
        self.assertEqual([a["section"] for a in stale], [cases.LATER])
        self.assertIn("## Later\n- [#1]", p.read_text())

    def test_open_waits_are_reported(self):
        self.write()
        actions = cases.sweep(self.dir, states())
        opened = [a for a in actions if a["action"] == "open"]
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[1]["prs"][1]["url"], PR2)

    def test_dry_run_does_not_write(self):
        p = self.write()
        cases.sweep(self.dir, states(**{PR1: "MERGED"}), dry_run=True)
        self.assertEqual(p.read_text(), SAMPLE)

    def test_pr_after_arrow_does_not_resolve_wait(self):
        p = self.write(text=f"# t\n\n## Waiting\n- 申請中 → [#1]({PR1}) にコメントする\n")
        actions = cases.sweep(self.dir, states(**{PR1: "MERGED"}))
        self.assertEqual(actions, [])
        self.assertIn("申請中", p.read_text())

    def test_archives_case_without_tasks(self):
        self.write(text=f"# t\n\n## Waiting\n- [#1]({PR1}) の merge 待ち\n\n## 資料\n- a\n")
        actions = cases.sweep(self.dir, states(**{PR1: "CLOSED"}))
        self.assertEqual(actions[-1], {"action": "archived", "case": "x"})
        self.assertFalse((self.dir / "x.md").exists())
        self.assertTrue((self.dir / "done" / "x.md").exists())

    def test_unknown_pr_is_kept(self):
        self.write(text=f"# t\n\n## Waiting\n- [#1]({PR1}) 待ち\n")
        actions = cases.sweep(self.dir, lambda urls: {})
        self.assertEqual(actions[0]["action"], "open")
        self.assertEqual(actions[0]["prs"][0]["state"], "UNKNOWN")


class ResolveTest(Base):
    def test_resolve_moves_next(self):
        p = self.write()
        out = cases.resolve(self.dir, "x.md", "merge 待ち")
        self.assertEqual(out["next"], "続きの PR の base を main に向ける")
        text = p.read_text()
        self.assertNotIn("merge 待ち", text)
        self.assertIn("## TODO\n- [#3]", text)
        self.assertIn("- 続きの PR の base を main に向ける\n\n## Waiting", text)

    def test_resolve_continuation_item(self):
        p = self.write()
        cases.resolve(self.dir, "x", "申請中")
        self.assertNotIn("11/05 に申請", p.read_text())

    def test_resolve_needs_exactly_one(self):
        self.write()
        with self.assertRaises(SystemExit):
            cases.resolve(self.dir, "x", "待ち")

    def test_resolve_creates_mine_section(self):
        p = self.write(text="# t\n\n## Waiting\n- 申請中 → 届いたら設定する\n- ほか\n")
        cases.resolve(self.dir, "x", "申請中")
        self.assertEqual(p.read_text(), "# t\n\n## TODO\n- 届いたら設定する\n\n## Waiting\n- ほか\n")


class RenderTest(Base):
    NOW = dt.datetime(2026, 11, 5, 16, 40)

    def test_links_are_osc8(self):
        self.write()
        out = "\n".join(cases.render(self.dir, 60, 100, self.NOW))
        self.assertIn(f"\x1b]8;;{PR3}\x1b\\", out)
        self.assertIn("\x1b]8;;file:///tmp/report.md\x1b\\", out)
        self.assertIn((self.dir / "x.md").as_uri(), out)

    def test_ticket_link_uses_pane_json(self):
        self.write(text="# t\n\n## Later\n- ABC-12 を閉じる\n")
        out = "\n".join(cases.render(self.dir, 60, 100, self.NOW))
        self.assertNotIn("\x1b]8;;https://jira.example/browse/ABC-12", out)
        (Path(self.tmp.name) / "pane.json").write_text('{"jira": "https://jira.example/browse/"}')
        out = "\n".join(cases.render(self.dir, 60, 100, self.NOW))
        self.assertIn("\x1b]8;;https://jira.example/browse/ABC-12\x1b\\", out)

    def test_lines_fit_width(self):
        self.write()
        for line in cases.render(self.dir, 24, 100, self.NOW):
            self.assertLessEqual(cases.text_width(plain(line)), 24, plain(line))

    def test_truncates_to_height(self):
        self.write()
        lines = cases.render(self.dir, 60, 6, self.NOW)
        self.assertEqual(len(lines), 6)
        self.assertTrue(plain(lines[-1]).startswith("… ほか"))

    def test_folds_refs_and_later_before_truncating(self):
        self.write()
        full = cases.render(self.dir, 80, 100, self.NOW)
        folded = plain("\n".join(cases.render(self.dir, 80, len(full) - 2, self.NOW)))
        self.assertNotIn("資料", folded)
        self.assertIn("・Later 1 件", folded)
        self.assertNotIn("… ほか", folded)

    def test_cases_with_my_turn_come_first(self):
        self.write("a", "# 待つだけ\n\n## Waiting\n- 待ち\n")
        self.write("b", "# 私の番\n\n## TODO\n- やる\n")
        os.utime(self.dir / "b.md", (0, 0))
        text = plain("\n".join(cases.render(self.dir, 60, 100, self.NOW)))
        self.assertLess(text.index("私の番"), text.index("待つだけ"))
        self.assertIn("TODO 1", text.splitlines()[0])

    def test_empty(self):
        text = plain("\n".join(cases.render(self.dir, 40, 10, self.NOW)))
        self.assertIn("案件はありません", text)


class HeadingStyleTest(Base):
    """区分名を変えても、見出しの色が名前に付いてくること。"""

    NOW = dt.datetime(2026, 11, 5, 16, 40)
    # 区分名を変える前（あなたの番 / 外の待ち / あとでやること）と同じ色。
    EXPECTED = {
        "TODO": ("▶ TODO", "\x1b[1;38;2;224;175;104m"),  # yellow
        "Waiting": ("◇ Waiting", "\x1b[1;38;2;125;207;255m"),  # cyan
        "Later": ("・Later", "\x1b[1;38;2;158;206;106m"),  # green
    }

    def test_every_task_section_has_its_own_style_and_label(self):
        self.assertEqual(set(cases.TASK_SECTIONS), set(self.EXPECTED))
        for name in cases.TASK_SECTIONS:
            self.assertIn(name, cases.STYLE, name)
            self.assertIn(name, cases.LABEL, name)
            self.assertNotEqual(cases.STYLE[name], cases.STYLE["other"], name)
        styles = [cases.STYLE[n] for n in cases.TASK_SECTIONS]
        self.assertEqual(len(set(styles)), len(styles))

    def test_headings_in_case_file_are_colored(self):
        self.write()
        out = "\n".join(cases.render(self.dir, 80, 100, self.NOW))
        for name, (label, style) in self.EXPECTED.items():
            self.assertIn(f"{style}{label}{cases.RESET}", out, name)

    def test_unknown_section_uses_other(self):
        self.write(text="# t\n\n## メモ\n- 何か\n")
        out = "\n".join(cases.render(self.dir, 80, 100, self.NOW))
        self.assertIn(f"{cases.STYLE['other']}メモ{cases.RESET}", out)


class BoardReloadTest(Base):
    def test_restarts_when_script_changes(self):
        sigs = iter([("old",), ("new",), ("new",)])
        execv = mock.Mock(side_effect=SystemExit)
        with (
            mock.patch.object(cases, "code_signature", lambda: next(sigs)),
            mock.patch.object(cases.os, "execv", execv),
            mock.patch.object(cases.time, "sleep"),
            mock.patch.object(cases.sys, "stdout", new=mock.Mock()),
            mock.patch.object(cases.signal, "signal"),
        ):
            with self.assertRaises(SystemExit):
                cases.board(self.dir, once=False, width=40, height=10)
        execv.assert_called_once()
        self.assertEqual(execv.call_args.args[1][1], str(SCRIPT))


if __name__ == "__main__":
    unittest.main()
