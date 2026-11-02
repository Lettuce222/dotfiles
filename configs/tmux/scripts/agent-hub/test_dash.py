"""dash.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_dash.py"""

import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
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


class ServerTest(unittest.TestCase):
    def test_rejects_foreign_host(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        port = server.server_address[1]
        dash.Handler.allowed_hosts = {f"127.0.0.1:{port}"}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/app.css", headers={"Host": "evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/app.css", timeout=5) as res:
                self.assertEqual(res.status, 200)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
