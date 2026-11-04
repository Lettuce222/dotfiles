"""prs.py のテスト。実行: python3 -m unittest configs/tmux/scripts/agent-hub/test_prs.py

GitHub には問い合わせない。gh の出力の代わりに、GraphQL の node を手で組み立てて判定を確かめる。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prs  # noqa: E402

ME = "me"
NOW = prs.ts("2026-01-10T00:00:00Z")
HEAD = "h2"
CFG = dict(prs.DEFAULTS)


def user(name):
    return {"__typename": "User", "login": name}


def bot(name):
    return {"__typename": "Bot", "login": name}


def team(slug):
    return {"__typename": "Team", "slug": slug}


def request_pr(**kw):
    """自分宛てのレビュー依頼として数えられる PR。kw で一部を変える。"""
    pr = {
        "id": "PR_1",
        "number": 1,
        "title": "機能を足す",
        "url": "https://github.com/o/r/pull/1",
        "isDraft": False,
        "createdAt": "2026-01-05T00:00:00Z",
        "updatedAt": "2026-01-09T00:00:00Z",
        "headRefOid": HEAD,
        "additions": 10,
        "deletions": 5,
        "reviewDecision": "REVIEW_REQUIRED",
        "repository": {"nameWithOwner": "o/r"},
        "author": user("alice"),
        "reviewRequests": {"nodes": [{"asCodeOwner": False, "requestedReviewer": user(ME)}]},
        "reviews": {"nodes": []},
        "timelineItems": {
            "nodes": [{"createdAt": "2026-01-08T00:00:00Z", "actor": user("alice"), "requestedReviewer": user(ME)}]
        },
    }
    pr.update(kw)
    return pr


def own_pr(**kw):
    """自分の PR。既定では reviewer がおらず、CI は成功。"""
    pr = {
        "id": "PR_2",
        "number": 2,
        "title": "直す",
        "url": "https://github.com/o/r/pull/2",
        "isDraft": False,
        "createdAt": "2026-01-05T00:00:00Z",
        "updatedAt": "2026-01-09T00:00:00Z",
        "headRefOid": HEAD,
        "additions": 1,
        "deletions": 1,
        "reviewDecision": "REVIEW_REQUIRED",
        "repository": {"nameWithOwner": "o/r"},
        "author": user(ME),
        "reviewRequests": {"nodes": []},
        "latestReviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "timelineItems": {"nodes": []},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-01-07T00:00:00Z", "statusCheckRollup": {"state": "SUCCESS"}}}]},
    }
    pr.update(kw)
    return pr


def check_run(name, conclusion, started, status="COMPLETED", workflow="CI"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion,
            "startedAt": started, "completedAt": started if status == "COMPLETED" else None,
            "checkSuite": {"workflowRun": {"workflow": {"name": workflow}}}}


def status(context, state, created):
    return {"__typename": "StatusContext", "context": context, "state": state, "createdAt": created}


def review(who, state, commit=HEAD, author=None):
    return {"author": author or user(who), "state": state, "submittedAt": "2026-01-08T00:00:00Z", "commit": {"oid": commit}}


def thread(who, at, resolved=False, author=None):
    return {"isResolved": resolved, "comments": {"nodes": [{"author": author or user(who), "createdAt": at}]}}


def requested(who, at="2026-01-08T00:00:00Z"):
    return {"__typename": "ReviewRequestedEvent", "createdAt": at, "requestedReviewer": who}


class ReviewRequestTest(unittest.TestCase):
    def why(self, pr, cfg=CFG):
        return prs.review_request_why(pr, ME, cfg)

    def test_personal_request_from_a_person_counts(self):
        pr = request_pr()
        self.assertIsNone(self.why(pr))
        item = prs.review_request_item(pr, ME, CFG, NOW)
        self.assertEqual(item["key"], "o/r#1@h2")
        self.assertEqual(item["requested_by"], "alice")
        self.assertEqual(item["waiting_hours"], 48)
        self.assertEqual(item["size"], 15)
        self.assertTrue(item["only_blocker"])
        self.assertFalse(item["re_review"])
        self.assertFalse(item["stale"])

    def test_codeowners_and_team_requests_do_not_count(self):
        codeowner = request_pr(reviewRequests={"nodes": [{"asCodeOwner": True, "requestedReviewer": user(ME)}]})
        self.assertEqual(self.why(codeowner), "CODEOWNERS かチーム経由の依頼だけ")
        via_team = request_pr(reviewRequests={"nodes": [{"asCodeOwner": False, "requestedReviewer": team("t")}]})
        self.assertEqual(self.why(via_team), "CODEOWNERS かチーム経由の依頼だけ")

    def test_request_made_by_bot_or_app_does_not_count(self):
        for actor in (bot("auto-assign"), None):
            pr = request_pr(timelineItems={"nodes": [{"createdAt": "2026-01-08T00:00:00Z", "actor": actor, "requestedReviewer": user(ME)}]})
            self.assertEqual(self.why(pr), "人ではないアカウントの依頼")
        # GitHub 上は User でも、設定の bots に入っていれば人として扱わない
        pr = request_pr(timelineItems={"nodes": [{"createdAt": "2026-01-08T00:00:00Z", "actor": user("ci-user"), "requestedReviewer": user(ME)}]})
        self.assertEqual(self.why(pr, dict(CFG, bots=["ci-user"])), "人ではないアカウントの依頼")
        # 依頼の記録が timeline の窓に無ければ数えない
        self.assertEqual(self.why(request_pr(timelineItems={"nodes": []})), "人ではないアカウントの依頼")

    def test_latest_request_decides(self):
        events = [
            {"createdAt": "2026-01-06T00:00:00Z", "actor": bot("b"), "requestedReviewer": user(ME)},
            {"createdAt": "2026-01-07T00:00:00Z", "actor": user("alice"), "requestedReviewer": user("bob")},
            {"createdAt": "2026-01-08T00:00:00Z", "actor": user("alice"), "requestedReviewer": user(ME)},
        ]
        self.assertIsNone(self.why(request_pr(timelineItems={"nodes": events})))
        self.assertEqual(self.why(request_pr(timelineItems={"nodes": events[::-1]})), "人ではないアカウントの依頼")

    def test_draft_and_scope(self):
        self.assertEqual(self.why(request_pr(isDraft=True)), "draft")
        self.assertEqual(self.why(request_pr(), dict(CFG, orgs=["other"])), "対象外のリポジトリ")
        self.assertIsNone(self.why(request_pr(), dict(CFG, repos=["o/r"])))
        self.assertEqual(self.why(request_pr(), dict(CFG, exclude_repos=["o/r"])), "除外したリポジトリ")
        self.assertEqual(self.why(request_pr(), dict(CFG, exclude_orgs=["o"])), "除外したリポジトリ")
        self.assertEqual(self.why(request_pr(), dict(CFG, exclude_title_patterns=["^機能"])), "除外したタイトル")
        self.assertEqual(self.why(request_pr(), dict(CFG, ignore_authors=["alice"])), "無視する作者")

    def test_re_review_and_stale(self):
        pr = request_pr(reviews={"nodes": [{"state": "COMMENTED", "commit": {"oid": "h1"}}]}, updatedAt="2025-11-01T00:00:00Z")
        item = prs.review_request_item(pr, ME, CFG, NOW)
        self.assertTrue(item["re_review"])
        self.assertTrue(item["stale"])

    def test_only_blocker_needs_me_alone(self):
        pr = request_pr(reviewRequests={"nodes": [
            {"asCodeOwner": False, "requestedReviewer": user(ME)},
            {"asCodeOwner": False, "requestedReviewer": user("bob")},
        ]})
        self.assertFalse(prs.review_request_item(pr, ME, CFG, NOW)["only_blocker"])

    def test_rank(self):
        def item(**kw):
            base = {"stale": False, "only_blocker": False, "author_is_person": True, "waiting_hours": 1, "size": 1}
            return dict(base, **kw)

        items = [
            item(name="stale", stale=True, only_blocker=True, waiting_hours=999),
            item(name="bot", author_is_person=False, waiting_hours=99),
            item(name="old", waiting_hours=50),
            item(name="new", waiting_hours=5),
            item(name="blocker", only_blocker=True),
        ]
        self.assertEqual([i["name"] for i in prs.rank_requests(items)], ["blocker", "old", "new", "bot", "stale"])


class OwnPrTest(unittest.TestCase):
    def item(self, **kw):
        return prs.own_pr_item(own_pr(**kw), ME, CFG, NOW)

    def test_no_reviewer(self):
        item = self.item()
        self.assertEqual(item["states"], ["no_reviewer"])
        self.assertEqual(item["ci"], "success")
        # draft なら reviewer がいないのは普通なので挙げない
        self.assertEqual(self.item(isDraft=True)["states"], [])

    def test_waiting_with_elapsed_time(self):
        item = self.item(
            reviewRequests={"nodes": [{"asCodeOwner": False, "requestedReviewer": user("bob")},
                                      {"asCodeOwner": True, "requestedReviewer": team("core")}]},
            timelineItems={"nodes": [requested(user("bob"), "2026-01-09T12:00:00Z"), requested(team("core"), "2026-01-06T00:00:00Z")]},
        )
        self.assertEqual(item["states"], ["waiting"])
        self.assertEqual([(w["reviewer"], w["hours"]) for w in item["waiting"]], [("team:core", 96), ("bob", 12)])

    def test_waiting_falls_back_to_created_at(self):
        item = self.item(reviewRequests={"nodes": [{"asCodeOwner": False, "requestedReviewer": user("bob")}]})
        self.assertEqual(item["waiting"][0]["hours"], 120)

    def test_unanswered_thread_after_last_push(self):
        item = self.item(
            latestReviews={"nodes": [review("bob", "COMMENTED")]},
            reviewThreads={"nodes": [
                thread("bob", "2026-01-08T00:00:00Z"),  # 最後の push の後で、他人で終わっている
                thread("bob", "2026-01-06T00:00:00Z"),  # push より前
                thread(ME, "2026-01-08T00:00:00Z"),  # 自分が返している
                thread("bob", "2026-01-08T00:00:00Z", resolved=True),
            ]},
        )
        self.assertEqual(item["unanswered_threads"], 1)
        self.assertEqual(item["states"], ["unanswered"])

    def test_approval_on_older_head(self):
        item = self.item(latestReviews={"nodes": [review("bob", "APPROVED", commit="h1")]})
        self.assertEqual(item["states"], ["approval_stale"])
        self.assertEqual(item["stale_approvals"], ["bob"])
        # レビューが要らない、または承認が生きているなら古い承認とは言わない
        self.assertNotIn("approval_stale", self.item(reviewDecision="APPROVED", latestReviews={"nodes": [review("bob", "APPROVED", commit="h1")]})["states"])

    def test_dismissed_approval_and_rerequest(self):
        item = self.item(
            reviewRequests={"nodes": [{"asCodeOwner": False, "requestedReviewer": user("bob")}]},
            latestReviews={"nodes": [review("bob", "DISMISSED", commit="h1")]},
            timelineItems={"nodes": [
                requested(user("bob"), "2026-01-06T00:00:00Z"),
                {"__typename": "ReviewDismissedEvent", "createdAt": "2026-01-08T00:00:00Z", "previousReviewState": "APPROVED",
                 "review": {"author": {"login": "bob"}}},
            ]},
        )
        # 古い承認の人は、依頼し直されていてもレビュー待ちには数えない（重ねて挙げない）
        self.assertEqual(item["states"], ["approval_stale"])
        self.assertEqual(item["waiting"], [])

    def test_changes_requested_and_ci_failed(self):
        item = self.item(
            reviewDecision="CHANGES_REQUESTED",
            latestReviews={"nodes": [review("bob", "CHANGES_REQUESTED"), review("carol", "APPROVED")]},
            commits={"nodes": [{"commit": {"committedDate": "2026-01-07T00:00:00Z", "statusCheckRollup": {"state": "FAILURE"}}}]},
        )
        self.assertEqual(item["states"], ["ci_failed", "changes_requested"])
        self.assertEqual(item["changes_requested_by"], ["bob"])
        self.assertEqual(item["ci"], "failure")

    def test_approved(self):
        self.assertEqual(self.item(reviewDecision="APPROVED", latestReviews={"nodes": [review("bob", "APPROVED")]})["states"], ["approved"])
        # レビュー必須でないリポジトリでも、今の head に承認があれば承認済み
        item = self.item(reviewDecision=None, latestReviews={"nodes": [review("bob", "APPROVED")]})
        self.assertEqual(item["states"], ["approved"])
        self.assertEqual(item["approved_by"], ["bob"])

    def test_bot_reviews_are_not_people(self):
        item = self.item(latestReviews={"nodes": [review("ai", "APPROVED", author=bot("ai")), review(ME, "COMMENTED")]})
        self.assertEqual(item["states"], ["no_reviewer"])
        self.assertEqual(item["approved_by"], [])

    def test_no_ci(self):
        self.assertIsNone(self.item(commits={"nodes": [{"commit": {"committedDate": "2026-01-07T00:00:00Z", "statusCheckRollup": None}}]})["ci"])

    def ci(self, *nodes, state="FAILURE", more=False):
        rollup = {"state": state, "contexts": {"pageInfo": {"hasNextPage": more}, "nodes": list(nodes)}}
        return self.item(commits={"nodes": [{"commit": {"committedDate": "2026-01-07T00:00:00Z", "statusCheckRollup": rollup}}]})

    def test_ci_uses_the_latest_run_of_each_check(self):
        # 同じ名前のチェックが 4 回。古い 3 回は後の実行に置き換えられて CANCELLED、最後は SUCCESS。
        # rollup の state は FAILURE でも、GitHub の画面では成功なので失敗にしない
        runs = [check_run("build", "CANCELLED", f"2026-01-07T00:0{i}:00Z") for i in range(3)]
        runs.append(check_run("build", "SUCCESS", "2026-01-07T00:03:00Z"))
        others = [check_run("lint", "SUCCESS", "2026-01-07T00:00:00Z"), check_run("deploy", "SKIPPED", "2026-01-07T00:00:00Z"),
                  status("ci/legacy", "SUCCESS", "2026-01-07T00:00:00Z")]
        for nodes in (runs + others, runs[3:] + runs[:3] + others):  # 並び順によらない
            item = self.ci(*nodes)
            self.assertEqual(item["ci"], "success")
            self.assertNotIn("ci_failed", item["states"])

    def test_ci_failure_and_pending_of_the_latest_runs(self):
        old_ok = check_run("build", "SUCCESS", "2026-01-07T00:00:00Z")
        self.assertEqual(self.ci(old_ok, check_run("build", "CANCELLED", "2026-01-07T00:01:00Z"), state="SUCCESS")["ci"], "failure")
        self.assertEqual(self.ci(old_ok, check_run("build", None, "2026-01-07T00:01:00Z", status="IN_PROGRESS"))["ci"], "pending")
        self.assertEqual(self.ci(old_ok, check_run("build", None, None, status="QUEUED"))["ci"], "pending")
        self.assertEqual(self.ci(old_ok, status("ci/legacy", "ERROR", "2026-01-07T00:00:00Z"))["ci"], "failure")
        # 別のワークフローの同じ名前のジョブは、別のチェックとして見る
        self.assertEqual(self.ci(check_run("build", "FAILURE", "2026-01-07T00:00:00Z", workflow="Release"),
                                 check_run("build", "SUCCESS", "2026-01-07T00:05:00Z"))["ci"], "failure")
        self.assertEqual(self.ci(status("ci/legacy", "FAILURE", "2026-01-07T00:00:00Z"),
                                 status("ci/legacy", "SUCCESS", "2026-01-07T00:05:00Z"))["ci"], "success")

    def test_ci_falls_back_to_rollup_state(self):
        # contexts を取り切れないときは、一部だけで決めずに rollup の state を使う
        self.assertEqual(self.ci(check_run("build", "SUCCESS", "2026-01-07T00:00:00Z"), more=True)["ci"], "failure")
        self.assertEqual(self.ci(state="PENDING")["ci"], "pending")

    def test_rank(self):
        def item(name, states, **kw):
            return dict({"name": name, "states": states, "stale": False, "draft": False, "idle_days": 0}, **kw)

        items = [
            item("approved", ["approved"]),
            item("draft", ["ci_failed"], draft=True),
            item("waiting", ["waiting"]),
            item("ci", ["ci_failed", "waiting"]),
            item("stale", ["ci_failed"], stale=True),
            item("none", []),
        ]
        self.assertEqual([i["name"] for i in prs.rank_own(items)], ["ci", "waiting", "approved", "none", "draft", "stale"])


class FakeGitHub:
    def __init__(self, requests=(), own=()):
        self.requests, self.own_nodes = list(requests), list(own)

    def viewer(self):
        return ME

    def review_requested(self, me):
        return self.requests

    def own(self):
        return self.own_nodes

    def count(self, q):
        return 3


class CollectTest(unittest.TestCase):
    def test_collect_and_render(self):
        gh = FakeGitHub(
            requests=[request_pr(), request_pr(number=3, isDraft=True)],
            own=[own_pr(), own_pr(number=4, repository={"nameWithOwner": "x/y"})],
        )
        data = prs.collect(gh, dict(CFG, exclude_orgs=["x"]), NOW)
        self.assertEqual(data["viewer"], ME)
        self.assertEqual(data["team_requests"], 3)
        self.assertEqual([i["pr"] for i in data["review_requests"]], ["o/r#1"])
        self.assertEqual([i["pr"] for i in data["own_prs"]], ["o/r#2"])
        self.assertEqual(
            data["excluded"],
            [{"pr": "o/r#3", "list": "review_requests", "why": "draft"}, {"pr": "x/y#4", "list": "own_prs", "why": "除外したリポジトリ"}],
        )
        json.dumps(data, ensure_ascii=False)  # JSON にできる
        text = prs.render_text(data)
        self.assertIn("レビュー依頼（1、ほかにチーム宛て 3）", text)
        self.assertIn("o/r#2  直す  reviewer なし", text)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "prs.json"

    def test_missing_file_means_defaults(self):
        self.assertEqual(prs.load_config(self.path), prs.DEFAULTS)

    def test_rejects_bad_values(self):
        for raw in ('{"orgs": "o"}', '{"unknown": 1}', '{"exclude_title_patterns": ["("]}', "[]", "{"):
            self.path.write_text(raw)
            with self.assertRaises(prs.ConfigError, msg=raw):
                prs.load_config(self.path)

    def test_config_location_and_gh_path(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name}, clear=False):
            os.environ.pop("AGENT_HUB_PRS_CONFIG", None)
            self.assertEqual(prs.config_path(), Path(self.tmp.name) / "agent-hub" / "prs.json")
        with mock.patch.dict(os.environ, {"AGENT_HUB_PRS_CONFIG": str(self.path)}):
            self.assertEqual(prs.config_path(), self.path)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_HUB_GH", None)
            self.assertEqual(prs.gh_path({"gh": "/opt/gh"}), "/opt/gh")
            self.assertEqual(prs.gh_path({}), "gh")
        with mock.patch.dict(os.environ, {"AGENT_HUB_GH": "/env/gh"}):
            self.assertEqual(prs.gh_path({"gh": "/opt/gh"}), "/env/gh")


class GhTest(unittest.TestCase):
    """GitHub クラスが gh を `api graphql --input -` で呼び、ページを辿ること。gh は偽のスクリプトに差し替える。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.log = root / "calls.jsonl"
        self.gh = root / "gh"
        # 1 回目は次のページあり、2 回目で終わり。呼ばれた引数と入力を記録する
        self.gh.write_text(
            f"""#!{sys.executable}
import json, sys
body = json.load(sys.stdin)
with open({str(self.log)!r}, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "body": body}}) + "\\n")
if "fail" in body["variables"].get("q", "") or body["query"].startswith("query{{viewer"):
    sys.stderr.write("HTTP 401: Bad credentials\\n")
    sys.exit(1)
after = body["variables"].get("after")
page = {{"hasNextPage": after is None, "endCursor": "c1"}}
print(json.dumps({{"data": {{"search": {{"pageInfo": page, "nodes": [{{"n": after or "first"}}]}}}}}}))
"""
        )
        self.gh.chmod(0o755)

    def test_pages_and_read_only_call(self):
        nodes = prs.GitHub(str(self.gh))._search(prs.OWN_Q, "is:pr")
        self.assertEqual(nodes, [{"n": "first"}, {"n": "c1"}])
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([c["argv"] for c in calls], [["api", "graphql", "--input", "-"]] * 2)
        self.assertNotIn("after", calls[0]["body"]["variables"])
        self.assertEqual(calls[1]["body"]["variables"]["after"], "c1")
        self.assertTrue(all(c["body"]["query"].startswith("query(") for c in calls))

    def test_error_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "Bad credentials"):
            prs.GitHub(str(self.gh))._search(prs.OWN_Q, "fail")

    def test_main_exit_code(self):
        cfg = Path(self.tmp.name) / "prs.json"
        cfg.write_text(json.dumps({"gh": str(self.gh), "orgs": ["o"]}))
        env = dict(os.environ, AGENT_HUB_PRS_CONFIG=str(cfg))
        env.pop("AGENT_HUB_GH", None)
        res = subprocess.run([sys.executable, str(Path(prs.__file__)), "--json"], env=env, capture_output=True, text=True)
        # 偽の gh は viewer に認証エラーを返すので、2 で終わる
        self.assertEqual(res.returncode, 2)
        self.assertIn("prs.py: gh api graphql: HTTP 401", res.stderr)
        self.assertEqual(res.stdout, "")


if __name__ == "__main__":
    unittest.main()
