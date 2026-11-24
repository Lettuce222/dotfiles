"""agents-orchestrator スキルの gtd.py（hub v2 の項目）のテスト。

実行: python3 -m unittest configs/agent/tests/test_gtd.py

一時ディレクトリを GTD_HOME と AGENT_CASES_DIR にする。git は一時ディレクトリの中でだけ使う。
gh は呼ばない（sweep には PR の状態を返す関数を渡す）。
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "agents-orchestrator" / "scripts" / "gtd.py"

spec = importlib.util.spec_from_file_location("gtd", SCRIPT)
gtd = importlib.util.module_from_spec(spec)
sys.modules["gtd"] = gtd  # dataclass が自分のモジュールを引くため
spec.loader.exec_module(gtd)

PR1 = "https://github.com/o/r/pull/1"
PR2 = "https://github.com/o/r/pull/2"

CASE = """# 架空の作り直し
略称: 作り直し

## TODO
- [11/25] 新しい API のテストを足す
- ! 呼び出し元を洗い出す

## Waiting
- PR のレビュー待ち → 指摘があれば直す

## Later
- 旧モジュールを消す

## 予定
- [11/26] 定例で話す → 宿題を足す

## 資料
- [メモ](https://example.com/memo)
"""


def states(**by_url):
    return lambda urls: {u: {"state": by_url.get(u, "OPEN"), "reviewDecision": None, "isDraft": False} for u in urls}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "gtd"
        self.cases = base / "cases"
        self.cases.mkdir()
        env = {"GTD_HOME": str(self.root), "AGENT_CASES_DIR": str(self.cases), "AGENT_ORCHESTRATOR_HOME": str(base),
               "GTD_TODAY": "2026-11-24", "GTD_BY": "agent:test"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        gtd.init(self.root)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def read(self, item_id):
        return (self.root / "items" / f"{item_id}.md").read_text(encoding="utf-8")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout

    def log(self):
        return self.git("log", "--format=%an|%s")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=os.environ.copy())


class FrontmatterTest(Base):
    def test_round_trip_keeps_order_and_unknown_keys(self):
        text = "---\nlist: next\ntitle: 題\nid: x1\nzeta: 1\nlinks:\n  - https://a\n  - https://b\n---\n本文"
        lines, body = gtd.split_doc(text)
        fm = gtd.parse_frontmatter(lines)
        self.assertEqual(fm["links"], ["https://a", "https://b"])
        dumped = gtd.dump_frontmatter(fm)
        self.assertEqual(dumped, "---\nid: x1\ntitle: 題\nlist: next\nlinks:\n  - https://a\n  - https://b\nzeta: 1\n---\n")
        self.assertEqual(body, "本文")

    def test_comments_inline_lists_and_quotes(self):
        fm = gtd.parse_frontmatter([
            "id: p1   # 変えない",
            "steps:",
            "  - a1          # done",
            "watch: [https://x/1, https://x/2]",
            'title: "a: b # c"',
            "then: 'it''s'",
        ])
        self.assertEqual(fm["id"], "p1")
        self.assertEqual(fm["steps"], ["a1"])
        self.assertEqual(fm["watch"], ["https://x/1", "https://x/2"])
        self.assertEqual(fm["title"], "a: b # c")
        self.assertEqual(fm["then"], "it's")

    def test_quotes_values_that_need_it(self):
        out = gtd.dump_frontmatter({"id": "a", "title": "#262 のレビュー", "then": "a: b", "who": "- x"})
        self.assertIn('title: "#262 のレビュー"', out)
        self.assertIn('then: "a: b"', out)
        self.assertIn('who: "- x"', out)
        fm = gtd.parse_frontmatter(out.strip().split("\n")[1:-1])
        self.assertEqual(fm["title"], "#262 のレビュー")

    def test_bad_lines_are_invalid(self):
        with self.assertRaises(gtd.Invalid):
            gtd.parse_frontmatter(["just text"])
        with self.assertRaises(gtd.Invalid):
            gtd.parse_frontmatter(["id: a", "id: b"])
        with self.assertRaises(gtd.Invalid):
            gtd.split_doc("---\nid: a\n")


class AddMoveDoneTest(Base):
    def test_add_writes_canonical_file_without_blank_or_final_newline(self):
        item = gtd.add(self.gtd_root(), "  頭にあること   を 1 行で ", "user")
        self.assertRegex(item.id, r"^20261124-[0-9a-f]{4}$")
        self.assertEqual(self.read(item.id), f"---\nid: {item.id}\ntitle: 頭にあること を 1 行で\nlist: inbox\nsince: 2026-11-24\n---\n")
        self.assertEqual(gtd.lint(self.root), {})

    def gtd_root(self):
        return self.root

    def test_add_normalizes_body(self):
        item = gtd.add(self.root, "題", "agent", body="* a\n* see https://x.y/z")
        self.assertTrue(self.read(item.id).endswith("---\n- a\n- see [https://x.y/z](https://x.y/z)"))

    def test_move_and_done_and_hash_conflict(self):
        item = gtd.add(self.root, "題", "user")
        res = gtd.move(self.root, item.id, "next", "user", expect_hash=item.hash)
        self.assertIn("list: next", self.read(item.id))
        with self.assertRaises(gtd.Conflict):
            gtd.move(self.root, item.id, "someday", "user", expect_hash=item.hash)
        gtd.done(self.root, item.id, "user", expect_hash=res["hash"])
        text = self.read(item.id)
        self.assertIn("list: done", text)
        self.assertIn("done: 2026-11-24", text)
        gtd.move(self.root, item.id, "next", "user")
        self.assertNotIn("done: ", self.read(item.id))

    def test_unknown_list_and_missing_item(self):
        item = gtd.add(self.root, "題", "user")
        with self.assertRaises(gtd.Invalid):
            gtd.move(self.root, item.id, "calendar", "user")
        with self.assertRaises(gtd.GtdError):
            gtd.move(self.root, "20990101-ffff", "next", "user")
        with self.assertRaises(gtd.Invalid):
            gtd.load("../etc/passwd", self.root)

    def test_changes_are_logged_with_the_writer(self):
        item = gtd.add(self.root, "題", "user")
        gtd.move(self.root, item.id, "next", "agent:w1")
        lines = [json.loads(l) for l in (self.root / ".log" / "changes.jsonl").read_text().splitlines()]
        self.assertEqual([(l["action"], l["by"]) for l in lines], [("add", "user"), ("move:next", "agent:w1")])

    def test_json_lists_items_counts_and_deliverables(self):
        a = gtd.add(self.root, "自分の番", "user", list_="next", actor="me", worker="w1")
        b = gtd.add(self.root, "待ち", "user", list_="waiting", who="相手", follow_up="2026-11-23")
        gtd.add(self.root, "まだ", "user", list_="next", due="2026-12-01")
        (self.root / "items" / a.id).mkdir()
        (self.root / "items" / a.id / "draft.md").write_text("x")
        (self.root / "items" / a.id / "report.md").write_text("x")
        state = gtd.state_json(self.root)
        by_id = {i["id"]: i for i in state["items"]}
        self.assertEqual(by_id[a.id]["mine"], "handback")
        self.assertEqual(by_id[a.id]["deliverables"], ["report.md", "draft.md"])
        self.assertEqual(by_id[b.id]["mine"], "follow_up")
        self.assertEqual(state["counts"]["mine"], 2)
        self.assertEqual(state["counts"]["next"], 2)
        self.assertEqual(state["counts"]["waiting"], 1)

    def test_broken_file_is_reported_not_fatal(self):
        (self.root / "items" / "bad.md").write_text("no frontmatter")
        gtd.add(self.root, "題", "user")
        state = gtd.state_json(self.root)
        self.assertEqual(len(state["items"]), 1)
        self.assertEqual(len(state["broken"]), 1)


class SetTest(Base):
    def test_set_lists_and_unset(self):
        item = gtd.add(self.root, "題", "user", list_="waiting", who="a")
        gtd.set_fields(self.root, item.id, ["watch+=" + PR1, "watch+=" + PR2, "watch-=" + PR1, "then=直す"], "user", unset=["who"])
        fm = gtd.load(item.id, self.root).fm
        self.assertEqual(fm["watch"], [PR2])
        self.assertEqual(fm["then"], "直す")
        self.assertNotIn("who", fm)

    def test_set_validates(self):
        item = gtd.add(self.root, "題", "user")
        for bad in (["list=calendar"], ["actor=bot"], ["due=11/20"], ["id=x"], ["title+=x"]):
            with self.assertRaises(gtd.Invalid, msg=bad):
                gtd.set_fields(self.root, item.id, bad, "user")
        with self.assertRaises(gtd.Invalid):
            gtd.set_fields(self.root, item.id, [], "user", unset=["title"])

    def test_stale_hash_merges_by_key_when_expectations_hold(self):
        item = gtd.add(self.root, "題", "user", list_="next")
        old = item.hash
        gtd.set_fields(self.root, item.id, ["due=2026-12-01"], "agent")  # ほかの人が別のキーを直した
        with self.assertRaises(gtd.Conflict):
            gtd.set_fields(self.root, item.id, ["list=someday"], "user", expect_hash=old)
        gtd.set_fields(self.root, item.id, ["list=someday"], "user", expect_hash=old, expect=["list=next"])
        fm = gtd.load(item.id, self.root).fm
        self.assertEqual((fm["list"], fm["due"]), ("someday", "2026-12-01"))

    def test_stale_hash_conflicts_when_the_same_key_changed(self):
        item = gtd.add(self.root, "題", "user", list_="next")
        old = item.hash
        gtd.set_fields(self.root, item.id, ["list=waiting"], "agent")
        with self.assertRaises(gtd.Conflict):
            gtd.set_fields(self.root, item.id, ["list=someday"], "user", expect_hash=old, expect=["list=next"])


class NoteAssignTest(Base):
    def test_note_appends_to_section_or_creates_it(self):
        item = gtd.add(self.root, "題", "agent", body="前置き\n\n## メモ\n\n- 1 つ目\n\n## ほか\n\n- x")
        gtd.note(self.root, item.id, "メモ", "2 つ目", "agent")
        gtd.note(self.root, item.id, "メモへの返事", "応えた", "agent")
        body = gtd.load(item.id, self.root).body
        self.assertEqual(body, "前置き\n\n## メモ\n\n- 1 つ目\n- 2 つ目\n\n## ほか\n\n- x\n\n## メモへの返事\n\n- 応えた")
        self.assertEqual(gtd.lint(self.root), {})

    def test_assign_and_handback(self):
        item = gtd.add(self.root, "題", "user")
        gtd.assign(self.root, item.id, "research-x", "agent")
        fm = gtd.load(item.id, self.root).fm
        self.assertEqual((fm["actor"], fm["worker"], fm["list"]), ("agent", "research-x", "next"))
        gtd.handback(self.root, item.id, "下書きを読んで直す", "agent:research-x")
        loaded = gtd.load(item.id, self.root)
        self.assertEqual(loaded.fm["actor"], "me")
        self.assertIn("## あなたの番\n\n- 11/24: 下書きを読んで直す", loaded.body)
        self.assertEqual(gtd.mine_reason(loaded, gtd.today()), "handback")
        with self.assertRaises(gtd.Invalid):
            gtd.assign(self.root, item.id, "bad name", "agent")


class TalkTest(Base):
    """The talk with the orchestrator on an item: its answers, the user's replies, and what is unread."""

    def test_reply_writes_a_dated_block_and_marks_it_unread_until_read(self):
        item = gtd.add(self.root, "題", "user", body="前置き\n\n## メモ\n\n- x")
        with mock.patch.dict(os.environ, {"GTD_NOW": "2026-11-24T16:52"}):
            gtd.reply(self.root, item.id, "1 つ目の答え", "agent:orchestrator")
        with mock.patch.dict(os.environ, {"GTD_NOW": "2026-11-24T17:05"}):
            gtd.reply(self.root, item.id, "2 つ目は\n\n- 箇条\n- **太字**\n\n```sh\n# コードの中の見出しは見出しでない\n```", "agent:orchestrator")
        loaded = gtd.load(item.id, self.root)
        self.assertEqual(loaded.body, "前置き\n\n## メモ\n\n- x\n\n## 窓口の返事\n\n### 11/24 16:52\n\n1 つ目の答え\n\n### 11/24 17:05\n\n2 つ目は\n\n- 箇条\n- **太字**\n\n```sh\n# コードの中の見出しは見出しでない\n```")
        self.assertEqual(loaded.fm["answered"], "2026-11-24T17:05")
        self.assertTrue(gtd.unread(loaded))
        with mock.patch.dict(os.environ, {"GTD_NOW": "2026-11-24T17:10"}):
            self.assertEqual(gtd.read_reply(self.root, item.id, "user")["changed"], True)
            self.assertEqual(gtd.read_reply(self.root, item.id, "user")["changed"], False, "nothing unread: nothing written")
        self.assertFalse(gtd.unread(gtd.load(item.id, self.root)))
        self.assertEqual(gtd.lint(self.root), {})

    def test_reply_goes_into_its_section_before_the_next_one(self):
        item = gtd.add(self.root, "題", "user", body="## 窓口の返事\n\n### 11/24 09:00\n\nはじめ\n\n## メモ\n\n- x")
        with mock.patch.dict(os.environ, {"GTD_NOW": "2026-11-24T10:00"}):
            gtd.reply(self.root, item.id, "つぎ", "agent")
        self.assertEqual(gtd.load(item.id, self.root).body, "## 窓口の返事\n\n### 11/24 09:00\n\nはじめ\n\n### 11/24 10:00\n\nつぎ\n\n## メモ\n\n- x")

    def test_a_reply_cannot_break_the_sections(self):
        item = gtd.add(self.root, "題", "user")
        for bad in ("## 見出し", "### 見出し", "   \n"):
            with self.assertRaises(gtd.Invalid):
                gtd.reply(self.root, item.id, bad, "agent")

    def test_say_writes_the_users_line_and_waits_for_an_answer(self):
        item = gtd.add(self.root, "題", "user")
        with mock.patch.dict(os.environ, {"GTD_NOW": "2026-11-24T16:40"}):
            gtd.say(self.root, item.id, "A 案で。\n来週まで", "user")
        loaded = gtd.load(item.id, self.root)
        self.assertIn("## あなたの番への返事\n\n- 11/24 16:40: A 案で。 来週まで", loaded.body)
        self.assertEqual(loaded.fm["asked"], "2026-11-24T16:40")
        with mock.patch.dict(os.environ, {"GTD_NOW": "2026-11-24T16:50"}):
            gtd.reply(self.root, item.id, "了解", "agent")
        loaded = gtd.load(item.id, self.root)
        self.assertGreater(loaded.fm["answered"], loaded.fm["asked"])

    def test_the_cli_reads_the_body_from_a_file_or_stdin(self):
        item = gtd.add(self.root, "題", "user")
        body = Path(self.tmp.name) / "answer.md"
        body.write_text("ファイルの答え\n\n- 1\n", encoding="utf-8")
        env = {**os.environ, "GTD_NOW": "2026-11-24T18:00"}
        res = subprocess.run([sys.executable, str(SCRIPT), "reply", item.id, "--body-file", str(body)], capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        res = subprocess.run([sys.executable, str(SCRIPT), "reply", item.id, "--body-file", "-"], input="標準入力の答え\n", capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        res = subprocess.run([sys.executable, str(SCRIPT), "say", item.id, "了解", "--by", "user"], capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        res = subprocess.run([sys.executable, str(SCRIPT), "read", item.id, "--by", "user"], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(res.stdout)["changed"], True)
        text = self.read(item.id)
        self.assertIn("### 11/24 18:00\n\nファイルの答え\n\n- 1\n\n### 11/24 18:00\n\n標準入力の答え", text)
        self.assertIn("answered: 2026-11-24T18:00\nread: 2026-11-24T18:00", text)
        state = json.loads(self.run_cli("json").stdout)
        shown = next(i for i in state["items"] if i["id"] == item.id)
        self.assertEqual((shown["asked"], shown["answered"], shown["read"]), ("2026-11-24T18:00", "2026-11-24T18:00", "2026-11-24T18:00"))

    def test_lint_checks_the_times(self):
        path = self.root / "items" / "x1.md"
        path.write_text("---\nid: x1\ntitle: 題\nlist: next\nanswered: 11/24\n---\n", encoding="utf-8")
        found = gtd.lint(self.root)
        self.assertIn("answered が時刻", " ".join(f.message for fs in found.values() for f in fs))


class ProjectStepsTest(Base):
    def make_project(self):
        proj = gtd.add(self.root, "プロジェクト", "agent", list_="project", item_id="proj", outcome="できている")
        s1 = gtd.step_add(self.root, "proj", "agent", title="1 つ目")["id"]
        s2 = gtd.step_add(self.root, "proj", "agent", title="2 つ目")["id"]
        s3 = gtd.step_add(self.root, "proj", "agent", title="3 つ目")["id"]
        return proj, s1, s2, s3

    def lists(self, *ids):
        return [gtd.load(i, self.root).fm["list"] for i in ids]

    def test_first_step_becomes_next_and_done_promotes_the_following(self):
        _, s1, s2, s3 = self.make_project()
        self.assertEqual(gtd.load("proj", self.root).fm["steps"], [s1, s2, s3])
        self.assertEqual(self.lists(s1, s2, s3), ["next", "planned", "planned"])
        res = gtd.done(self.root, s1, "user")
        self.assertEqual(res["promoted"], [s2])
        self.assertEqual(self.lists(s1, s2, s3), ["done", "next", "planned"])
        self.assertEqual(gtd.lint(self.root), {})

    def test_no_promotion_while_another_step_is_next(self):
        _, s1, s2, s3 = self.make_project()
        gtd.move(self.root, s2, "next", "user")
        res = gtd.done(self.root, s1, "user")
        self.assertEqual(res["promoted"], [])
        self.assertEqual(self.lists(s2, s3), ["next", "planned"])

    def test_reorder_and_remove(self):
        _, s1, s2, s3 = self.make_project()
        gtd.step_move(self.root, "proj", s3, 1, "user")
        self.assertEqual(gtd.load("proj", self.root).fm["steps"], [s3, s1, s2])
        gtd.step_remove(self.root, "proj", s1, "user")
        self.assertEqual(gtd.load("proj", self.root).fm["steps"], [s3, s2])

    def test_existing_item_as_step_at_position(self):
        _, s1, s2, _ = self.make_project()
        other = gtd.add(self.root, "外の行動", "user")
        gtd.step_add(self.root, "proj", "user", step_id=other.id, at=2)
        self.assertEqual(gtd.load("proj", self.root).fm["steps"][:3], [s1, other.id, s2])
        fm = gtd.load(other.id, self.root).fm
        self.assertEqual((fm["project"], fm["list"]), ("proj", "planned"))

    def test_add_with_project_attaches_step(self):
        self.make_project()
        item = gtd.add(self.root, "あとから", "user", list_="planned", project="proj")
        self.assertEqual(gtd.load("proj", self.root).fm["steps"][-1], item.id)
        ref = gtd.add(self.root, "資料", "user", list_="reference", project="proj")
        self.assertNotIn(ref.id, gtd.load("proj", self.root).fm["steps"])  # 資料は属するだけ
        self.assertEqual(gtd.lint(self.root), {})


class RecorderTest(Base):
    def test_agent_writes_commit_at_once_and_first_fold_human_changes(self):
        human = gtd.add(self.root, "人が足した", "user")
        self.assertIn("??", self.git("status", "--porcelain"))  # 人の変更はすぐにはコミットしない
        gtd.add(self.root, "エージェントが足した", "agent:w1")
        log = self.log().splitlines()
        self.assertRegex(log[0], r"^agent:w1\|add 20261124-[0-9a-f]{4}: エージェントが足した$")
        self.assertTrue(log[1].startswith("user|記録係: エージェントが書く前に人の変更をまとめる"))
        self.assertIn(f"items/{human.id}.md", self.git("show", "--name-only", "--format=", "HEAD~1"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_record_waits_for_quiet(self):
        gtd.add(self.root, "人が足した", "user")
        res = gtd.record(self.root, quiet=600)
        self.assertFalse(res["committed"])
        self.assertEqual(res["pending"], 1)
        res = gtd.record(self.root, quiet=600, now=time.time() + 601)
        self.assertTrue(res["committed"])
        self.assertTrue(self.log().startswith("user|記録係: 人の変更をまとめる（1 件）"))
        self.assertEqual(gtd.record(self.root)["pending"], 0)

    def test_init_is_idempotent_and_ignores_the_log(self):
        gtd.init(self.root)
        gtd.add(self.root, "題", "agent")
        self.assertNotIn(".log", self.git("ls-files"))
        self.assertEqual(self.git("config", "commit.gpgsign").strip(), "false")


class CasesTest(Base):
    def setUp(self):
        super().setUp()
        (self.cases / "refactor.md").write_text(CASE, encoding="utf-8")

    def case_text(self):
        return (self.cases / "refactor.md").read_text(encoding="utf-8")

    def line(self, section, index):
        data = gtd.cases_json(self.root)
        return next(l for l in data["cases"][0]["lines"] if l["section"] == section and l["index"] == index)

    def test_cases_json_lists_every_line(self):
        data = gtd.cases_json(self.root)
        self.assertEqual((data["total"], data["done"]), (6, 0))
        c = data["cases"][0]
        self.assertEqual((c["slug"], c["title"], c["short"], c["project"]), ("refactor", "架空の作り直し", "作り直し", None))
        self.assertEqual([l["section"] for l in c["lines"]], ["TODO", "TODO", "Waiting", "Later", "予定", "資料"])

    def test_from_case_next_keeps_due_and_marks_the_line(self):
        line = self.line("TODO", 0)
        res = gtd.from_case(self.root, "refactor", "TODO", 0, "next", "user", text=line["text"])
        fm = gtd.load(res["id"], self.root).fm
        self.assertEqual((fm["title"], fm["list"], fm["actor"], fm["due"], fm["from"]),
                         ("新しい API のテストを足す", "next", "me", "2026-11-25", "state/cases/refactor.md"))
        self.assertIn(f"- [11/25] 新しい API のテストを足す 〔移した→{res['id']}〕", self.case_text())
        self.assertEqual(self.line("TODO", 0)["moved"], res["id"])
        self.assertEqual(gtd.cases_json(self.root)["done"], 1)
        with self.assertRaises(gtd.Conflict):
            gtd.from_case(self.root, "refactor", "TODO", 0, "next", "user")
        self.assertEqual(gtd.lint(self.root), {})

    def test_from_case_marks_keep_cases_py_working(self):
        cm = gtd.cases_module()
        res = gtd.from_case(self.root, "refactor", "Waiting", 0, "waiting", "user")
        fm = gtd.load(res["id"], self.root).fm
        self.assertEqual((fm["title"], fm["then"]), ("PR のレビュー待ち", "指摘があれば直す"))
        case = cm.parse(self.cases / "refactor.md")
        wait, nxt = cm.split_next(case.items("Waiting")[0].text)
        self.assertEqual(nxt, f"指摘があれば直す 〔移した→{res['id']}〕")  # → のあとは元のまま

    def test_from_case_gcal_drop_and_stale_text(self):
        res = gtd.from_case(self.root, "refactor", "予定", 0, "gcal", "user")
        fm = gtd.load(res["id"], self.root).fm
        self.assertEqual(fm["title"], "Google Calendar に入れる: 定例で話す（11/26）")
        self.assertEqual(fm["then"], "宿題を足す")
        res = gtd.from_case(self.root, "refactor", "Later", 0, "drop", "user")
        self.assertIsNone(res["id"])
        self.assertIn("- 旧モジュールを消す 〔移さない〕", self.case_text())
        self.assertTrue(self.line("Later", 0)["dropped"])
        with self.assertRaises(gtd.Conflict):
            gtd.from_case(self.root, "refactor", "TODO", 1, "next", "user", text="違う文")
        with self.assertRaises(gtd.GtdError):
            gtd.from_case(self.root, "refactor", "TODO", 9, "next", "user")
        with self.assertRaises(gtd.Invalid):
            gtd.from_case(self.root, "../x", "TODO", 0, "next", "user")

    def test_step_needs_a_project_and_case_project_links_it(self):
        with self.assertRaises(gtd.Invalid):
            gtd.from_case(self.root, "refactor", "Later", 0, "step", "user")
        proj = gtd.case_project(self.root, "refactor", "user")
        self.assertTrue(proj["created"])
        self.assertEqual(gtd.case_project(self.root, "refactor", "user"), {"id": proj["id"], "created": False})
        pfm = gtd.load(proj["id"], self.root).fm
        self.assertEqual((pfm["list"], pfm["short"], pfm["from"]), ("project", "作り直し", "state/cases/refactor.md"))
        self.assertEqual(gtd.cases_json(self.root)["cases"][0]["project"], proj["id"])
        res = gtd.from_case(self.root, "refactor", "Later", 0, "step", "user")
        step = gtd.load(res["id"], self.root).fm
        self.assertEqual((step["project"], step["list"]), (proj["id"], "next"))  # next が無かったので繰り上がる
        self.assertEqual(gtd.load(proj["id"], self.root).fm["steps"], [res["id"]])
        res2 = gtd.from_case(self.root, "refactor", "TODO", 1, "next", "user")
        self.assertEqual(gtd.load(res2["id"], self.root).fm["project"], proj["id"])
        self.assertEqual(gtd.lint(self.root), {})


class SweepTest(Base):
    def test_closed_prs_resolve_the_wait(self):
        a = gtd.add(self.root, "レビュー待ち", "agent", list_="waiting", who="r", then="merge する", watch=[PR1])
        b = gtd.add(self.root, "ほかの待ち", "agent", list_="waiting", who="r", watch=[PR1, PR2])
        out = gtd.sweep(self.root, "agent", states_fn=states(**{PR1: "MERGED"}))
        self.assertEqual([e["id"] for e in out], [a.id])
        fm = gtd.load(a.id, self.root).fm
        self.assertEqual((fm["list"], fm["title"], fm["actor"], fm["links"]), ("next", "merge する", "me", [PR1]))
        self.assertNotIn("watch", fm)
        self.assertEqual(gtd.load(b.id, self.root).fm["list"], "waiting")
        self.assertIn("待ちが解けた（レビュー待ち）", gtd.load(a.id, self.root).body)

    def test_dry_run_changes_nothing(self):
        a = gtd.add(self.root, "待ち", "agent", list_="waiting", watch=[PR1])
        before = self.read(a.id)
        out = gtd.sweep(self.root, "agent", states_fn=states(**{PR1: "CLOSED"}), dry_run=True)
        self.assertEqual(len(out), 1)
        self.assertEqual(self.read(a.id), before)


class ReviewRegressionTest(Base):
    """見直しで見つかった問題が戻らないこと。"""

    def test_from_case_twice_at_once_makes_one_item(self):
        (self.cases / "c.md").write_text("# 案件\n\n## TODO\n- 1 つだけ\n", encoding="utf-8")
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "from-case", "c", "TODO", "0", "next", "--by", "user"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy()) for _ in range(4)]
        codes = sorted(p.wait() for p in procs)
        self.assertEqual(codes, [0, gtd.EXIT_CONFLICT, gtd.EXIT_CONFLICT, gtd.EXIT_CONFLICT])
        self.assertEqual(len(gtd.load_all(self.root)[0]), 1)
        self.assertEqual((self.cases / "c.md").read_text(encoding="utf-8").count("〔移した→"), 1)

    def test_note_does_not_enter_a_code_block(self):
        item = gtd.add(self.root, "題", "agent", body="## メモ\n\n```bash\n# install deps\nmake\n```\n\n- last")
        gtd.note(self.root, item.id, "メモ", "added", "agent")
        self.assertEqual(gtd.load(item.id, self.root).body, "## メモ\n\n```bash\n# install deps\nmake\n```\n\n- last\n- added")

    def test_values_with_odd_spaces_before_a_hash_survive(self):
        for value in ("レビュー　#12 を見る", "a\t#b", "x #y"):
            item = gtd.add(self.root, "題", "user", then=value)
            self.assertEqual(gtd.load(item.id, self.root).fm["then"], value, repr(value))

    def test_record_commits_a_deletion_once_quiet(self):
        item = gtd.add(self.root, "消す", "agent")
        (self.root / "items" / f"{item.id}.md").unlink()
        self.assertFalse(gtd.record(self.root, quiet=600)["committed"])
        self.assertTrue(gtd.record(self.root, quiet=600, now=time.time() + 601)["committed"])

    def test_a_broken_git_does_not_stop_a_write(self):
        (self.root / ".git" / "index.lock").write_text("")
        res = self.run_cli("add", "git が不調でも書く", "--by", "agent:x")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("記録係", res.stderr)
        res = self.run_cli("record", "--quiet", "0")
        self.assertEqual(res.returncode, gtd.EXIT_GIT)
        self.assertNotIn("Traceback", res.stderr)

    def test_values_that_look_like_flags(self):
        res = self.run_cli("add", "--title=--by", "--by", "user")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(gtd.load(json.loads(res.stdout)["id"], self.root).fm["title"], "--by")

    def test_expect_needs_a_hash(self):
        item = gtd.add(self.root, "題", "user", who="a")
        with self.assertRaises(gtd.Invalid):
            gtd.set_fields(self.root, item.id, ["who=b"], "user", expect=["who=OTHER"])


class CliTest(Base):
    def test_add_json_move_and_exit_codes(self):
        res = self.run_cli("add", "CLI で足した", "--list", "next", "--actor", "me", "--by", "user")
        self.assertEqual(res.returncode, 0, res.stderr)
        added = json.loads(res.stdout)
        state = json.loads(self.run_cli("json").stdout)
        self.assertEqual(state["items"][0]["title"], "CLI で足した")
        res = self.run_cli("move", added["id"], "someday", "--hash", "0000000000000000")
        self.assertEqual(res.returncode, gtd.EXIT_CONFLICT)
        self.assertIn("ほかの人が先に直した", res.stderr)
        self.assertEqual(self.run_cli("move", added["id"], "nowhere").returncode, gtd.EXIT_INVALID)
        self.assertEqual(self.run_cli("show", "20990101-0000").returncode, gtd.EXIT_NOT_FOUND)
        self.assertEqual(self.run_cli("show", added["id"]).stdout, self.read(added["id"]))

    def test_lint_cli_fix(self):
        path = self.root / "items" / "x1.md"
        path.write_text("---\nid: x1\ntitle: 題\nlist: next\n---\n\n* a\n\n\n* b\n", encoding="utf-8")
        res = self.run_cli("lint")
        self.assertEqual(res.returncode, gtd.EXIT_INVALID)
        self.assertIn("リストの印は - にする", res.stdout)
        self.assertEqual(self.run_cli("lint", "--fix").returncode, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "---\nid: x1\ntitle: 題\nlist: next\n---\n\n- a\n\n- b\n")


if __name__ == "__main__":
    unittest.main()
