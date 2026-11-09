"""agents-watch スキルの watch.py のテスト。

実行: python3 -m unittest configs/agent/tests/test_agents_watch.py

判定の関数と、seen の記録だけを確かめる。gh は呼ばない（github_events は差し替える）。
"""

import datetime as dt
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "agents-watch" / "scripts" / "watch.py"

spec = importlib.util.spec_from_file_location("watch", SCRIPT)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

ME = "me"
NOW = dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def pr(url="https://github.com/o/r/pull/1", head="h1", **extra):
    base = {
        "number": 1,
        "title": "T",
        "url": url,
        "isDraft": False,
        "headRefOid": head,
        "repository": {"nameWithOwner": "o/r"},
        "reviewRequests": {"nodes": []},
        "latestReviews": {"nodes": []},
        "comments": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
    }
    base.update(extra)
    return base


def request(login, typename="User", code_owner=False):
    return {"asCodeOwner": code_owner, "requestedReviewer": {"__typename": typename, "login": login}}


def comment(cid, login, at="2026-11-05T00:00:00Z"):
    return {"id": cid, "url": f"https://github.com/o/r/pull/1#{cid}", "createdAt": at, "author": {"login": login}}


class ReviewRequestTest(unittest.TestCase):
    def test_named_request_only(self):
        prs = [
            pr(url="u1", reviewRequests={"nodes": [request(ME)]}),
            pr(url="u2", reviewRequests={"nodes": [request(ME, code_owner=True)]}),
            pr(url="u3", reviewRequests={"nodes": [{"asCodeOwner": False, "requestedReviewer": {"__typename": "Team"}}]}),
            pr(url="u4", reviewRequests={"nodes": [request("other")]}),
            pr(url="u5", isDraft=True, reviewRequests={"nodes": [request(ME)]}),
        ]
        events = watch.review_request_events(prs, ME)
        self.assertEqual([e["url"] for e in events], ["u1"])
        self.assertEqual(events[0]["key"], "review_request:u1@h1")

    def test_new_head_is_a_new_event(self):
        a = watch.review_request_events([pr(reviewRequests={"nodes": [request(ME)]})], ME)
        b = watch.review_request_events([pr(head="h2", reviewRequests={"nodes": [request(ME)]})], ME)
        self.assertNotEqual(a[0]["key"], b[0]["key"])


class OwnPrTest(unittest.TestCase):
    def test_ci_failed(self):
        p = pr(commits={"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]})
        kinds = [e["kind"] for e in watch.own_pr_events([p], ME, [])]
        self.assertEqual(kinds, ["ci_failed"])

    def test_no_rollup(self):
        p = pr(commits={"nodes": [{"commit": {"statusCheckRollup": None}}]})
        self.assertEqual(watch.own_pr_events([p], ME, []), [])

    def test_changes_requested(self):
        p = pr(latestReviews={"nodes": [
            {"author": {"login": "rev"}, "state": "CHANGES_REQUESTED", "submittedAt": "t1", "url": "x"},
            {"author": {"login": "ok"}, "state": "APPROVED", "submittedAt": "t1", "url": "y"},
        ]})
        events = watch.own_pr_events([p], ME, [])
        self.assertEqual([(e["kind"], e["note"]) for e in events], [("changes_requested", "rev")])

    def test_comments_grouped_and_filtered(self):
        p = pr(
            comments={"nodes": [comment("c1", "alice", "2026-11-05T01:00:00Z"), comment("c2", ME)]},
            reviewThreads={"nodes": [{"comments": {"nodes": [comment("c3", "bob", "2026-11-05T02:00:00Z"), comment("c4", "ci-bot")]}}]},
        )
        events = watch.own_pr_events([p], ME, ["ci-bot"])
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["kind"], "comment")
        self.assertEqual(e["keys"], ["comment:c1", "comment:c3"])
        self.assertEqual(e["note"], "alice, bob")
        self.assertTrue(e["url"].endswith("#c3"))


class UnseenTest(unittest.TestCase):
    def test_filters_seen_keys(self):
        events = [
            {"key": "a"},
            {"key": "c1", "keys": ["c1", "c2"]},
            {"key": "c3", "keys": ["c3"]},
        ]
        out = watch.unseen(events, {"a", "c1", "c3"})
        self.assertEqual(out, [{"key": "c2", "keys": ["c2"]}])


class HoursTest(unittest.TestCase):
    def test_work_hours(self):
        cfg = dict(watch.DEFAULTS)
        self.assertTrue(watch.in_work_hours(NOW, cfg))  # 木曜 10 時
        self.assertFalse(watch.in_work_hours(NOW.replace(hour=19), cfg))
        self.assertFalse(watch.in_work_hours(NOW.replace(day=7), cfg))  # 土曜


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"AGENT_WATCH_STATE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_main(self, argv, events=None, stdin=None):
        buf = io.StringIO()
        with mock.patch.object(watch, "github_events", return_value=events or []), redirect_stdout(buf):
            rc = watch.main(argv, now=NOW, stdin=stdin)
        return rc, [json.loads(line) for line in buf.getvalue().splitlines()]

    def test_first_run_hides_comments_then_only_new(self):
        events = [
            {"source": "github", "kind": "review_request", "key": "r1", "url": "u", "title": "t"},
            {"source": "github", "kind": "comment", "key": "c1", "keys": ["c1"], "url": "u", "title": "t"},
        ]
        rc, out = self.run_main(["prs"], events)
        self.assertEqual(rc, 0)
        self.assertEqual([e["key"] for e in out], ["r1"])
        self.assertEqual(set((self.dir / "seen.txt").read_text().split()), {"r1", "c1"})

        events.append({"source": "github", "kind": "comment", "key": "c2", "keys": ["c1", "c2"], "url": "u", "title": "t"})
        rc, out = self.run_main(["prs"], events)
        self.assertEqual([e["keys"] for e in out], [["c2"]])
        logged = [json.loads(l) for l in (self.dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["key"] for e in logged], ["r1", "c2"])
        self.assertEqual(logged[0]["at"], NOW.isoformat(timespec="seconds"))

    def test_dry_run_records_nothing(self):
        self.run_main(["prs", "--dry-run"], [{"kind": "ci_failed", "key": "x", "url": "u", "title": "t"}])
        self.assertFalse((self.dir / "seen.txt").exists())

    def test_seen_for_slack(self):
        lines = '{"key": "slack:C1/1.0", "url": "p1", "title": "要点"}\n{"key": "slack:C1/2.0", "url": "p2", "title": "要点"}\n'
        rc, out = self.run_main(["seen", "slack"], stdin=io.StringIO(lines))
        self.assertEqual(rc, 0)
        self.assertEqual([e["source"] for e in out], ["slack", "slack"])
        rc, out = self.run_main(["seen", "slack"], stdin=io.StringIO(lines))
        self.assertEqual(out, [])

    def test_seen_rejects_line_without_key(self):
        rc, _ = self.run_main(["seen", "slack"], stdin=io.StringIO('{"url": "p"}\n'))
        self.assertEqual(rc, 2)

    def test_hours_exit_code(self):
        rc, _ = self.run_main(["hours"])
        self.assertEqual(rc, 0)


class HeartbeatTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"AGENT_WATCH_STATE": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stale_output(self, now):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(watch.main(["stale"], now=now), 0)
        return out.getvalue()

    def test_hours_writes_heartbeat_even_outside_work_hours(self):
        night = NOW.replace(hour=23)
        self.assertEqual(watch.main(["hours"], now=night), 1)
        self.assertEqual(watch.read_heartbeat(watch.state_dir()), night)

    def test_recent_heartbeat_is_not_stale(self):
        watch.main(["hours"], now=NOW)
        self.assertEqual(self.stale_output(NOW + dt.timedelta(minutes=59)), "")

    def test_old_heartbeat_is_stale_in_work_hours(self):
        watch.main(["hours"], now=NOW)
        self.assertIn("見張り", self.stale_output(NOW + dt.timedelta(minutes=61)))

    def test_missing_heartbeat_is_stale_in_work_hours(self):
        self.assertIn("記録なし", self.stale_output(NOW))

    def test_not_stale_outside_work_hours(self):
        self.assertEqual(self.stale_output(NOW.replace(hour=23)), "")


class SkillFrontmatterTest(unittest.TestCase):
    def test_model_can_invoke_the_skill(self):
        # /loop の cron の発火は、モデルが Skill ツールで読み込むことがある。
        # disable-model-invocation を付けると拒否され、見張りが空振りする。
        text = (SCRIPT.parents[1] / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        self.assertNotIn("disable-model-invocation", frontmatter)


if __name__ == "__main__":
    unittest.main()
