#!/usr/bin/env python3
"""GitHub で新しい出来事が起きるまで待ち、起きたら 1 行 1 件で出して終わる。窓口（hub）を起こすためのスクリプト。

hub は Bash の run_in_background でこれを動かし、終わったら起きて出来事を処理し、また起動する。
ループは hub の側にあり、このスクリプトは出来事を出したら終わる。

拾う出来事（出力の 1 列目）:
- review_requested: 自分宛ての名指しのレビュー依頼。prs.py の review_requests と同じ判定（CODEOWNERS・チーム・
  bot の依頼と draft は除く）。同じ PR でも、依頼し直されたら新しい出来事になる
- ci_failed: 自分の open の PR の head の CI が失敗した。head ごとに 1 回
- review: 自分の PR に、人（自分と bot を除く）がレビューを付けた
- comment: 自分の PR に、人が会話のコメントを付けた
- mention: 人が自分を @ で名指しした（issue・PR の本文、コメント、レビュー、レビューのコメント）

出し方: 1 行 1 件、タブ区切りで「種類 repo 番号 タイトル URL」。URL はレビューやコメントそのものを指す。
同じ PR に同じ種類の出来事が重なったら 1 行にまとめる。

GitHub の通知 API は使わない。ghtkn などの GitHub App のトークンでは読めないため。代わりに `gh api graphql`
で自分の PR・レビュー依頼・mention を読み、前に見たもの（seen）との差分を出来事にする。GitHub には書き込まず、
既読にもしない。mention は検索（mentions:@me）で更新の新しい 20 件だけを見て、その中の直近のコメントを調べるので、
通知より粗い（古いスレッドの奥、編集で足された @、チーム宛ての @ は拾わない）。

seen: ${XDG_STATE_HOME:-~/.local/state}/agent-hub/notify-seen.txt（--state DIR で変える）。キーだけを持つ。
ファイルが無い初回は、今ある出来事を記録だけして出さない。

設定: prs.py と同じ ${XDG_CONFIG_HOME:-~/.config}/agent-hub/prs.json。対象の org・リポジトリ、除外、bots、
gh のパスに加えて、notify_interval_s（見る間隔、既定 60 秒）と notify_max_minutes（何も無いときに終わるまで、
既定 720 分）を使う。

終了コード: 0 は出来事を出した。1 は notify_max_minutes の間に何も無かった（起動し直す）。2 は直らない失敗
（設定の誤り、認証エラーなどが 3 回続いた）で、理由を標準エラーに出す。5xx・タイムアウト・利用枠の超過は、
間隔を延ばして待ち直し、失敗に数えない。

考え方は JeongJaeSoon/agent-skills の skills/watch-prs の scripts/notify.py（MIT License,
Copyright (c) 2026 JeongJaeSoon）を参考にした（seen の扱い、human_activity_only・personal_review_only の絞り込み、
終了コード、待ち直し）。

Usage: notify.py [--once] [--config PATH] [--state DIR]
  --once は 1 回だけ見て終わる（出来事があれば 0、無ければ 1）。初回の記録の確認に使う。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prs  # noqa: E402

KINDS = ("review_requested", "ci_failed", "review", "comment", "mention")
KEEP_SEEN = 5000
MAX_FAILURES = 3
MAX_BACKOFF_S = 900
MENTION_PAGE = 20
TRANSIENT = re.compile(
    r"HTTP (5\d\d|429)|rate limit|secondary rate|dial tcp|no such host|connection (refused|reset)|timeout|timed out|EOF",
    re.I,
)

ACTOR = "author{__typename login}"
CHECKS = """statusCheckRollup{state contexts(first:100){pageInfo{hasNextPage} nodes{__typename
 ... on CheckRun{name status conclusion startedAt completedAt checkSuite{workflowRun{workflow{name}}}}
 ... on StatusContext{context state createdAt}}}}"""
OWN_FIELDS = f"""id number title url isDraft headRefOid repository{{nameWithOwner}}
 reviews(last:30){{nodes{{id url state {ACTOR}}}}}
 comments(last:30){{nodes{{id url {ACTOR}}}}}
 commits(last:1){{nodes{{commit{{oid {CHECKS}}}}}}}"""
TEXT = f"id url body {ACTOR}"
MENTION_COMMON = f"{TEXT} number title repository{{nameWithOwner}} comments(last:20){{nodes{{{TEXT}}}}}"
MENTION_FIELDS = f"""... on Issue{{{MENTION_COMMON}}}
 ... on PullRequest{{{MENTION_COMMON} reviews(last:10){{nodes{{{TEXT} comments(last:10){{nodes{{{TEXT}}}}}}}}}}}"""
MENTION_Q = (
    f"query($q:String!){{search(query:$q,type:ISSUE,first:{MENTION_PAGE}){{nodes{{{MENTION_FIELDS}}}}}}}"
)


class Fatal(RuntimeError):
    pass


class Source(prs.GitHub):
    """notify.py が使う GitHub の読み取り。テストではこれを偽物に差し替える。"""

    def own_activity(self) -> list[dict]:
        return self._search(prs.search_query(OWN_FIELDS, False), "is:pr is:open archived:false author:@me")

    def mentions(self) -> list[dict]:
        q = "mentions:@me archived:false sort:updated-desc"
        return [n for n in self.graphql(MENTION_Q, q=q)["search"]["nodes"] if n]


@dataclass(frozen=True)
class Event:
    kind: str
    repo: str
    number: int
    title: str
    url: str
    key: str

    def line(self) -> str:
        def clean(s: str) -> str:
            return re.sub(r"\s+", " ", s).strip()

        return "\t".join((self.kind, self.repo, str(self.number), clean(self.title)[:100], self.url))


# ---------------------------------------------------------------------------
# 判定（GitHub から取った node と設定だけで決める。I/O はしない）


def by_person(node: dict, me: str, cfg: dict) -> bool:
    author = node.get("author")
    return prs.login(author) != me and prs.is_person(author, cfg)


def mentions_me(body: str | None, me: str) -> bool:
    return bool(re.search(rf"(?<![\w/`])@{re.escape(me)}(?![\w-])", body or "", re.I))


def request_events(nodes: list[dict], me: str, cfg: dict) -> list[Event]:
    events = []
    for pr in nodes:
        if prs.review_request_why(pr, me, cfg):
            continue
        asks = [e for e in pr["timelineItems"]["nodes"] if e and prs.login(e.get("requestedReviewer")) == me]
        events.append(Event("review_requested", pr["repository"]["nameWithOwner"], pr["number"], pr["title"],
                            pr["url"], f"rr:{pr['id']}@{asks[-1]['createdAt']}"))
    return events


def own_events(nodes: list[dict], me: str, cfg: dict) -> list[Event]:
    events = []
    for pr in nodes:
        if prs.out_of_scope(pr, cfg):
            continue
        repo, number, title = pr["repository"]["nameWithOwner"], pr["number"], pr["title"]
        last = (pr["commits"]["nodes"] or [{}])[-1].get("commit") or {}
        if prs.ci_state(last.get("statusCheckRollup")) == "failure":
            events.append(Event("ci_failed", repo, number, title, f"{pr['url']}/checks",
                                f"ci:{pr['id']}@{pr['headRefOid']}"))
        for r in pr["reviews"]["nodes"]:
            if r and r.get("state") != "PENDING" and by_person(r, me, cfg):
                events.append(Event("review", repo, number, title, r["url"], f"c:{r['id']}"))
        for c in pr["comments"]["nodes"]:
            if c and by_person(c, me, cfg):
                events.append(Event("comment", repo, number, title, c["url"], f"c:{c['id']}"))
    return events


def mention_events(nodes: list[dict], me: str, cfg: dict) -> list[Event]:
    events = []
    for item in nodes:
        if not item.get("repository") or prs.out_of_scope(item, cfg):
            continue
        texts = [item, *item["comments"]["nodes"]]
        for r in (item.get("reviews") or {}).get("nodes") or []:
            texts += [r, *r["comments"]["nodes"]]
        for t in texts:
            if t and by_person(t, me, cfg) and mentions_me(t.get("body"), me):
                events.append(Event("mention", item["repository"]["nameWithOwner"], item["number"],
                                    item["title"], t["url"], f"c:{t['id']}"))
    return events


def new_events(events: list[Event], seen: set[str]) -> tuple[list[Event], list[str]]:
    """まだ見ていない出来事と、記録するキー。同じキー（自分の PR で自分を名指ししたコメントなど）は種類の順で
    先のものだけを残し、同じ PR の同じ種類は 1 件にまとめる。"""
    order = {k: i for i, k in enumerate(dict.fromkeys(("mention", *KINDS)))}
    fresh, keys, lines = [], [], set()
    for e in sorted(events, key=lambda e: order[e.kind]):
        if e.key in seen or e.key in keys:
            continue
        keys.append(e.key)
        if (e.kind, e.repo, e.number) not in lines:
            lines.add((e.kind, e.repo, e.number))
            fresh.append(e)
    fresh.sort(key=lambda e: KINDS.index(e.kind))
    return fresh, keys


# ---------------------------------------------------------------------------
# seen と待ち


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base).expanduser() / "agent-hub"


def read_seen(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").split()
    except FileNotFoundError:
        return None


def write_seen(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}\n" for k in keys[-KEEP_SEEN:]))
    os.replace(tmp, path)


def collect(gh: Source, me: str, cfg: dict) -> list[Event]:
    return (
        request_events(gh.review_requested(me), me, cfg)
        + own_events(gh.own_activity(), me, cfg)
        + mention_events(gh.mentions(), me, cfg)
    )


def watch(gh: Source, cfg: dict, path: Path, once: bool = False, sleep=time.sleep, clock=time.monotonic) -> list[Event]:
    """出来事が出るまで見る。出来事を返す。時間切れなら空。直らない失敗は Fatal。"""
    interval = cfg["notify_interval_s"]
    deadline = clock() + cfg["notify_max_minutes"] * 60
    me, failures, streak = None, 0, 0
    while True:
        try:
            me = me or gh.viewer()
            events = collect(gh, me, cfg)
        except (RuntimeError, KeyError, TypeError) as e:
            streak += 1
            if not TRANSIENT.search(str(e)):
                failures += 1
                if failures >= MAX_FAILURES:
                    raise Fatal(f"{failures} 回続けて失敗: {e}") from e
            if once:
                raise Fatal(str(e)) from e
            wait = min(interval * 2 ** (streak - 1), MAX_BACKOFF_S)
        else:
            failures = streak = 0
            seen = read_seen(path)
            fresh, keys = new_events(events, set(seen or []))
            if seen is None:
                write_seen(path, keys)  # 初回は記録だけ
                fresh = []
            elif keys:
                write_seen(path, seen + keys)
            if fresh:
                return fresh
            wait = interval
        if once or clock() + wait >= deadline:
            return []
        sleep(wait)


def check_config(cfg: dict) -> None:
    for k in ("notify_interval_s", "notify_max_minutes"):
        if cfg[k] <= 0:
            raise prs.ConfigError(f"{k} は 1 以上にしてください")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="1 回だけ見て終わる")
    ap.add_argument("--config", type=Path, help="設定ファイル（既定: $XDG_CONFIG_HOME/agent-hub/prs.json）")
    ap.add_argument("--state", type=Path, help="seen を置くディレクトリ（既定: $XDG_STATE_HOME/agent-hub）")
    args = ap.parse_args(argv)
    try:
        cfg = prs.load_config(args.config)
        check_config(cfg)
        path = (args.state or state_dir()) / "notify-seen.txt"
        first = not path.exists()
        events = watch(Source(prs.gh_path(cfg)), cfg, path, once=args.once)
    except (prs.ConfigError, Fatal, OSError) as e:
        print(f"notify.py: {e}", file=sys.stderr)
        return 2
    if events:
        print("\n".join(e.line() for e in events))
        return 0
    if first and path.exists():
        print(f"notify.py: 初回なので今ある出来事を記録しました（{len(read_seen(path) or [])} 件）", file=sys.stderr)
    else:
        print("notify.py: 新しい出来事はありませんでした。起動し直してください", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
