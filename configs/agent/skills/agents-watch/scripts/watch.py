#!/usr/bin/env python3
"""見張りのスレッド（agents-watch）が新しい出来事を見つけるための、読むだけのスクリプト。

GitHub へは `gh api graphql` で問い合わせるだけで、何も書き込まない。Python の標準ライブラリと gh だけで動かす。

状態は state ディレクトリ（既定は ${AGENT_ORCHESTRATOR_HOME:-~/hub}/state、AGENT_WATCH_STATE で変える）に置く。
- seen.txt: 知らせ済みの出来事の key を 1 行に 1 つ
- events.jsonl: 知らせた出来事を 1 行に 1 つ（あとで GTD の受信箱などから読めるよう、追記だけする）
- watch-heartbeat: hours を最後に実行した時刻（ISO 8601）。見張りが止まっていないかを stale で確かめる
- watch.json: 設定（無くてよい）。キーはすべて省略できる
    {"ignore_authors": [], "work_days": [1, 2, 3, 4, 5], "work_start": 9, "work_end": 19}
  ignore_authors は、自分の PR へのコメントを知らせない作者（CI の bot など）。
  work_days は ISO の曜日（月 = 1）、work_start・work_end は時（work_end の時は含まない）。

Usage:
  watch.py hours            心拍を記録し、勤務時間なら終了コード 0、外なら 1
  watch.py stale            勤務時間内で心拍が 1 時間より古い（か無い）ときだけ 1 行出す。終了コードは常に 0
  watch.py prs [--dry-run]
      GitHub の新しい出来事を JSON Lines で標準出力に出し、seen.txt と events.jsonl に記録する。
      初回（seen.txt が無いとき）は今あるものをすべて記録し、コメント以外だけを出す。
  watch.py seen <source> [--dry-run]
      標準入力の JSON Lines（各行に "key" が要る）のうち、まだ知らせていないものだけを出して記録する。
      Slack のように、スクリプトの外で集めた出来事に使う。

出来事の形: {"source", "kind", "key", "keys"?, "url", "title", "repo"?, "note"?, "at"}
gh が失敗したら標準エラーに理由を出して終了コード 2 で終わる。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULTS = {
    "ignore_authors": [],
    "work_days": [1, 2, 3, 4, 5],
    "work_start": 9,
    "work_end": 19,
}

STALE_AFTER = dt.timedelta(hours=1)

PR_COMMON = "number title url isDraft headRefOid repository{nameWithOwner}"

REQUEST_QUERY = (
    "query($q:String!){search(query:$q,type:ISSUE,first:50){nodes{... on PullRequest{"
    + PR_COMMON
    + " reviewRequests(first:50){nodes{asCodeOwner requestedReviewer{__typename ... on User{login}}}}"
    + "}}}}"
)

OWN_QUERY = (
    "query($q:String!){search(query:$q,type:ISSUE,first:50){nodes{... on PullRequest{"
    + PR_COMMON
    + " latestReviews(first:20){nodes{author{login} state submittedAt url}}"
    + " comments(last:20){nodes{id url createdAt author{login}}}"
    + " reviewThreads(last:50){nodes{comments(last:5){nodes{id url createdAt author{login}}}}}"
    + " commits(last:1){nodes{commit{statusCheckRollup{state}}}}"
    + "}}}}"
)

REQUEST_SEARCH = "is:pr is:open -is:draft archived:false user-review-requested:@me"
OWN_SEARCH = "is:pr is:open archived:false author:@me"


class GhError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 設定と状態


def state_dir() -> Path:
    if os.environ.get("AGENT_WATCH_STATE"):
        return Path(os.environ["AGENT_WATCH_STATE"]).expanduser()
    home = os.environ.get("AGENT_ORCHESTRATOR_HOME") or str(Path.home() / "hub")
    return Path(home).expanduser() / "state"


def load_config(directory: Path) -> dict:
    cfg = dict(DEFAULTS)
    path = directory / "watch.json"
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    return cfg


def load_seen(directory: Path) -> set[str] | None:
    """知らせ済みの key。seen.txt が無ければ None（初回）。"""
    path = directory / "seen.txt"
    if not path.exists():
        return None
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def record(directory: Path, events: list[dict], extra_keys: list[str] = ()) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    keys = list(extra_keys)
    for event in events:
        keys.extend(event_keys(event))
    with (directory / "seen.txt").open("a") as f:
        for key in keys:
            f.write(key + "\n")
    if events:
        with (directory / "events.jsonl").open("a") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_heartbeat(directory: Path, now: dt.datetime) -> None:
    """記録に失敗しても hours の判定は止めない。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "watch-heartbeat").write_text(now.isoformat(timespec="seconds") + "\n")
    except OSError as e:
        print(f"watch.py: 心拍を書けません: {e}", file=sys.stderr)


def read_heartbeat(directory: Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat((directory / "watch-heartbeat").read_text().strip())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 判定（純粋な関数）


def in_work_hours(now: dt.datetime, cfg: dict) -> bool:
    return now.isoweekday() in cfg["work_days"] and cfg["work_start"] <= now.hour < cfg["work_end"]


def is_stale(last: dt.datetime | None, now: dt.datetime, cfg: dict) -> bool:
    """勤務時間内で、心拍が無いか STALE_AFTER より古いか。心拍は勤務時間外にも書かれる。"""
    return in_work_hours(now, cfg) and (last is None or now - last > STALE_AFTER)


def event_keys(event: dict) -> list[str]:
    return list(event.get("keys") or [event["key"]])


def unseen(events: list[dict], seen: set[str]) -> list[dict]:
    """まだ知らせていない出来事。keys を持つものは、新しい key だけに絞る。"""
    out = []
    for event in events:
        new = [k for k in event_keys(event) if k not in seen]
        if not new:
            continue
        if "keys" in event:
            event = dict(event, keys=new, key=new[0])
        out.append(event)
    return out


def _pr_base(pr: dict, kind: str, key: str) -> dict:
    return {
        "source": "github",
        "kind": kind,
        "key": key,
        "url": pr["url"],
        "title": pr["title"],
        "repo": pr["repository"]["nameWithOwner"],
    }


def review_request_events(prs: list[dict], me: str) -> list[dict]:
    """自分が User reviewer として名指しされた（CODEOWNERS・チーム経由でない）依頼。head ごとに 1 回。"""
    events = []
    for pr in prs:
        if not pr or pr.get("isDraft"):
            continue
        named = any(
            not node.get("asCodeOwner")
            and (node.get("requestedReviewer") or {}).get("__typename") == "User"
            and node["requestedReviewer"].get("login") == me
            for node in pr["reviewRequests"]["nodes"]
        )
        if named:
            events.append(_pr_base(pr, "review_request", f"review_request:{pr['url']}@{pr['headRefOid']}"))
    return events


def own_pr_events(prs: list[dict], me: str, ignore_authors: list[str]) -> list[dict]:
    """自分の PR の CI の失敗・変更要求・ほかの人の新しいコメント。"""
    ignored = set(ignore_authors) | {me}
    events = []
    for pr in prs:
        if not pr:
            continue
        commits = pr["commits"]["nodes"]
        rollup = (commits[0]["commit"].get("statusCheckRollup") or {}) if commits else {}
        if rollup.get("state") in ("FAILURE", "ERROR"):
            events.append(_pr_base(pr, "ci_failed", f"ci_failed:{pr['url']}@{pr['headRefOid']}"))

        for review in pr["latestReviews"]["nodes"]:
            if review["state"] == "CHANGES_REQUESTED":
                author = (review.get("author") or {}).get("login", "")
                event = _pr_base(pr, "changes_requested", f"changes_requested:{pr['url']}@{author}@{review['submittedAt']}")
                event["note"] = author
                events.append(event)

        comments = list(pr["comments"]["nodes"])
        for thread in pr["reviewThreads"]["nodes"]:
            comments.extend(thread["comments"]["nodes"])
        comments = [c for c in comments if (c.get("author") or {}).get("login") not in ignored]
        if comments:
            comments.sort(key=lambda c: c["createdAt"])
            event = _pr_base(pr, "comment", f"comment:{comments[0]['id']}")
            event["keys"] = [f"comment:{c['id']}" for c in comments]
            event["url"] = comments[-1]["url"]
            event["note"] = ", ".join(sorted({c["author"]["login"] for c in comments}))
            events.append(event)
    return events


def stamp(events: list[dict], now: dt.datetime) -> list[dict]:
    at = now.isoformat(timespec="seconds")
    return [dict(e, at=e.get("at") or at) for e in events]


# ---------------------------------------------------------------------------
# gh


def gh(args: list[str]) -> str:
    cmd = [os.environ.get("AGENT_WATCH_GH", "gh"), *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhError(f"gh を実行できません: {e}") from e
    if res.returncode != 0:
        raise GhError(res.stderr.strip() or f"gh が終了コード {res.returncode} で失敗しました")
    return res.stdout


def search(query: str, q: str) -> list[dict]:
    out = json.loads(gh(["api", "graphql", "-f", f"query={query}", "-f", f"q={q}"]))
    return out["data"]["search"]["nodes"]


def github_events(cfg: dict) -> list[dict]:
    me = gh(["api", "user", "--jq", ".login"]).strip()
    events = review_request_events(search(REQUEST_QUERY, REQUEST_SEARCH), me)
    events += own_pr_events(search(OWN_QUERY, OWN_SEARCH), me, cfg["ignore_authors"])
    return events


# ---------------------------------------------------------------------------
# 入口


def emit(events: list[dict]) -> None:
    for event in events:
        print(json.dumps(event, ensure_ascii=False))


def cmd_github(args, directory: Path, now: dt.datetime) -> int:
    cfg = load_config(directory)
    try:
        events = stamp(github_events(cfg), now)
    except GhError as e:
        print(f"watch.py: {e}", file=sys.stderr)
        return 2
    seen = load_seen(directory)
    if seen is None:
        shown = [e for e in events if e["kind"] != "comment"]
        hidden = [k for e in events if e["kind"] == "comment" for k in event_keys(e)]
        if not args.dry_run:
            record(directory, shown, hidden)
        emit(shown)
        return 0
    new = unseen(events, seen)
    if not args.dry_run:
        record(directory, new)
    emit(new)
    return 0


def cmd_seen(args, directory: Path, now: dt.datetime, stdin) -> int:
    events = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if "key" not in event:
            print("watch.py: key の無い行があります", file=sys.stderr)
            return 2
        event.setdefault("source", args.source)
        events.append(event)
    new = unseen(stamp(events, now), load_seen(directory) or set())
    if not args.dry_run:
        record(directory, new)
    emit(new)
    return 0


def main(argv: list[str] | None = None, now: dt.datetime | None = None, stdin=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hours")
    sub.add_parser("stale")
    p = sub.add_parser("prs")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("seen")
    p.add_argument("source")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    directory = state_dir()
    now = now or dt.datetime.now().astimezone()
    if args.cmd == "stale":
        last = read_heartbeat(directory)
        if is_stale(last, now, load_config(directory)):
            when = last.isoformat(timespec="minutes") if last else "記録なし"
            print(f"見張りが止まっている可能性があります（最後の心拍: {when}）")
        return 0
    if args.cmd == "hours":
        write_heartbeat(directory, now)
        return 0 if in_work_hours(now, load_config(directory)) else 1
    if args.cmd == "prs":
        return cmd_github(args, directory, now)
    return cmd_seen(args, directory, now, stdin or sys.stdin)


if __name__ == "__main__":
    sys.exit(main())
