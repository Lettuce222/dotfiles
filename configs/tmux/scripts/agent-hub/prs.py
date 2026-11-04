#!/usr/bin/env python3
"""窓口（hub）が GitHub の PR の状況をつかむための、読むだけのスクリプト。

集めるもの:
- review_requests: 自分宛てのレビュー依頼。自分が User reviewer として名指しで依頼され
  （CODEOWNERS・チーム経由は除く）、最後に依頼したのが人（bot・app ではない）で、draft でない PR
- own_prs: 自分が作った open の PR と、その待ち状態（STATES を参照）

GitHub へは `gh api graphql` で問い合わせるだけで、何も書き込まない。Python の標準ライブラリと gh だけで動かす。

設定: ${XDG_CONFIG_HOME:-~/.config}/agent-hub/prs.json（AGENT_HUB_PRS_CONFIG か --config で変える）。
無ければ全リポジトリが対象。キーはすべて省略できる:
  {"orgs": [], "repos": [], "exclude_orgs": [], "exclude_repos": [],
   "exclude_title_patterns": [], "bots": [], "ignore_authors": [], "stale_days": 30, "gh": "gh"}
- orgs・repos が両方空なら全リポジトリ。どちらかがあれば、その org（owner）か owner/name だけ
- exclude_title_patterns は re.search の正規表現。合う PR はどちらの一覧にも出さない
- bots は GitHub 上は User だが人として扱わないアカウント（依頼者・作者の判定に使う）
- ignore_authors の作者の PR はレビュー依頼に出さない
- gh は gh のパス。環境変数 AGENT_HUB_GH が優先する

判定の考え方は JeongJaeSoon/agent-skills の skills/watch-prs（MIT License,
Copyright (c) 2026 JeongJaeSoon）の「What counts」と「Own PRs waiting on people」、
scripts/prs.py の personal_request / request_why / wait_state を参考にした。

Usage: prs.py [--json] [--config PATH]
  既定は人が読む短い一覧、--json は hub が読む JSON を標準出力に出す。
  gh が失敗したら標準エラーに理由を出して終了コード 2 で終わる。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULTS = {
    "orgs": [],
    "repos": [],
    "exclude_orgs": [],
    "exclude_repos": [],
    "exclude_title_patterns": [],
    "bots": [],
    "ignore_authors": [],
    "stale_days": 30,
    "gh": "gh",
}

# own_prs の states に入る値。表示の順もこの順にする
STATES = {
    "ci_failed": "CI 失敗",
    "changes_requested": "変更要求",
    "unanswered": "未返信のスレッド",
    "approval_stale": "承認が古い head",
    "no_reviewer": "reviewer なし",
    "waiting": "レビュー待ち",
    "approved": "承認済み",
}

PAGE = 25
GH_RETRY_WAITS = (2, 4)

REQUEST_FIELDS = """id number title url isDraft createdAt updatedAt headRefOid additions deletions reviewDecision
 repository{nameWithOwner} author{__typename login}
 reviewRequests(first:50){nodes{asCodeOwner requestedReviewer{__typename ... on User{login} ... on Team{slug}}}}
 reviews(author:$me,last:1){nodes{state commit{oid}}}
 timelineItems(last:50,itemTypes:[REVIEW_REQUESTED_EVENT]){nodes{... on ReviewRequestedEvent{createdAt
  actor{__typename login} requestedReviewer{__typename ... on User{login}}}}}"""

OWN_FIELDS = """id number title url isDraft createdAt updatedAt headRefOid additions deletions reviewDecision
 repository{nameWithOwner} author{__typename login}
 reviewRequests(first:50){nodes{asCodeOwner requestedReviewer{__typename ... on User{login} ... on Team{slug}}}}
 latestReviews(first:50){nodes{author{__typename login} state submittedAt commit{oid}}}
 reviewThreads(first:100){nodes{isResolved comments(last:1){nodes{author{__typename login} createdAt}}}}
 timelineItems(last:50,itemTypes:[REVIEW_REQUESTED_EVENT,REVIEW_DISMISSED_EVENT]){nodes{__typename
  ... on ReviewRequestedEvent{createdAt requestedReviewer{__typename ... on User{login} ... on Team{slug}}}
  ... on ReviewDismissedEvent{createdAt previousReviewState review{author{login}}}}}
 commits(last:1){nodes{commit{committedDate statusCheckRollup{state
  contexts(first:100){pageInfo{hasNextPage} nodes{__typename
   ... on CheckRun{name status conclusion startedAt completedAt checkSuite{workflowRun{workflow{name}}}}
   ... on StatusContext{context state createdAt}}}}}}}"""


def search_query(fields: str, me_var: bool) -> str:
    args = "$q:String!,$after:String" + (",$me:String!" if me_var else "")
    return (
        f"query({args}){{search(query:$q,type:ISSUE,first:{PAGE},after:$after)"
        f"{{pageInfo{{hasNextPage endCursor}} nodes{{... on PullRequest{{{fields}}}}}}}}}"
    )


REQUEST_Q = search_query(REQUEST_FIELDS, True)
OWN_Q = search_query(OWN_FIELDS, False)


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 設定と gh


def config_path() -> Path:
    if os.environ.get("AGENT_HUB_PRS_CONFIG"):
        return Path(os.environ["AGENT_HUB_PRS_CONFIG"]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "agent-hub" / "prs.json"


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: JSON のオブジェクトではありません")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"{path}: 知らないキー: {', '.join(sorted(unknown))}")
    cfg = {**DEFAULTS, **raw}
    for k, v in DEFAULTS.items():
        if not isinstance(cfg[k], type(v)):
            raise ConfigError(f"{path}: {k} は {type(v).__name__} にしてください")
    for p in cfg["exclude_title_patterns"]:
        try:
            re.compile(p)
        except re.error as e:
            raise ConfigError(f"{path}: exclude_title_patterns の {p!r}: {e}") from e
    return cfg


def gh_path(cfg: dict) -> str:
    """AGENT_HUB_GH > 設定の gh > PATH の gh。非対話のシェルで別の gh を直接呼ぶ必要がある環境向け。"""
    return str(Path(os.environ.get("AGENT_HUB_GH") or cfg.get("gh") or "gh").expanduser())


class GitHub:
    """prs.py が使う GitHub の読み取り。テストではこれを偽物に差し替える。"""

    def __init__(self, gh: str = "gh", timeout: float = 60):
        self.gh = gh
        self.timeout = timeout

    def graphql(self, query: str, **variables) -> dict:
        body = json.dumps({"query": query, "variables": {k: v for k, v in variables.items() if v is not None}})
        # 502/504 は GitHub の GraphQL のタイムアウトか一時的な障害なので、少し待って取り直す
        for wait in (*GH_RETRY_WAITS, None):
            try:
                out = subprocess.run(
                    [self.gh, "api", "graphql", "--input", "-"],
                    input=body, capture_output=True, text=True, timeout=self.timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                raise RuntimeError(f"{self.gh}: {type(e).__name__}: {e}") from e
            if wait is None or not (out.returncode and re.search(r"HTTP 5\d\d", out.stderr)):
                break
            time.sleep(wait)
        try:
            data = json.loads(out.stdout).get("data")
        except ValueError:
            data = None
        if out.returncode or data is None:
            raise RuntimeError(f"gh api graphql: {out.stderr.strip()[:300] or f'exit {out.returncode}'}")
        return data

    def viewer(self) -> str:
        return self.graphql("query{viewer{login}}")["viewer"]["login"]

    def _search(self, query: str, q: str, **variables) -> list[dict]:
        nodes, after = [], None
        while True:
            page = self.graphql(query, q=q, after=after, **variables)["search"]
            nodes += [n for n in page["nodes"] if n]
            if not page["pageInfo"]["hasNextPage"]:
                return nodes
            after = page["pageInfo"]["endCursor"]

    def review_requested(self, me: str) -> list[dict]:
        # user-review-requested はチーム経由の依頼を除くが、CODEOWNERS や bot の依頼は残るので、判定は review_request_why で行う
        return self._search(REQUEST_Q, "is:pr is:open archived:false user-review-requested:@me", me=me)

    def own(self) -> list[dict]:
        return self._search(OWN_Q, "is:pr is:open archived:false author:@me")

    def count(self, q: str) -> int:
        return self.graphql("query($q:String!){search(query:$q,type:ISSUE,first:0){issueCount}}", q=q)["search"]["issueCount"]


# ---------------------------------------------------------------------------
# 判定（GitHub から取った node と設定と時刻だけで決める。I/O はしない）


def ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def hours(since: float, now: float) -> int:
    return max(0, int((now - since) // 3600))


def days(iso: str, now: float) -> int:
    return max(0, int((now - ts(iso)) // 86400))


def login(actor: dict | None) -> str:
    return (actor or {}).get("login") or ""


def norm(name: str) -> str:
    return name.lower().removesuffix("[bot]")


def is_person(actor: dict | None, cfg: dict) -> bool:
    """User アカウントで、設定の bots に入っていないもの。Bot・Mannequin・app（actor が無い）は人ではない。"""
    actor = actor or {}
    return actor.get("__typename") == "User" and norm(login(actor)) not in {norm(b) for b in cfg["bots"]}


def pr_name(pr: dict) -> str:
    return f"{pr['repository']['nameWithOwner']}#{pr['number']}"


def out_of_scope(pr: dict, cfg: dict) -> str | None:
    repo = pr["repository"]["nameWithOwner"]
    org = repo.split("/")[0]
    if repo in cfg["exclude_repos"] or org in cfg["exclude_orgs"]:
        return "除外したリポジトリ"
    if (cfg["orgs"] or cfg["repos"]) and org not in cfg["orgs"] and repo not in cfg["repos"]:
        return "対象外のリポジトリ"
    if any(re.search(p, pr["title"]) for p in cfg["exclude_title_patterns"]):
        return "除外したタイトル"
    return None


def review_request_why(pr: dict, me: str, cfg: dict) -> str | None:
    """自分宛てのレビュー依頼として数えるなら None、数えないなら理由。"""
    if why := out_of_scope(pr, cfg):
        return why
    if norm(login(pr.get("author"))) in {norm(a) for a in cfg["ignore_authors"]}:
        return "無視する作者"
    personal = any(
        (n.get("requestedReviewer") or {}).get("__typename") == "User"
        and n["requestedReviewer"].get("login") == me
        and not n.get("asCodeOwner")
        for n in pr["reviewRequests"]["nodes"]
    )
    if not personal:
        return "CODEOWNERS かチーム経由の依頼だけ"
    # 最後に自分を依頼したのが人か。timeline の窓（直近 50 件）より古い依頼は、人のものと確かめられないので数えない
    asks = [e for e in pr["timelineItems"]["nodes"] if e and login(e.get("requestedReviewer")) == me]
    if not asks or not is_person(asks[-1].get("actor"), cfg):
        return "人ではないアカウントの依頼"
    if pr["isDraft"]:
        return "draft"
    return None


def review_request_item(pr: dict, me: str, cfg: dict, now: float) -> dict:
    asks = [e for e in pr["timelineItems"]["nodes"] if e and login(e.get("requestedReviewer")) == me]
    asked = ts(asks[-1]["createdAt"]) if asks else ts(pr["createdAt"])
    reviewers = [n["requestedReviewer"] for n in pr["reviewRequests"]["nodes"] if n.get("requestedReviewer")]
    mine = pr["reviews"]["nodes"]
    idle = days(pr["updatedAt"], now)
    return {
        "key": f"{pr_name(pr)}@{pr['headRefOid']}",
        "pr": pr_name(pr),
        "repo": pr["repository"]["nameWithOwner"],
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "author": login(pr.get("author")),
        "author_is_person": is_person(pr.get("author"), cfg),
        "requested_by": login(asks[-1].get("actor")) if asks else "",
        "requested_at": dt.datetime.fromtimestamp(asked, dt.timezone.utc).isoformat(),
        "waiting_hours": hours(asked, now),
        "age_days": days(pr["createdAt"], now),
        "idle_days": idle,
        "size": pr["additions"] + pr["deletions"],
        # 残っている reviewer が自分だけで、レビューが要る状態
        "only_blocker": pr.get("reviewDecision") == "REVIEW_REQUIRED"
        and [(r.get("__typename"), r.get("login")) for r in reviewers] == [("User", me)],
        # 前にレビューしたあと、新しい commit で依頼し直された
        "re_review": bool(mine) and (mine[-1].get("commit") or {}).get("oid") != pr["headRefOid"],
        "stale": idle > cfg["stale_days"],
    }


def rank_requests(items: list[dict]) -> list[dict]:
    """古くて動いていないものは最後。次に自分だけが止めているもの、人が作ったもの、長く待っているもの、小さいもの。"""
    return sorted(
        items,
        key=lambda i: (i["stale"], not i["only_blocker"], not i["author_is_person"], -i["waiting_hours"], i["size"]),
    )


ROLLUP_CI = {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure", "PENDING": "pending", "EXPECTED": "pending"}
CHECK_RUN_FAILURES = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}


def check_ci(node: dict) -> tuple[str, str, str] | None:
    """rollup の 1 件を (名前, 新しさの比較キー, success|failure|pending) にする。

    GitHub Actions のジョブは、別のワークフローの同じ名前のジョブと混ぜないよう、名前にワークフロー名を付ける。
    """
    if node.get("__typename") == "CheckRun":
        if node.get("status") != "COMPLETED":
            state = "pending"
        else:
            state = "failure" if node.get("conclusion") in CHECK_RUN_FAILURES else "success"
        workflow = (((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow") or {}).get("name") or ""
        # 待ち行列にあってまだ始まっていない実行は、ほかのどれよりも新しい
        return f"{workflow} / {node.get('name') or ''}", node.get("startedAt") or node.get("completedAt") or "\uffff", state
    if node.get("__typename") == "StatusContext":
        return f"status: {node.get('context') or ''}", node.get("createdAt") or "", ROLLUP_CI.get(node.get("state") or "", "pending")
    return None


def ci_state(rollup: dict | None) -> str | None:
    """head の CI の状態。同じ名前のチェックは最新の実行だけで決める。

    statusCheckRollup.state は、後の実行に置き換えられて CANCELLED になった古い実行も失敗に数えるので、
    contexts を名前ごとに見る。contexts が取り切れないときだけ rollup の state に頼る。
    """
    if not rollup:
        return None
    contexts = rollup.get("contexts") or {}
    nodes = [c for c in map(check_ci, contexts.get("nodes") or []) if c]
    if not nodes or (contexts.get("pageInfo") or {}).get("hasNextPage"):
        return ROLLUP_CI.get(rollup.get("state") or "")
    latest: dict[str, tuple[str, str]] = {}
    for name, when, state in nodes:
        if name not in latest or when >= latest[name][0]:
            latest[name] = (when, state)
    states = {state for _, state in latest.values()}
    for state in ("failure", "pending"):
        if state in states:
            return state
    return "success"


def own_pr_item(pr: dict, me: str, cfg: dict, now: float) -> dict:
    """自分の PR が何を待っているか。GitHub の状態だけから決める。"""
    head = pr["headRefOid"]
    decision = pr.get("reviewDecision")
    requests = [n["requestedReviewer"] for n in pr["reviewRequests"]["nodes"] if n.get("requestedReviewer")]

    asked: dict[str, float] = {}
    dismissed: set[str] = set()
    for e in pr["timelineItems"]["nodes"]:
        if not e:
            continue
        if e.get("__typename") == "ReviewRequestedEvent":
            r = e.get("requestedReviewer") or {}
            name = r.get("login") or (f"team:{r['slug']}" if r.get("slug") else "")
            if name:
                asked[name] = ts(e["createdAt"])
        elif e.get("__typename") == "ReviewDismissedEvent" and e.get("previousReviewState") == "APPROVED":
            dismissed.add(login((e.get("review") or {}).get("author")))

    reviews = {
        login(r["author"]): r
        for r in pr["latestReviews"]["nodes"]
        if login(r.get("author")) and login(r["author"]) != me and is_person(r["author"], cfg)
    }
    stale_approvals = sorted(
        who
        for who, r in reviews.items()
        if decision == "REVIEW_REQUIRED"
        and (
            (r["state"] == "APPROVED" and (r.get("commit") or {}).get("oid") != head)
            or (r["state"] == "DISMISSED" and who in dismissed)
        )
    )

    waiting = []
    for r in requests:
        if r.get("__typename") == "User":
            name = r["login"]
            if name in stale_approvals:
                continue
        elif r.get("__typename") == "Team":
            name = f"team:{r['slug']}"
        else:
            continue
        since = asked.get(name, ts(pr["createdAt"]))
        waiting.append({
            "reviewer": name,
            "requested_at": dt.datetime.fromtimestamp(since, dt.timezone.utc).isoformat(),
            "hours": hours(since, now),
        })
    waiting.sort(key=lambda w: -w["hours"])

    last = (pr["commits"]["nodes"] or [{}])[-1].get("commit") or {}
    head_at = ts(last["committedDate"]) if last.get("committedDate") else 0
    unanswered = 0
    for t in pr["reviewThreads"]["nodes"]:
        if t["isResolved"] or not t["comments"]["nodes"]:
            continue
        c = t["comments"]["nodes"][-1]
        if login(c.get("author")) != me and ts(c["createdAt"]) > head_at:
            unanswered += 1

    ci = ci_state(last.get("statusCheckRollup"))
    changes = sorted(who for who, r in reviews.items() if r["state"] == "CHANGES_REQUESTED")
    approvers = sorted(
        who for who, r in reviews.items() if r["state"] == "APPROVED" and (r.get("commit") or {}).get("oid") == head
    )

    states = []
    if ci == "failure":
        states.append("ci_failed")
    if decision == "CHANGES_REQUESTED" or (decision is None and changes):
        states.append("changes_requested")
    if unanswered:
        states.append("unanswered")
    if stale_approvals:
        states.append("approval_stale")
    if not pr["isDraft"] and not requests and not reviews and decision != "APPROVED":
        states.append("no_reviewer")
    if waiting and not pr["isDraft"]:
        states.append("waiting")
    if decision == "APPROVED" or (decision is None and approvers and not changes):
        states.append("approved")

    idle = days(pr["updatedAt"], now)
    return {
        "key": f"{pr_name(pr)}@{head}",
        "pr": pr_name(pr),
        "repo": pr["repository"]["nameWithOwner"],
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "draft": pr["isDraft"],
        "review_decision": decision,
        "ci": ci,
        "states": states,
        "waiting": waiting,
        "changes_requested_by": changes,
        "approved_by": approvers,
        "stale_approvals": stale_approvals,
        "unanswered_threads": unanswered,
        "age_days": days(pr["createdAt"], now),
        "idle_days": idle,
        "stale": idle > cfg["stale_days"],
    }


def rank_own(items: list[dict]) -> list[dict]:
    """手を打つべきもの（STATES の前のほう）が先。draft と動いていないものは後ろ。"""
    order = list(STATES)

    def first_state(i: dict) -> int:
        return min((order.index(s) for s in i["states"]), default=len(order))

    return sorted(items, key=lambda i: (i["stale"], i["draft"], first_state(i), -i["idle_days"]))


def collect(gh: GitHub, cfg: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    me = gh.viewer()
    requests, own, excluded = [], [], []
    for pr in gh.review_requested(me):
        why = review_request_why(pr, me, cfg)
        if why:
            excluded.append({"pr": pr_name(pr), "list": "review_requests", "why": why})
        else:
            requests.append(review_request_item(pr, me, cfg, now))
    for pr in gh.own():
        why = out_of_scope(pr, cfg)
        if why:
            excluded.append({"pr": pr_name(pr), "list": "own_prs", "why": why})
        else:
            own.append(own_pr_item(pr, me, cfg, now))
    # チーム宛ての依頼は一覧には出さないが、数だけ残す（対象外のリポジトリの分も含む）
    team = gh.count("is:pr is:open archived:false draft:false review-requested:@me -user-review-requested:@me")
    return {
        "generated_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
        "viewer": me,
        "team_requests": team,
        "review_requests": rank_requests(requests),
        "own_prs": rank_own(own),
        "excluded": excluded,
    }


# ---------------------------------------------------------------------------
# 出力


def wait_text(h: int) -> str:
    return f"{h // 24}日" if h >= 48 else f"{h}時間"


def own_pr_summary(i: dict) -> str:
    parts = []
    for s in i["states"]:
        if s == "waiting":
            parts.append("待ち " + ", ".join(f"{w['reviewer']} {wait_text(w['hours'])}" for w in i["waiting"]))
        elif s == "unanswered":
            parts.append(f"未返信 {i['unanswered_threads']}")
        elif s == "changes_requested" and i["changes_requested_by"]:
            parts.append("変更要求 " + ", ".join(i["changes_requested_by"]))
        elif s == "approval_stale":
            parts.append("承認が古い head " + ", ".join(i["stale_approvals"]))
        else:
            parts.append(STATES[s])
    if i["draft"]:
        parts.insert(0, "draft")
    if i["stale"]:
        parts.append(f"{i['idle_days']}日動きなし")
    return " / ".join(parts) or "—"


def render_text(data: dict) -> str:
    lines = [f"レビュー依頼（{len(data['review_requests'])}、ほかにチーム宛て {data.get('team_requests', 0)}）"]
    for i in data["review_requests"]:
        flags = [f"{wait_text(i['waiting_hours'])}待ち", f"+-{i['size']}"]
        if i["only_blocker"]:
            flags.append("自分だけ")
        if i["re_review"]:
            flags.append("再レビュー")
        if i["stale"]:
            flags.append(f"{i['idle_days']}日動きなし")
        lines.append(f"  {i['pr']}  {i['title']}  [{i['author']}] {' '.join(flags)}")
    lines.append(f"自分の PR（{len(data['own_prs'])}）")
    for i in data["own_prs"]:
        lines.append(f"  {i['pr']}  {i['title']}  {own_pr_summary(i)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="hub が読む JSON を出す")
    ap.add_argument("--config", type=Path, help="設定ファイル（既定: $XDG_CONFIG_HOME/agent-hub/prs.json）")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        data = collect(GitHub(gh_path(cfg)), cfg)
    except (ConfigError, RuntimeError) as e:
        print(f"prs.py: {e}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
