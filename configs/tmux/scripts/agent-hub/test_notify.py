"""notify.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_notify.py

GitHub には問い合わせない。GraphQL の node を手で組み立てるか、gh を偽のスクリプトに差し替える。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify  # noqa: E402
import prs  # noqa: E402
from test_prs import ME, request_pr, user, bot  # noqa: E402

CFG = dict(prs.DEFAULTS, bots=["ci-user"])


def rollup(conclusion):
    return {"state": "FAILURE" if conclusion == "FAILURE" else "SUCCESS", "contexts": {
        "pageInfo": {"hasNextPage": False},
        "nodes": [{"__typename": "CheckRun", "name": "test", "status": "COMPLETED", "conclusion": conclusion,
                   "startedAt": "2026-01-09T00:00:00Z", "completedAt": "2026-01-09T00:05:00Z"}],
    }}


def own(reviews=(), comments=(), ci="SUCCESS", **kw):
    pr = {
        "id": "PR_2", "number": 2, "title": "直す", "url": "https://github.com/o/r/pull/2", "isDraft": False,
        "headRefOid": "h2", "repository": {"nameWithOwner": "o/r"},
        "reviews": {"nodes": list(reviews)}, "comments": {"nodes": list(comments)},
        "commits": {"nodes": [{"commit": {"oid": "h2", "statusCheckRollup": rollup(ci)}}]},
    }
    pr.update(kw)
    return pr


def text(id, author, body="", **kw):
    return {"id": id, "url": f"https://github.com/o/r/pull/2#{id}", "body": body, "author": author, **kw}


def mention_item(comments=(), reviews=None, **kw):
    item = {"id": "I_9", "url": "https://github.com/o/r/issues/9", "body": "", "author": user("alice"),
            "number": 9, "title": "相談", "repository": {"nameWithOwner": "o/r"}, "comments": {"nodes": list(comments)}}
    if reviews is not None:
        item["reviews"] = {"nodes": reviews}
    item.update(kw)
    return item


class EventsTest(unittest.TestCase):
    def test_own_pr_reviews_and_comments_by_people_only(self):
        pr = own(
            reviews=[text("R1", user("alice"), state="CHANGES_REQUESTED"), text("R2", user(ME), state="COMMENTED"),
                     text("R3", bot("renovate"), state="COMMENTED"), text("R4", user("bob"), state="PENDING")],
            comments=[text("C1", user("ci-user")), text("C2", user("bob")), text("C3", user(ME))],
        )
        events = notify.own_events([pr], ME, CFG)
        self.assertEqual([(e.kind, e.key) for e in events], [("review", "c:R1"), ("comment", "c:C2")])
        self.assertEqual(events[0].url, "https://github.com/o/r/pull/2#R1")

    def test_ci_failure_once_per_head(self):
        self.assertEqual(notify.own_events([own()], ME, CFG), [])
        [e] = notify.own_events([own(ci="FAILURE")], ME, CFG)
        self.assertEqual((e.kind, e.key, e.url), ("ci_failed", "ci:PR_2@h2", "https://github.com/o/r/pull/2/checks"))

    def test_scope(self):
        cfg = dict(CFG, exclude_repos=["o/r"])
        self.assertEqual(notify.own_events([own(ci="FAILURE")], ME, cfg), [])
        self.assertEqual(notify.mention_events([mention_item(body=f"@{ME} 見て")], ME, cfg), [])
        self.assertEqual(notify.request_events([request_pr()], ME, cfg), [])

    def test_review_request_uses_prs_rules_and_rerequest_is_new(self):
        [e] = notify.request_events([request_pr()], ME, CFG)
        self.assertEqual((e.kind, e.number, e.key), ("review_requested", 1, "rr:PR_1@2026-01-08T00:00:00Z"))
        # bot の依頼と draft は数えない
        by_bot = request_pr(timelineItems={"nodes": [
            {"createdAt": "2026-01-08T00:00:00Z", "actor": bot("x"), "requestedReviewer": user(ME)}]})
        self.assertEqual(notify.request_events([by_bot, request_pr(isDraft=True)], ME, CFG), [])
        again = request_pr(timelineItems={"nodes": [
            {"createdAt": "2026-01-08T00:00:00Z", "actor": user("alice"), "requestedReviewer": user(ME)},
            {"createdAt": "2026-01-09T00:00:00Z", "actor": user("alice"), "requestedReviewer": user(ME)}]})
        self.assertEqual(notify.request_events([again], ME, CFG)[0].key, "rr:PR_1@2026-01-09T00:00:00Z")

    def test_mentions(self):
        item = mention_item(
            body=f"@{ME} の件",
            comments=[text("C1", user("bob"), f"cc @{ME.upper()}"), text("C2", user("bob"), f"@{ME}-team へ"),
                      text("C3", user(ME), f"@{ME}"), text("C4", bot("b"), f"@{ME}"), text("C5", user("bob"), f"`a@{ME}`")],
            reviews=[text("R1", user("bob"), "", comments={"nodes": [text("RC1", user("carol"), f"@{ME} ここ")]})],
        )
        keys = [e.key for e in notify.mention_events([item], ME, CFG)]
        self.assertEqual(keys, ["c:I_9", "c:C1", "c:RC1"])

    def test_new_events_dedupes_keys_and_lines(self):
        e = notify.Event
        events = [
            e("comment", "o/r", 2, "t", "u1", "c:C1"),
            e("mention", "o/r", 2, "t", "u1", "c:C1"),  # 同じコメントは mention にする
            e("review", "o/r", 2, "t", "u2", "c:R1"),
            e("review", "o/r", 2, "t", "u3", "c:R2"),  # 同じ PR の review は 1 行
            e("ci_failed", "o/r", 2, "t", "u4", "ci:old"),
        ]
        fresh, keys = notify.new_events(events, {"ci:old"})
        self.assertEqual([(x.kind, x.url) for x in fresh], [("review", "u2"), ("mention", "u1")])
        self.assertEqual(sorted(keys), ["c:C1", "c:R1", "c:R2"])

    def test_line(self):
        ev = notify.Event("mention", "o/r", 9, "a\tb\n c", "https://x", "k")
        self.assertEqual(ev.line(), "mention\to/r\t9\ta b c\thttps://x")


class FakeSource:
    def __init__(self, rounds, fail=()):
        self.rounds, self.fail, self.calls = list(rounds), list(fail), 0

    def viewer(self):
        return ME

    def review_requested(self, me):
        self.calls += 1
        if self.fail:
            raise RuntimeError(self.fail.pop(0))
        self.current = self.rounds.pop(0) if self.rounds else self.current
        return []

    def own_activity(self):
        return self.current

    def mentions(self):
        return []


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state" / "notify-seen.txt"
        self.now, self.sleeps = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def watch(self, gh, **kw):
        return notify.watch(gh, dict(CFG, notify_max_minutes=10), self.path, sleep=self.sleep, clock=self.clock, **kw)

    def test_first_run_records_then_reports_only_new(self):
        old = own(reviews=[text("R1", user("alice"), state="APPROVED")])
        new = own(reviews=[text("R1", user("alice"), state="APPROVED"), text("R2", user("bob"), state="COMMENTED")])
        events = self.watch(FakeSource([[old], [old], [new]]))
        self.assertEqual([e.key for e in events], ["c:R2"])
        self.assertEqual(self.sleeps, [60, 60])
        self.assertEqual(self.path.read_text().split(), ["c:R1", "c:R2"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        # 同じものはもう出さない
        self.assertEqual(self.watch(FakeSource([[new]]), once=True), [])

    def test_times_out_with_nothing(self):
        self.assertEqual(self.watch(FakeSource([[]])), [])
        self.assertEqual(sum(self.sleeps), 600 - 60)

    def test_transient_errors_back_off_and_fatal_errors_stop(self):
        gh = FakeSource([[own(ci="FAILURE")]], fail=["HTTP 502", "HTTP 502"])
        self.path.parent.mkdir()
        self.path.write_text("")
        self.assertEqual([e.kind for e in self.watch(gh)], ["ci_failed"])
        self.assertEqual(self.sleeps, [60, 120])
        with self.assertRaisesRegex(notify.Fatal, "3 回続けて失敗: HTTP 401"):
            self.watch(FakeSource([], fail=["HTTP 401"] * 3))
        with self.assertRaisesRegex(notify.Fatal, "HTTP 502"):
            self.watch(FakeSource([], fail=["HTTP 502"]), once=True)


class MainTest(unittest.TestCase):
    """偽の gh で main を動かし、gh を graphql で読むだけで呼ぶこと、出力と終了コードを確かめる。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.log, self.gh, self.cfg = root / "calls.jsonl", root / "gh", root / "prs.json"
        self.own_file = root / "own.json"
        self.own_file.write_text("[]")
        self.gh.write_text(f"""#!{sys.executable}
import json, sys
body = json.load(sys.stdin)
with open({str(self.log)!r}, "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
q, v = body["query"], body["variables"]
if q.startswith("query{{viewer"):
    data = {{"viewer": {{"login": {ME!r}}}}}
elif "author:@me" in v.get("q", ""):
    data = {{"search": {{"pageInfo": {{"hasNextPage": False}}, "nodes": json.load(open({str(self.own_file)!r}))}}}}
else:
    data = {{"search": {{"pageInfo": {{"hasNextPage": False}}, "nodes": []}}}}
print(json.dumps({{"data": data}}))
""")
        self.gh.chmod(0o755)
        self.cfg.write_text(json.dumps({"gh": str(self.gh)}))

    def run_notify(self, *args):
        env = dict(os.environ, AGENT_HUB_PRS_CONFIG=str(self.cfg))
        env.pop("AGENT_HUB_GH", None)
        return subprocess.run([sys.executable, notify.__file__, "--once", "--state", self.tmp.name, *args],
                              env=env, capture_output=True, text=True)

    def test_first_run_then_event(self):
        res = self.run_notify()
        self.assertEqual((res.returncode, res.stdout), (1, ""))
        self.assertIn("初回", res.stderr)
        self.own_file.write_text(json.dumps([own(ci="FAILURE")]))
        res = self.run_notify()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "ci_failed\to/r\t2\t直す\thttps://github.com/o/r/pull/2/checks\n")
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertTrue(calls and all(c == ["api", "graphql", "--input", "-"] for c in calls))

    def test_config_error_exits_2(self):
        self.cfg.write_text(json.dumps({"notify_interval_s": 0}))
        res = self.run_notify()
        self.assertEqual(res.returncode, 2)
        self.assertIn("notify_interval_s", res.stderr)

    def test_auth_error_exits_2(self):
        self.gh.write_text("#!/bin/sh\necho 'HTTP 401: Bad credentials' >&2\nexit 1\n")
        res = self.run_notify()
        self.assertEqual(res.returncode, 2)
        self.assertIn("HTTP 401", res.stderr)


if __name__ == "__main__":
    unittest.main()
