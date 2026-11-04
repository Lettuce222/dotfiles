"""dash.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_dash.py"""

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
        (item,) = dash.parse_gtd("- [ ] 作業 worker:: repo.task\n", "waiting-for")
        self.assertTrue(item.doing)
        (item,) = dash.parse_gtd("- [ ] 作業 doing:: 2026-01-01\n", "next-actions")
        self.assertTrue(item.doing)
        (item,) = dash.parse_gtd("- [x] 作業 worker:: repo.task\n", "done")
        self.assertFalse(item.doing)

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


class AnswerTest(StateDirMixin, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
