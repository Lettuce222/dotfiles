"""agents-orchestrator スキルの cases.py（案件の一覧）のテスト。

実行: python3 -m unittest configs/agent/tests/test_cases.py

gh は呼ばない（sweep には PR の状態を返す関数を渡す）。
"""

import importlib.util
import os
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


class ScheduleSweepTest(Base):
    TEXT = (
        "# t\n\n## TODO\n- やる\n\n## 予定\n"
        "- [11/09] 定例に出る → 次の回の資料を作る\n- [11/10] 今日のレビュー会に出る\n- 日付の無い予定\n"
    )

    def test_removes_past_events_and_moves_next(self):
        p = self.write(text=self.TEXT)
        actions = cases.sweep(self.dir, states(), today=TODAY)
        self.assertEqual(
            actions,
            [
                {
                    "action": "removed",
                    "case": "x",
                    "section": "予定",
                    "item": "[11/09] 定例に出る → 次の回の資料を作る",
                    "next": "次の回の資料を作る",
                }
            ],
        )
        # 今日の予定と日付の無い予定は残す
        self.assertEqual(
            p.read_text(),
            "# t\n\n## TODO\n- やる\n- 次の回の資料を作る\n\n## 予定\n- [11/10] 今日のレビュー会に出る\n- 日付の無い予定\n",
        )

    def test_dry_run_does_not_write(self):
        p = self.write(text=self.TEXT)
        actions = cases.sweep(self.dir, states(), dry_run=True, today=TODAY)
        self.assertEqual(actions[0]["section"], "予定")
        self.assertEqual(p.read_text(), self.TEXT)

    def test_case_with_only_upcoming_events_is_kept(self):
        self.write(text="# t\n\n## 予定\n- [11/12] 定例に出る\n")
        self.assertEqual(cases.sweep(self.dir, states(), today=TODAY), [])
        self.assertTrue((self.dir / "x.md").exists())

    def test_archives_case_when_last_event_passes(self):
        self.write(text="# t\n\n## 予定\n- [11/09] 定例に出る\n")
        actions = cases.sweep(self.dir, states(), today=TODAY)
        self.assertEqual(actions[-1], {"action": "archived", "case": "x"})
        self.assertTrue((self.dir / "done" / "x.md").exists())

    def test_resolve_event_moves_next(self):
        p = self.write(text=self.TEXT)
        out = cases.resolve(self.dir, "x", "定例", section="予定")
        self.assertEqual(out["next"], "次の回の資料を作る")
        self.assertIn("- 次の回の資料を作る\n", p.read_text())

    def test_cli_accepts_schedule_section(self):
        self.write(text=self.TEXT)
        with mock.patch.dict(os.environ, {"AGENT_CASES_DIR": str(self.dir)}), mock.patch("sys.stdout"):
            self.assertEqual(cases.main(["resolve", "x", "日付の無い", "--section", "予定"]), 0)
        self.assertNotIn("日付の無い", (self.dir / "x.md").read_text())


class JsonTest(Base):
    def test_cases_with_marks_waiting_and_linked_workers(self):
        import datetime as dt

        self.write("a", "# 案件 A\n略称: A\n\n## TODO\n- 読む\n- [11/20] ! 出す\n- [11/18] 遅れた\n\n"
                        "## Waiting\n- 返事待ち → 続ける\n\n## 資料\n- [r](file:///Users/me/hub/workers/impl-a/report.md)\n"
                        "- [w](file:///Users/me/repo/.claude/worktrees/impl-b)\n")
        self.write("b", "# 案件 B\n\n## Waiting\n- 待つ\n")
        self.write("c", "# 案件 C\n\n## TODO\n- ! 急ぐ\n")
        out = cases.cases_json(self.dir, dt.date(2026, 11, 19))
        self.assertEqual(out["today"], "2026-11-19")
        self.assertEqual([c["slug"] for c in out["cases"]], ["a", "c", "b"])
        a = out["cases"][0]
        self.assertEqual(a["short"], "A")
        self.assertEqual([t["text"] for t in a["todo"]], ["遅れた", "出す", "読む"])
        self.assertEqual(a["todo"][0], {"text": "遅れた", "due": "2026-11-18", "bang": False, "overdue": True, "today": False})
        self.assertTrue(a["todo"][1]["bang"])
        self.assertEqual(a["waiting"], [{"text": "返事待ち", "next": "続ける"}])
        self.assertEqual(a["workers"], ["impl-a", "impl-b"])

    def test_main_prints_json(self):
        import io
        import json
        from contextlib import redirect_stdout

        self.write()
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"AGENT_CASES_DIR": str(self.dir)}), redirect_stdout(buf):
            self.assertEqual(cases.main(["json"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["cases"][0]["slug"], "x")


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


class LogTest(Base):
    def test_adds_one_line_to_refs(self):
        p = self.write()
        out = cases.log(self.dir, "x.md", "11/19 パネルで答えた:\n設定の置き場所 [report.md](file:///tmp/r.md)")
        self.assertEqual(out["section"], "資料")
        refs = [it.text for it in cases.parse(p).items("資料")]
        self.assertEqual(refs[-1], "11/19 パネルで答えた: 設定の置き場所 [report.md](file:///tmp/r.md)")
        self.assertEqual(len(refs), 2)

    def test_creates_the_refs_section(self):
        p = self.write(text="# 案件\n\n## TODO\n- 読む\n")
        cases.log(self.dir, "x", "残す")
        self.assertEqual([it.text for it in cases.parse(p).items("資料")], ["残す"])
        self.assertEqual([it.text for it in cases.parse(p).items("TODO")], ["読む"])

    def test_refuses_paths_and_missing_cases(self):
        self.write()
        for slug in ("../x", "a/b", ".x", "nothing"):
            with self.assertRaises(SystemExit, msg=slug):
                cases.log(self.dir, slug, "残す")


TODAY = cases.dt.date(2026, 11, 10)  # 火曜


class TodoMarksTest(unittest.TestCase):
    def marks(self, text, today=TODAY):
        return cases.todo_marks(text, today)

    def test_due_and_bang(self):
        d = cases.dt.date
        self.assertEqual(self.marks("[11/11] ! 読む"), (d(2026, 11, 11), True, "読む"))
        self.assertEqual(self.marks("! [11/11] 読む"), (d(2026, 11, 11), True, "読む"))
        self.assertEqual(self.marks("[11/11（水）] 読む"), (d(2026, 11, 11), False, "読む"))
        self.assertEqual(self.marks("[1/5] 読む"), (d(2027, 1, 5), False, "読む"))
        self.assertEqual(self.marks("[10/30] 送る"), (d(2026, 10, 30), False, "送る"))

    def test_text_without_marks_is_kept(self):
        for text in (
            "[#3](https://github.com/o/r/pull/3) を Ready にする",
            "11/11（水）の定例の資料を読む",
            "![図](x.png) を貼る",
            "[2/30] ありえない日付",
            "!重要",
        ):
            self.assertEqual(self.marks(text), (None, False, text), text)


if __name__ == "__main__":
    unittest.main()
