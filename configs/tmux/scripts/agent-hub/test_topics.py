"""topics.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_topics.py"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics  # noqa: E402


def line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"


def user(content, ts="2026-01-02T01:00:00Z", **kw):
    return line({"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}, **kw})


def assistant(blocks, ts="2026-01-02T01:00:05Z", **kw):
    return line({"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": blocks}, **kw})


TRANSCRIPT = "".join([
    line({"type": "agent-name", "agentName": "repo.task", "sessionId": "s1"}),
    user("最初の指示", origin={"kind": "human"}),
    assistant([{"type": "thinking", "thinking": "考え中"}]),
    assistant([{"type": "text", "text": "調べます"}]),
    assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls /tmp"}}]),
    user([{"type": "tool_result", "tool_use_id": "t1", "content": "a\nb"}]),
    assistant([{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/x"}}]),
    user([{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "無い"}], "is_error": True}]),
    user("<task-notification>\n<summary>終わった</summary>\n</task-notification>", origin={"kind": "task-notification"}),
    user("Skill の本文", isMeta=True),
    user("要約", isCompactSummary=True),
    assistant([{"type": "text", "text": "サブエージェントの発言"}], isSidechain=True),
    user(
        'Another Claude session sent a message:\n<cross-session-message from="uds:x" from-name="hub">\n続けてください\n</cross-session-message>\n\nThis came from...',
        ts="2026-01-02T01:01:00Z",
        origin={"kind": "peer", "name": "hub"},
    ),
    user("<command-name>/clear</command-name>", origin={"kind": "human"}),
    assistant([{"type": "text", "text": "## 終わりました\n\n結果は /tmp/a.png"}], ts="2026-01-02T01:02:00Z"),
    user([{"type": "text", "text": "[Request interrupted by user]"}]),
])


def parse(text: str) -> topics.Transcript:
    t = topics.Transcript()
    topics.feed_bytes(t, text.encode())
    return t


class TranscriptTest(unittest.TestCase):
    def test_kinds(self):
        t = parse(TRANSCRIPT)
        got = [(e.kind, e.text) for e in t.entries]
        self.assertEqual(got, [
            ("user", "最初の指示"),
            ("assistant", "調べます"),
            ("tools", ""),
            ("note", "ここまでの会話を要約して、続きを始めた"),
            ("peer", "続けてください"),
            ("note", "コマンド /clear"),
            ("assistant", "## 終わりました\n\n結果は /tmp/a.png"),
            ("note", "ユーザーが中断した"),
        ])
        self.assertEqual(t.entries[4].sender, "hub")

    def test_consecutive_tools_are_grouped_with_results(self):
        tools = parse(TRANSCRIPT).entries[2].tools
        self.assertEqual([(c.name, c.summary, c.done, c.error) for c in tools],
                         [("Bash", "ls /tmp", True, False), ("Read", "/x", True, True)])
        self.assertEqual(tools[1].result, "無い")

    def test_times(self):
        t = parse(TRANSCRIPT)
        self.assertEqual(t.last_reply_ts, topics.parse_ts("2026-01-02T01:02:00Z"))
        self.assertGreaterEqual(t.last_ts, t.last_reply_ts)
        self.assertEqual(t.last_message().kind, "assistant")

    def test_pending_question_is_waiting_input(self):
        ask = assistant([{"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
                          "input": {"questions": [{"question": "A と B のどちら？"}]}}])
        t = parse(TRANSCRIPT + ask)
        self.assertTrue(t.waiting_input)
        self.assertEqual(t.entries[-1].tools[0].summary, "A と B のどちら？")
        topics.feed_bytes(t, user([{"type": "tool_result", "tool_use_id": "q1", "content": "A"}]).encode())
        self.assertFalse(t.waiting_input)

    def test_broken_lines_are_skipped(self):
        t = parse('{"type":"user", broken\n' + TRANSCRIPT)
        self.assertEqual(t.entries[0].text, "最初の指示")


class TranscriptCacheTest(unittest.TestCase):
    def test_reads_only_appended_complete_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.jsonl"
            first = user("一つ目", origin={"kind": "human"})
            second = assistant([{"type": "text", "text": "二つ目"}])
            path.write_text(first + second[:10], encoding="utf-8")
            cache = topics.TranscriptCache()
            t = cache.get(path)
            self.assertEqual([e.text for e in t.entries], ["一つ目"])
            with path.open("a", encoding="utf-8") as f:
                f.write(second[10:])
            self.assertIs(cache.get(path), t)
            self.assertEqual([e.text for e in t.entries], ["一つ目", "二つ目"])
            # 書き直されて短くなったら読み直す
            path.write_text(first, encoding="utf-8")
            self.assertEqual([e.text for e in cache.get(path).entries], ["一つ目"])
            path.unlink()
            self.assertIsNone(cache.get(path))


class LocateTest(unittest.TestCase):
    def test_project_dir(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/c"}):
            self.assertEqual(topics.project_dir("/Users/a/repo.worktrees/agent/x_y"),
                             Path("/c/projects/-Users-a-repo-worktrees-agent-x-y"))

    def test_find_agent_prefers_pane_descendant(self):
        agents = [
            {"pid": 10, "name": "hub", "cwd": "/h", "sessionId": "a"},
            {"pid": 20, "name": "hub", "cwd": "/h", "sessionId": "b"},
        ]
        parents = topics.parse_ps("  10   1\n  20  15\n  15   5\n")
        self.assertEqual(topics.find_agent("hub", "/h", 5, agents, parents)["sessionId"], "b")
        # pane が分からなければ、同じ名前が 2 つある時は決めない
        self.assertIsNone(topics.find_agent("hub", "/h", None, agents, parents))
        self.assertEqual(topics.find_agent("hub", "/h", None, agents[:1], parents)["sessionId"], "a")
        self.assertIsNone(topics.find_agent("hub", "/other", None, agents[:1], parents))

    def test_agent_transcript_rejects_odd_session_ids(self):
        self.assertIsNone(topics.agent_transcript({"sessionId": "../x", "cwd": "/h"}))
        self.assertTrue(str(topics.agent_transcript({"sessionId": "ab-12", "cwd": "/h"})).endswith("-h/ab-12.jsonl"))

    def test_fallback_picks_newest_with_same_name(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": d}):
            pdir = topics.project_dir("/w")
            pdir.mkdir(parents=True)
            for i, name in enumerate(["repo.task", "repo.task", "other"]):
                p = pdir / f"s{i}.jsonl"
                p.write_text(line({"type": "agent-name", "agentName": name}), encoding="utf-8")
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual(topics.fallback_transcript("repo.task", "/w").name, "s1.jsonl")
            self.assertIsNone(topics.fallback_transcript("none", "/w"))
            self.assertIsNone(topics.fallback_transcript("repo.task", ""))


class StateTest(unittest.TestCase):
    def test_priority(self):
        base = dict(dialog=False, asking=False, open_reports=0, unread=False, busy=False)
        self.assertEqual(topics.topic_state(**base), "idle")
        self.assertEqual(topics.topic_state(**base | {"busy": True}), "busy")
        self.assertEqual(topics.topic_state(**base | {"busy": True, "unread": True}), "unread")
        for key, value in (("dialog", True), ("asking", True), ("open_reports", 1)):
            self.assertEqual(topics.topic_state(**base | {"unread": True, key: value}), "waiting")

    def test_seen_store(self):
        with tempfile.TemporaryDirectory() as d:
            store = topics.SeenStore(Path(d) / "dash" / "seen.json")
            self.assertEqual(store.load(), {})
            store.mark("a", 100.0)
            store.mark("a", 50.0)  # 戻さない
            store.mark("b", 7.0)
            self.assertEqual(topics.SeenStore(store.path).load(), {"a": 100.0, "b": 7.0})
            store.path.write_text("壊れた", encoding="utf-8")
            self.assertEqual(store.load(), {})

    def test_first_line(self):
        self.assertEqual(topics.first_line("\n## **見出し** と `code`\n本文"), "見出し と code")
        self.assertEqual(topics.first_line("あ" * 200, 10), "あ" * 9 + "…")


class PathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = base / "allowed"
        (self.root / "sub").mkdir(parents=True)
        (self.root / "sub" / "a.png").write_bytes(b"png")
        (base / "secret.txt").write_text("x")
        (self.root / "link").symlink_to(base / "secret.txt")
        self.base = base
        self.roots = [self.root]

    def test_only_existing_paths_under_roots(self):
        ok = topics.resolve_allowed
        self.assertEqual(ok(str(self.root / "sub" / "a.png"), self.roots), self.root / "sub" / "a.png")
        self.assertEqual(ok(str(self.root / "sub") + ".", self.roots), self.root / "sub")
        self.assertIsNone(ok(str(self.base / "secret.txt"), self.roots))
        self.assertIsNone(ok(str(self.root / ".." / "secret.txt"), self.roots))
        self.assertIsNone(ok(str(self.root / "link"), self.roots))  # symlink で外へ出る
        self.assertIsNone(ok(str(self.root / "none.png"), self.roots))
        self.assertIsNone(ok("allowed/sub", self.roots))
        self.assertIsNone(ok(str(self.root) + "\x00", self.roots))

    def test_allowed_roots(self):
        with mock.patch.dict(os.environ, {"AGENT_HUB_OPEN_DIRS": f"{self.root}:/nonexistent:/"}):
            roots = topics.allowed_roots(self.base / "missing-hub")
        self.assertIn(self.root, roots)
        self.assertIn(Path("/tmp").resolve(), roots)
        self.assertNotIn(Path("/"), roots)  # ルートそのものは許さない

    def test_find_paths(self):
        text = "撮った /tmp/pr-captures/after-1.png と ~/hub/notes/a.md。URL https://example.com/tmp/x は除く"
        self.assertEqual(topics.find_paths(text), ["/tmp/pr-captures/after-1.png", "~/hub/notes/a.md"])

    def test_open_command(self):
        f = self.root / "sub" / "a.png"
        self.assertEqual(topics.open_command(f, "darwin"), ["open", "-R", str(f)])
        self.assertEqual(topics.open_command(f.parent, "darwin"), ["open", str(f.parent)])
        self.assertEqual(topics.open_command(f, "linux"), ["xdg-open", str(f.parent)])


if __name__ == "__main__":
    unittest.main()
