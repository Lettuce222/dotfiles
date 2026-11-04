"""dash.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_dash.py"""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dash  # noqa: E402
import topics  # noqa: E402


class GtdTest(unittest.TestCase):
    def test_attrs_and_sub_lines(self):
        text = (
            "# next-actions\n\n## 2026-01-02\n\n"
            "- [ ] 資料を仕上げる @desk project:: 計測 due:: 2026-01-03 note:: notes/a.md\n"
            "  - 補足の行\n"
            "- [x] 終わった project:: 計測 done:: 2026-01-02\n"
        )
        items = dash.parse_gtd(text, "next-actions")
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.body, "資料を仕上げる @desk")
        self.assertEqual(first.attrs, {"project": "計測", "due": "2026-01-03", "note": "notes/a.md"})
        self.assertEqual(first.sub, ["補足の行"])
        self.assertEqual(first.section, "2026-01-02")
        self.assertTrue(first.open)
        self.assertFalse(items[1].open)

    def test_doing(self):
        (item,) = dash.parse_gtd("- [ ] 作業 doing:: 2026-01-01\n", "next-actions")
        self.assertTrue(item.doing)
        self.assertFalse(item.waiting)
        (item,) = dash.parse_gtd("- [x] 作業 doing:: 2026-01-01\n", "done")
        self.assertFalse(item.doing)

    def test_handed_over_items_are_waiting_not_doing(self):
        cases = [
            ("- [ ] 作業 doing:: 2026-01-01 waiting:: 2026-01-02\n", "next-actions"),
            ("- [ ] 作業 doing:: 2026-01-01\n", "waiting-for"),
            ("- [ ] 作業 worker:: repo.task doing:: 2026-01-01 waiting:: 2026-01-02\n", "waiting-for"),
            ("- [ ] 作業 worker:: repo.task\n", "next-actions"),
        ]
        for line, file in cases:
            with self.subTest(line=line, file=file):
                (item,) = dash.parse_gtd(line, file)
                self.assertTrue(item.waiting)
                self.assertFalse(item.doing)
        (item,) = dash.parse_gtd("- [x] 作業 worker:: repo.task waiting:: 2026-01-02\n", "done")
        self.assertFalse(item.waiting)

    def test_split_overview(self):
        gtd = {name: [] for name in dash.GTD_FILES}
        gtd["next-actions"] = dash.parse_gtd(
            "- [ ] 着手中 doing:: 2026-01-01\n"
            "- [ ] 渡した doing:: 2026-01-01 waiting:: 2026-01-02\n"
            "- [ ] まだ\n"
            "- [x] 終わった doing:: 2026-01-01\n",
            "next-actions",
        )
        gtd["waiting-for"] = dash.parse_gtd(
            "- [ ] worker に任せた worker:: repo.task doing:: 2026-01-01 waiting:: 2026-01-02\n"
            "- [ ] 返事待ち who:: 誰か\n",
            "waiting-for",
        )
        gtd["inbox"] = dash.parse_gtd("- [ ] メモ\n", "inbox")
        gtd["projects"] = dash.parse_gtd("- [ ] 計画 doing:: 2026-01-01\n", "projects")
        doing, nexts, waiting, inbox = dash.split_overview(gtd)
        bodies = lambda items: [it.body for it in items]  # noqa: E731
        self.assertEqual(bodies(doing), ["着手中"])
        self.assertEqual(bodies(nexts), ["まだ"])
        self.assertEqual(bodies(waiting), ["渡した", "worker に任せた", "返事待ち"])
        self.assertEqual(bodies(inbox), ["メモ"])

    def test_waiting_item_shows_worker_and_handover_date(self):
        (item,) = dash.parse_gtd(
            "- [ ] 任せた worker:: dotfiles.task doing:: 2026-01-01 waiting:: 2026-01-02\n", "waiting-for"
        )
        html = dash.render_item(item, dash.dt.date(2026, 1, 3))
        self.assertIn("worker: dotfiles.task", html)
        self.assertIn("/workers#", html)
        self.assertIn("渡した日 2026-01-02", html)
        self.assertNotIn("着手", html)

    def test_url_with_colons_is_not_an_attr(self):
        (item,) = dash.parse_gtd("- [ ] 見る https://example.com/a::b link:: https://example.com/x\n", "inbox")
        self.assertEqual(item.attrs, {"link": "https://example.com/x"})


class MarkdownTest(unittest.TestCase):
    def render(self, text, base="notes/a.md"):
        return dash.Renderer(base).render(text)

    def test_escapes_html(self):
        out = self.render("<script>alert(1)</script> **太字**")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("<strong>太字</strong>", out)

    def test_table(self):
        out = self.render("| a | b |\n|---|--:|\n| `x\\|y` | 2 |\n")
        self.assertIn("<th>a</th>", out)
        self.assertIn('<td class="al-right">2</td>', out)
        self.assertIn("<code>x|y</code>", out)

    def test_code_block_is_not_formatted(self):
        out = self.render("```sh\n**not bold** <b>\n```\n")
        self.assertIn('<pre><code class="lang-sh">**not bold** &lt;b&gt;</code></pre>', out)

    def test_nested_list_and_tasks(self):
        out = self.render("- a\n  - b\n- [x] c\n1. d\n")
        self.assertIn("<ul><li>a<ul><li>b</li></ul></li><li>", out)
        self.assertIn('class="done"', out)
        self.assertIn("<ol><li>d</li></ol>", out)

    def test_links(self):
        out = self.render("[外](https://example.com) [隣](b.md) [上](../gtd/c.md#x) [悪](javascript:alert(1))")
        self.assertIn('href="https://example.com" target="_blank" rel="noopener noreferrer"', out)
        self.assertIn('href="/doc?path=notes/b.md"', out)
        self.assertIn('href="/doc?path=gtd/c.md#x"', out)
        self.assertNotIn('href="javascript', out)


class ResolveDocTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        (home / "notes").mkdir()
        (home / "notes" / "a.md").write_text("# A\n", encoding="utf-8")
        (home / "profile.md").write_text("secret\n", encoding="utf-8")
        (home / "notes" / "x.txt").write_text("x\n", encoding="utf-8")
        self.env = {"AGENT_HUB_HOME": str(home)}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_only_markdown_under_doc_dirs(self):
        self.assertIsNotNone(dash.resolve_doc("notes/a.md"))
        for bad in ("profile.md", "notes/../profile.md", "/etc/passwd", "notes/x.txt", "../../etc/hosts", ""):
            self.assertIsNone(dash.resolve_doc(bad), bad)


REPORTS = """
## 2026-01-02 10:00:00 要判断

[要判断] repo.task: 方式を決めてほしい
- 選択肢: A で進める
- 選択肢：B で進める
 ## 字下げされた見出しは本文

## 2026-01-02 10:05:00 ブロック

[ブロック] repo.task: 権限が足りない

## 2026-01-02 10:06:00 回答 2026-01-02 10:00:00

A で進める
"""


class StateDirMixin:
    """AGENT_HUB_HOME と XDG_STATE_HOME を一時ディレクトリに向ける。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "state" / "agent-hub"
        (self.state / "reports").mkdir(parents=True)
        (root / "hub").mkdir()
        self.env = {"AGENT_HUB_HOME": str(root / "hub"), "XDG_STATE_HOME": str(root / "state")}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def write_worker(self, name, reports):
        (self.state / f"{name}.md").write_text("あなたのセッション名: x\n", encoding="utf-8")
        (self.state / "reports" / f"{name}.md").write_text(reports, encoding="utf-8")


class ReportsTest(unittest.TestCase):
    def test_parse_and_link_answers(self):
        entries = dash.parse_reports(REPORTS, "repo.task")
        self.assertEqual([e.kind for e in entries], ["要判断", "ブロック", "回答"])
        ask, block, ans = entries
        self.assertEqual(ask.summary, "[要判断] repo.task: 方式を決めてほしい")
        self.assertEqual(ask.choices, ["A で進める", "B で進める"])
        self.assertIn("字下げされた見出しは本文", ask.body)
        self.assertEqual(ask.answers, [ans])
        self.assertFalse(ask.is_open)
        self.assertTrue(block.is_open)
        self.assertEqual(ans.ref, "2026-01-02 10:00:00")
        self.assertEqual(ans.body, "A で進める")

    def test_done_supersedes_earlier_asks(self):
        text = REPORTS + "\n## 2026-01-02 11:00:00 完了\n\n[完了] repo.task: 終わり\n"
        entries = dash.parse_reports(text, "repo.task")
        self.assertFalse(any(e.is_open for e in entries))
        text += "\n## 2026-01-02 12:00:00 要判断\n\n再開後の相談\n"
        self.assertTrue(dash.parse_reports(text, "repo.task")[-1].is_open)

    def test_resolve_marks_handled(self):
        text = REPORTS + "\n## 2026-01-02 10:07:00 対応済み 2026-01-02 10:05:00\n\n（対応済み）\n"
        self.assertFalse(any(e.is_open for e in dash.parse_reports(text, "w")))

    def test_clean_answer(self):
        self.assertEqual(dash.clean_answer(" a\nb\r\n\tc\x1b[2J\x00‮d "), "a b c[2Jd")
        self.assertEqual(dash.clean_answer("絵文字👍🏽は残す"), "絵文字👍🏽は残す")


class AnswerMixin(StateDirMixin):
    """報告のある worker を 1 つ置き、tmux を偽物にする。"""

    WINDOW = {"id": "@1", "name": "repo:task", "session": "s", "pane": "%9"}

    def setUp(self):
        super().setUp()
        self.write_worker("repo.task", REPORTS)
        self.sent = []
        patches = [
            mock.patch.object(dash, "tmux_windows", lambda: {"repo.task": self.WINDOW, "other.task": self.WINDOW}),
            mock.patch.object(dash, "capture_pane", lambda pane: "> \n"),
            mock.patch.object(dash, "send_to_pane", lambda pane, text: self.sent.append((pane, text)) or True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def reports(self):
        return dash.parse_reports((self.state / "reports" / "repo.task.md").read_text(encoding="utf-8"), "repo.task")


class AnswerTest(AnswerMixin, unittest.TestCase):
    def test_send_answer(self):
        result = dash.answer_report("repo.task", "2026-01-02 10:05:00", "send", "付与した\nので続けて\x07")
        self.assertEqual(result, "sent")
        self.assertEqual(self.sent, [("%9", "[ダッシュボードから回答 2026-01-02 10:05:00] 付与した ので続けて")])
        last = self.reports()[-1]
        self.assertEqual((last.kind, last.ref, last.body), ("回答", "2026-01-02 10:05:00", "付与した ので続けて"))
        # 同じ報告には二度送らない
        self.assertEqual(dash.answer_report("repo.task", "2026-01-02 10:05:00", "send", "もう一度"), "stale")
        self.assertEqual(len(self.sent), 1)

    def test_resolve_without_sending(self):
        self.assertEqual(dash.answer_report("repo.task", "2026-01-02 10:05:00", "resolve", ""), "resolved")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.reports()[-1].kind, "対応済み")

    def test_target_restrictions(self):
        ref = "2026-01-02 10:05:00"
        # 記録ファイルが無い worker（window はあっても）、パスに使えない名前
        for name in ("other.task", "../repo.task", "repo.task/../x", "", ".hidden"):
            self.assertEqual(dash.answer_report(name, ref, "send", "x"), "unknown", name)
        # 存在しない報告、対応済みの報告、完了の報告
        self.assertEqual(dash.answer_report("repo.task", "2026-01-02 09:00:00", "send", "x"), "stale")
        self.assertEqual(dash.answer_report("repo.task", "2026-01-02 10:00:00", "send", "x"), "stale")
        self.assertEqual(dash.answer_report("repo.task", ref, "other", "x"), "stale")
        self.assertEqual(dash.answer_report("repo.task", ref, "send", " \n\x01 "), "empty")
        self.assertEqual(dash.answer_report("repo.task", ref, "send", "あ" * (dash.MAX_ANSWER + 1)), "toolong")
        self.assertEqual(self.sent, [])

    def test_no_window_or_dialog(self):
        ref = "2026-01-02 10:05:00"
        with mock.patch.object(dash, "tmux_windows", lambda: {}):
            self.assertEqual(dash.answer_report("repo.task", ref, "send", "x"), "nowindow")
        with mock.patch.object(dash, "capture_pane", lambda pane: "Do you want to proceed?\n❯ 1. Yes\n  2. No\n"):
            self.assertEqual(dash.answer_report("repo.task", ref, "send", "x"), "dialog")
        with mock.patch.object(dash, "tmux_windows", lambda: {"repo.task": dict(self.WINDOW, name="🔴repo:task")}):
            self.assertEqual(dash.answer_report("repo.task", ref, "send", "x"), "dialog")
        self.assertEqual(self.sent, [])
        self.assertTrue(self.reports()[1].is_open)


class ReportScriptTest(StateDirMixin, unittest.TestCase):
    SCRIPT = Path(__file__).resolve().parent / "report.sh"

    def run_script(self, *args, body="本文"):
        return subprocess.run(["sh", str(self.SCRIPT), *args], input=body, capture_output=True, text=True, env=os.environ.copy())

    def test_appends_parseable_report(self):
        res = self.run_script("repo.task", "要判断", body="[要判断] repo.task: 相談\n## 見出しっぽい行\n選択肢: A\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        path = self.state / "reports" / "repo.task.md"
        self.assertEqual(res.stdout.strip(), str(path))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        (entry,) = dash.parse_reports(path.read_text(encoding="utf-8"), "repo.task")
        self.assertEqual(entry.kind, "要判断")
        self.assertEqual(entry.choices, ["A"])
        self.assertIn(" ## 見出しっぽい行", entry.body)

    def test_rejects_bad_input(self):
        self.assertEqual(self.run_script("../x", "完了").returncode, 2)
        self.assertEqual(self.run_script("repo.task", "回答").returncode, 2)
        self.assertEqual(self.run_script("repo.task", "完了", body="").returncode, 2)
        self.assertFalse((self.state / "reports" / "repo.task.md").exists())


MY_PRS_DATA = {
    "generated_at": "2026-01-10T00:00:00+00:00",
    "viewer": "me",
    "team_requests": 2,
    "review_requests": [
        {"pr": "o/r#1", "url": "https://github.com/o/r/pull/1", "title": "<b>機能</b>", "author": "alice",
         "author_is_person": True, "waiting_hours": 30, "only_blocker": True, "re_review": True, "stale": False,
         "idle_days": 0, "size": 15},
    ],
    "own_prs": [
        {"pr": "o/r#2", "url": "javascript:alert(1)", "title": "直す", "draft": False, "stale": False, "idle_days": 1,
         "ci": "failure", "states": ["ci_failed", "waiting"], "waiting": [{"reviewer": "bob", "hours": 3}],
         "unanswered_threads": 0, "changes_requested_by": [], "stale_approvals": []},
        {"pr": "o/r#3", "url": "https://github.com/o/r/pull/3", "title": "下書き", "draft": True, "stale": False,
         "idle_days": 1, "ci": None, "states": [], "waiting": [], "unanswered_threads": 0,
         "changes_requested_by": [], "stale_approvals": []},
    ],
    "excluded": [],
}


class MyPrsTest(unittest.TestCase):
    def cache(self, fetch):
        c = dash.MyPRs(fetch=fetch)
        c.get()  # 取得を始める
        for _ in range(100):
            if not c.pending:
                break
            threading.Event().wait(0.01)
        return c

    def test_render(self):
        with mock.patch.object(dash, "MY_PRS", self.cache(lambda: MY_PRS_DATA)):
            html, n_requests, n_act = dash.render_my_prs()
        self.assertEqual((n_requests, n_act), (1, 1))
        self.assertIn("自分宛てのレビュー依頼（1）", html)
        self.assertIn("&lt;b&gt;機能&lt;/b&gt;", html)
        self.assertIn("30時間待ち", html)
        self.assertIn("再レビュー", html)
        self.assertIn("チーム宛ての依頼 2 件", html)
        self.assertIn('<span class="chip bad">CI 失敗</span>', html)
        self.assertIn("bob 3時間待ち", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("draft・長く動いていない PR（1）", html)

    def test_failure_keeps_last_result(self):
        c = self.cache(lambda: MY_PRS_DATA)
        c.fetch = mock.Mock(side_effect=RuntimeError("gh api graphql: HTTP 401"))
        c.at = 0  # 古くして取り直させる
        c.get()
        for _ in range(100):
            if not c.pending:
                break
            threading.Event().wait(0.01)
        with mock.patch.object(dash, "MY_PRS", c):
            html, n_requests, _ = dash.render_my_prs()
        self.assertEqual(n_requests, 1)
        self.assertIn("取得に失敗しました: RuntimeError: gh api graphql: HTTP 401", html)

    def test_not_fetched_yet(self):
        c = dash.MyPRs(fetch=lambda: MY_PRS_DATA)
        c.pending = True  # 取得中のまま
        with mock.patch.object(dash, "MY_PRS", c):
            html, n_requests, n_act = dash.render_my_prs()
        self.assertEqual((n_requests, n_act), (-1, -1))
        self.assertIn("取得中…", html)


class ServerTest(StateDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        old = (dash.Handler.allowed_hosts, dash.Handler.token)
        dash.Handler.allowed_hosts = {f"127.0.0.1:{self.port}"}
        dash.Handler.token = "t" * 43
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

        def restore():
            self.server.shutdown()
            self.server.server_close()
            dash.Handler.allowed_hosts, dash.Handler.token = old

        self.addCleanup(restore)
        self.calls = []
        # 本物の tmux サーバーは読まない
        for p in (
            mock.patch.object(dash, "answer_report", lambda *a: self.calls.append(a) or "sent"),
            mock.patch.object(dash, "tmux_windows", lambda: {}),
            # 本物の GitHub には問い合わせない
            mock.patch.object(dash, "MY_PRS", dash.MyPRs(fetch=lambda: MY_PRS_DATA)),
        ):
            p.start()
            self.addCleanup(p.stop)

    def status(self, req):
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def post(self, fields, headers=None):
        data = urllib.parse.urlencode(fields).encode()
        h = {"Origin": self.origin, "Content-Type": "application/x-www-form-urlencoded"}
        h.update(headers or {})

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        req = urllib.request.Request(f"{self.origin}/inbox/answer", data=data, headers=h, method="POST")
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as res:
                return res.status, res.headers.get("Location")
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, e.headers.get("Location")

    def test_rejects_foreign_host(self):
        req = urllib.request.Request(f"{self.origin}/app.css", headers={"Host": "evil.example"})
        self.assertEqual(self.status(req), 403)
        self.assertEqual(self.status(f"{self.origin}/app.css"), 200)

    def test_inbox_page_embeds_token(self):
        self.write_worker("repo.task", REPORTS)
        with urllib.request.urlopen(f"{self.origin}/inbox", timeout=5) as res:
            body = res.read().decode()
        self.assertIn('name="token" value="' + "t" * 43, body)
        self.assertIn("未対応の要判断・ブロック（1）", body)
        with urllib.request.urlopen(f"{self.origin}/", timeout=5) as res:
            page = res.read().decode()
        self.assertIn('<a class="stat alert" href="/inbox"><span class="num">1</span>', page)
        self.assertIn('<section id="prs">', page)

    def test_post_requires_token_and_origin(self):
        ok = {"token": "t" * 43, "worker": "repo.task", "ref": "2026-01-02 10:05:00", "action": "send", "text": "x"}
        self.assertEqual(self.post(dict(ok, token="wrong"))[0], 403)
        self.assertEqual(self.post({k: v for k, v in ok.items() if k != "token"})[0], 403)
        self.assertEqual(self.post(ok, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.post(ok, {"Origin": "null"})[0], 403)
        self.assertEqual(self.post(ok, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.post(ok, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.post(ok, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post(dict(ok, text="x" * dash.MAX_FORM_BYTES))[0], 413)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.post(ok), (303, "/inbox?r=sent"))
        self.assertEqual(self.calls, [("repo.task", "2026-01-02 10:05:00", "send", "x")])

    def test_choice_button_sends_its_value(self):
        fields = {"token": "t" * 43, "worker": "repo.task", "ref": "r", "choice": "A で進める", "text": "無視"}
        self.assertEqual(self.post(fields)[0], 303)
        self.assertEqual(self.calls, [("repo.task", "r", "send", "A で進める")])

    def test_get_does_not_answer(self):
        self.assertEqual(self.status(f"{self.origin}/inbox/answer?token=" + "t" * 43), 404)
        self.assertEqual(self.calls, [])


class StatusTest(StateDirMixin, unittest.TestCase):
    """dash.py status --json。tmux・claude・gh は偽物に差し替える。"""

    WINDOWS = {
        "repo.task": {"id": "@1", "name": "🟡 repo:task", "session": "s", "pane": "%1"},
        "repo.ask": {"id": "@2", "name": "🔴 repo:ask", "session": "s", "pane": "%2"},
    }
    AGENTS = {"repo.task": {"name": "repo.task", "status": "idle"}, "repo.ask": {"name": "repo.ask", "status": "busy"}}

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.cache_env = {"XDG_CACHE_HOME": str(root / "cache")}
        self.old.update({k: os.environ.get(k) for k in self.cache_env})
        os.environ.update(self.cache_env)
        hub = root / "hub"
        (hub / "gtd").mkdir()
        today = dash.dt.date.today()
        soon = (today + dash.dt.timedelta(days=2)).isoformat()
        later = (today + dash.dt.timedelta(days=10)).isoformat()
        nexts = "".join(f"- [ ] 次 {n}\n" for n in range(12))
        (hub / "gtd" / "next-actions.md").write_text(
            f"- [ ] 着手中 doing:: 2026-01-01 project:: 計測 due:: {soon}\n- [ ] 先の話 due:: {later}\n{nexts}",
            encoding="utf-8",
        )
        (hub / "gtd" / "waiting-for.md").write_text(
            "- [ ] 任せた worker:: repo.task repo:: o/r waiting:: 2026-01-02\n", encoding="utf-8"
        )
        self.write_record("repo.task", branch="agent/task")
        self.write_record("repo.ask")
        self.write_record("repo.gone")
        (self.state / "reports" / "repo.ask.md").write_text(REPORTS, encoding="utf-8")
        self.spawned = []
        self.windows = dict(self.WINDOWS)
        self.agents = (dict(self.AGENTS), "")
        for p in (
            mock.patch.object(dash, "tmux_windows_full", lambda: (self.windows, "")),
            mock.patch.object(dash, "capture_pane", lambda pane: "> \n"),
            mock.patch.object(dash, "claude_agents", lambda: self.agents),
            mock.patch.object(dash, "spawn_refresh", lambda: self.spawned.append(1) or True),
            mock.patch.object(dash, "send_to_pane", mock.Mock(side_effect=AssertionError("送らない"))),
        ):
            p.start()
            self.addCleanup(p.stop)

    def write_record(self, name, branch=""):
        lines = [f"あなたのセッション名: {name}"] + ([f"作業ブランチ: {branch}"] if branch else [])
        (self.state / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_cache(self, at=None):
        at = dash.time.time() if at is None else at
        dash.save_pr_cache({
            "my_prs": {"at": at, "data": MY_PRS_DATA, "error": ""},
            "worker_prs": {dash.pr_key("o/r", "agent/task"): {"at": at, "pr": {
                "number": 7, "url": "https://github.com/o/r/pull/7", "title": "作業", "state": "OPEN", "isDraft": True,
                "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"}]}}},
        })

    def test_parts(self):
        self.write_cache()
        out = dash.collect_status()
        json_text = dash.json.dumps(out, ensure_ascii=False)  # JSON にできる
        self.assertIn("generated_at", json_text)
        self.assertEqual(out["errors"], {})
        self.assertEqual(self.spawned, [])  # キャッシュが新しければ取り直さない

        (ask,) = out["inbox"]
        self.assertEqual((ask["worker"], ask["ref"], ask["kind"]), ("repo.ask", "2026-01-02 10:05:00", "ブロック"))
        self.assertEqual(ask["summary"], "[ブロック] repo.task: 権限が足りない")
        self.assertEqual((ask["window_id"], ask["dialog"]), ("@2", True))  # window 名の 🔴

        workers = {w["name"]: w for w in out["workers"]}
        self.assertEqual({n: w["status"] for n, w in workers.items()},
                         {"repo.task": "idle", "repo.ask": "permission", "repo.gone": "no_window"})
        task = workers["repo.task"]
        self.assertEqual((task["window_id"], task["claude_status"], task["open_reports"]), ("@1", "idle", 0))
        self.assertEqual(task["item"]["body"], "任せた")
        self.assertEqual(task["pr_status"], "ok")
        self.assertEqual(task["pr"], {"number": 7, "url": "https://github.com/o/r/pull/7", "title": "作業", "state": "draft",
                                      "ci": {"text": "CI 失敗 1/1", "level": "bad"}})
        self.assertEqual((workers["repo.ask"]["pr_status"], workers["repo.ask"]["open_reports"]), ("unknown_repo", 1))

        gtd = out["gtd"]
        self.assertEqual([i["body"] for i in gtd["doing"]], ["着手中"])
        self.assertEqual(gtd["doing"][0]["attrs"]["project"], "計測")
        self.assertEqual([i["body"] for i in gtd["waiting"]], ["任せた"])
        self.assertEqual((len(gtd["next"]), gtd["next_total"]), (10, 13))
        self.assertEqual([(i["body"], i["days_left"]) for i in gtd["due_soon"]], [("着手中", 2)])

        prs = out["prs"]
        self.assertEqual([i["pr"] for i in prs["review_requests"]], ["o/r#1"])
        self.assertEqual([i["pr"] for i in prs["own_action"]], ["o/r#2"])  # draft の #3 は入れない
        self.assertEqual((prs["pending"], prs["team_requests"]), (False, 2))

    def test_stale_cache_starts_refresh_without_waiting(self):
        self.write_cache(at=1)
        out = dash.collect_status()
        self.assertEqual(self.spawned, [1])
        self.assertEqual(out["prs"]["review_requests"][0]["pr"], "o/r#1")  # 古い結果はそのまま出す

    def test_first_run_is_pending(self):
        out = dash.collect_status()
        self.assertEqual(self.spawned, [1])
        self.assertTrue(out["prs"]["pending"])
        self.assertEqual({w["name"]: w["pr_status"] for w in out["workers"]}["repo.task"], "pending")

    def test_no_prs(self):
        out = dash.collect_status(with_prs=False)
        self.assertEqual(self.spawned, [])
        self.assertTrue(out["prs"]["skipped"])
        self.assertEqual({w["pr_status"] for w in out["workers"]}, {"skipped"})

    def test_failures_only_empty_their_part(self):
        self.write_cache()
        self.windows = {}
        self.agents = ({}, "OSError: claude がありません")
        with mock.patch.object(dash, "tmux_windows_full", lambda: ({}, "no server running")), \
             mock.patch.object(dash, "load_reports", mock.Mock(side_effect=RuntimeError("壊れた"))):
            out = dash.collect_status()
        self.assertEqual(out["errors"], {"tmux": "no server running", "claude": "OSError: claude がありません",
                                         "inbox": "RuntimeError: 壊れた"})
        self.assertEqual(out["inbox"], [])
        self.assertEqual({w["status"] for w in out["workers"]}, {"no_window"})
        self.assertEqual(len(out["gtd"]["doing"]), 1)

    def test_status_falls_back_to_window_mark(self):
        self.agents = ({}, "")
        out = dash.collect_status(with_prs=False)
        self.assertEqual({w["name"]: w["status"] for w in out["workers"]}["repo.task"], "busy")  # 🟡

    def test_prs_fetch_error_is_reported(self):
        dash.save_pr_cache({"my_prs": {"at": dash.time.time(), "data": None, "error": "RuntimeError: HTTP 401"},
                            "worker_prs": {}})
        out = dash.collect_status()
        self.assertEqual(out["errors"]["prs"], "RuntimeError: HTTP 401")
        self.assertEqual(out["prs"]["review_requests"], [])

    def test_refresh_keeps_last_result_on_failure(self):
        calls = []
        dash.refresh_pr_cache(lambda: MY_PRS_DATA, lambda repo, branch: calls.append((repo, branch)) or {"none": True}, now=1000)
        self.assertEqual(calls, [("o/r", "agent/task")])
        cache = dash.load_pr_cache()
        self.assertEqual(cache["my_prs"]["data"], MY_PRS_DATA)
        # 新しいうちは取り直さない
        dash.refresh_pr_cache(mock.Mock(side_effect=AssertionError), mock.Mock(side_effect=AssertionError), now=1001)
        cache = dash.refresh_pr_cache(mock.Mock(side_effect=RuntimeError("HTTP 502")), lambda r, b: {"error": "x"}, now=5000)
        self.assertEqual(cache["my_prs"]["data"], MY_PRS_DATA)
        self.assertEqual(cache["my_prs"]["error"], "RuntimeError: HTTP 502")
        self.assertEqual(cache["worker_prs"][dash.pr_key("o/r", "agent/task")]["pr"], {"error": "x"})

    def test_cli_prints_json(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf):
            self.assertEqual(dash.main(["status", "--json", "--no-prs"]), 0)
        self.assertEqual(dash.json.loads(buf.getvalue())["inbox"][0]["worker"], "repo.ask")


class AnswerCliTest(AnswerMixin, unittest.TestCase):
    """dash.py answer。受信箱と同じ answer_report を通る。"""

    def answer(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            code = dash.main(["answer", *args])
        return code, out.getvalue() + err.getvalue()

    def test_send_and_done(self):
        code, msg = self.answer("repo.task", "2026-01-02 10:05:00", "続けて")
        self.assertEqual((code, msg.split(":")[0]), (0, "sent"))
        self.assertEqual(self.sent, [("%9", "[ダッシュボードから回答 2026-01-02 10:05:00] 続けて")])
        self.assertEqual(self.reports()[-1].kind, "回答")
        code, msg = self.answer("repo.task", "2026-01-02 10:05:00", "--done")
        self.assertEqual((code, msg.split(":")[0]), (1, "stale"))
        self.assertEqual(msg.count("\n"), 1)

    def test_done_without_sending(self):
        code, msg = self.answer("repo.task", "2026-01-02 10:05:00", "--done")
        self.assertEqual((code, msg.split(":")[0]), (0, "resolved"))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.reports()[-1].kind, "対応済み")

    def test_failures(self):
        self.assertEqual(self.answer("other.task", "2026-01-02 10:05:00", "x")[0], 1)
        with mock.patch.object(dash, "capture_pane", lambda pane: "Do you want to proceed?\n"):
            code, msg = self.answer("repo.task", "2026-01-02 10:05:00", "x")
        self.assertEqual((code, msg.split(":")[0]), (1, "dialog"))
        self.assertEqual(self.sent, [])
        with mock.patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit):
            dash.main(["answer", "repo.task", "2026-01-02 10:05:00", "x", "--done"])


class TopicsMixin(StateDirMixin):
    """worker を 1 つ置き、その transcript と tmux と claude agents を偽物にする。"""

    WINDOW = {"id": "@7", "name": "🟢 repo:task", "session": "s", "pane": "%9", "pane_pid": 500}

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name).resolve()
        self.worktree = root / "wt"
        self.worktree.mkdir()
        (self.state / "repo.task.md").write_text(
            f"あなたのセッション名: repo.task\n作業場所: {self.worktree}\n作業ブランチ: agent/task\n", encoding="utf-8")
        self.env2 = {"CLAUDE_CONFIG_DIR": str(root / "claude"), "AGENT_HUB_OPEN_DIRS": str(root / "out")}
        self.old.update({k: os.environ.get(k) for k in self.env2})
        os.environ.update(self.env2)
        self.out = root / "out"
        self.out.mkdir()
        (self.out / "after-1.png").write_bytes(b"\x89PNG")
        (root / "secret.png").write_bytes(b"\x89PNG")
        self.secret = root / "secret.png"
        self.transcript = topics.project_dir(str(self.worktree)) / "sess-1.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.write_transcript("2026-01-02T01:00:00Z", f"撮りました: `{self.out / 'after-1.png'}` と {self.secret}")
        self.agents = [{"pid": 501, "name": "repo.task", "cwd": str(self.worktree), "sessionId": "sess-1", "status": "idle"}]
        self.pane = "> \n"
        self.sent, self.ran = [], []
        patches = [
            mock.patch.object(dash, "tmux_windows", lambda: {"repo.task": self.WINDOW}),
            mock.patch.object(dash, "capture_pane", lambda pane: self.pane),
            mock.patch.object(dash, "send_to_pane", lambda pane, text: self.sent.append((pane, text)) or True),
            mock.patch.object(dash.AGENTS, "get", lambda: (self.agents, {501: 500})),
            mock.patch.object(dash, "TRANSCRIPTS", topics.TranscriptCache()),
            mock.patch.object(dash, "run", lambda cmd, *a, **kw: self.ran.append(cmd) or ""),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def write_transcript(self, ts, text):
        rows = [
            {"type": "user", "timestamp": "2026-01-02T00:59:00Z", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "指示"}},
            {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}},
        ]
        self.transcript.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def topic(self):
        (t,) = dash.load_topics()
        return t


class TopicsTest(TopicsMixin, unittest.TestCase):
    def test_transcript_is_found_from_pane_process(self):
        t = self.topic()
        self.assertEqual(t.agent["sessionId"], "sess-1")
        self.assertEqual([e.kind for e in t.transcript.entries], ["user", "assistant"])
        self.assertEqual(t.state, "unread")
        self.assertTrue(t.summary().startswith("撮りました"))

    def test_fallback_without_live_session(self):
        self.agents = []
        self.transcript.with_name("sess-1.jsonl").write_text(
            '{"type":"agent-name","agentName":"repo.task"}\n' + self.transcript.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertIsNotNone(self.topic().transcript)

    def test_open_report_or_dialog_means_waiting(self):
        (self.state / "reports" / "repo.task.md").write_text(REPORTS, encoding="utf-8")
        t = self.topic()
        self.assertEqual(t.state, "waiting")
        self.assertIn("権限が足りない", t.summary())
        (self.state / "reports" / "repo.task.md").unlink()
        self.pane = "Do you want to proceed?\n❯ 1. Yes\n"
        self.assertEqual(self.topic().state, "waiting")

    def test_opening_marks_read_until_next_reply(self):
        self.assertTrue(self.topic().unread)
        title, body = dash.page_topic("tok", "repo.task", mark_seen=False)
        self.assertTrue(self.topic().unread)
        dash.page_topic("tok", "repo.task")
        self.assertFalse(self.topic().unread)
        self.assertEqual(self.topic().state, "idle")
        self.write_transcript("2026-01-02T02:00:00Z", "次の返答")
        self.assertTrue(self.topic().unread)

    def test_page_shows_allowed_paths_as_buttons_and_images(self):
        _, body = dash.page_topic("tok", "repo.task")
        allowed = str(self.out / "after-1.png")
        self.assertIn(f'name="path" value="{allowed}"', body)
        self.assertIn(f'<img loading="lazy" src="/topics/file?{urllib.parse.urlencode({"path": allowed})}"', body)
        self.assertNotIn(f'value="{self.secret}"', body)  # 許可していない場所はただの文字
        self.assertIn(str(self.secret), body)
        self.assertIn('action="/topics/send"', body)
        self.assertIsNone(dash.page_topic("tok", "nobody"))

    def test_send_refuses_dialog(self):
        self.assertEqual(dash.topic_send("repo.task", "続けて\nください"), "sent")
        self.assertEqual(self.sent, [("%9", "続けて ください")])
        self.pane = "Do you want to make this edit?\n"
        self.assertEqual(dash.topic_send("repo.task", "x"), "dialog")
        _, body = dash.page_topic("tok", "repo.task")
        self.assertIn("許可待ち。window へ移ってください", body)
        self.assertNotIn('action="/topics/send"', body)
        self.assertEqual(dash.topic_send("repo.task", "  "), "empty")
        self.assertEqual(dash.topic_send("other.task", "x"), "nowindow")
        self.assertEqual(len(self.sent), 1)

    def test_switch_and_open(self):
        self.assertEqual(dash.topic_switch("repo.task"), "switched")
        self.assertEqual(self.ran, [["tmux", "select-window", "-t", "@7"], ["tmux", "switch-client", "-t", "@7"]])
        self.ran.clear()
        self.assertEqual(dash.open_path(str(self.secret)), "badpath")
        self.assertEqual(dash.open_path(str(self.out / ".." / "secret.png")), "badpath")
        self.assertEqual(self.ran, [])
        self.assertEqual(dash.open_path(str(self.out)), "opened")
        self.assertEqual(len(self.ran), 1)
        self.assertIsNone(dash.read_image(str(self.secret)))
        self.assertEqual(dash.read_image(str(self.out / "after-1.png")), (b"\x89PNG", "image/png"))


class TopicsServerTest(TopicsMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        old = (dash.Handler.allowed_hosts, dash.Handler.token)
        dash.Handler.allowed_hosts = {f"127.0.0.1:{self.port}"}
        dash.Handler.token = "t" * 43
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

        def restore():
            self.server.shutdown()
            self.server.server_close()
            dash.Handler.allowed_hosts, dash.Handler.token = old

        self.addCleanup(restore)

    def request(self, path, fields=None, headers=None):
        h = {"Origin": self.origin, "Content-Type": "application/x-www-form-urlencoded"} | (headers or {})
        data = urllib.parse.urlencode(fields).encode() if fields is not None else None

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        req = urllib.request.Request(self.origin + path, data=data, headers=h, method="POST" if data else "GET")
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as res:
                return res.status, res.headers.get("Location"), res.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            e.close()
            return e.code, e.headers.get("Location"), body

    def test_posts_require_token_and_origin(self):
        ok = {"token": "t" * 43, "name": "repo.task", "text": "x", "path": str(self.out)}
        for route in ("/topics/send", "/topics/switch", "/topics/open"):
            with self.subTest(route=route):
                self.assertEqual(self.request(route, dict(ok, token="bad"))[0], 403)
                self.assertEqual(self.request(route, ok, {"Origin": "http://evil.example"})[0], 403)
                self.assertEqual(self.request(route, ok, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual((self.sent, self.ran), ([], []))
        self.assertEqual(self.request("/topics/send", ok)[:2], (303, "/topic?name=repo.task&r=sent"))
        self.assertEqual(self.request("/topics/switch", dict(ok, back="list"))[:2], (303, "/topics?r=switched"))
        self.assertEqual(self.request("/topics/open", dict(ok, path=str(self.secret)))[:2],
                         (303, "/topic?name=repo.task&r=badpath"))
        self.assertEqual(len(self.sent), 1)

    def test_pages_and_images(self):
        status, _, body = self.request("/topics")
        self.assertEqual(status, 200)
        self.assertIn("新しい返答あり", body.decode())
        self.assertIn('href="/topics" class="active"', body.decode())
        status, _, body = self.request("/topic?name=repo.task", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 200)
        self.assertTrue(self.topic().unread)  # ほかのサイトからでは既読にしない
        self.request("/topic?name=repo.task", headers={"X-Partial": "1"})
        self.assertFalse(self.topic().unread)
        q = urllib.parse.urlencode({"path": str(self.out / "after-1.png")})
        status, _, body = self.request("/topics/file?" + q)
        self.assertEqual((status, body), (200, b"\x89PNG"))
        self.assertEqual(self.request("/topics/file?" + q, headers={"Sec-Fetch-Site": "cross-site"})[0], 404)
        self.assertEqual(self.request("/topics/file?" + urllib.parse.urlencode({"path": str(self.secret)}))[0], 404)
        self.assertEqual(self.request("/topic?name=nobody")[0], 404)


if __name__ == "__main__":
    unittest.main()
