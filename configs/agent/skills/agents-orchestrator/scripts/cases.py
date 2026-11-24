#!/usr/bin/env python3
"""窓口（orchestrator）の案件の一覧を扱うスクリプト。

案件は 1 件 1 ファイルの Markdown で、案件のディレクトリ（既定は
${AGENT_ORCHESTRATOR_HOME:-~/hub}/state/cases、AGENT_CASES_DIR で変える）に置く。
中身は社内の文脈なので dotfiles には置かない。ここにあるのは仕組みだけ。

    # explore-wam security scan 対応

    ## TODO
    - [#828](https://github.com/o/r/pull/828) にスクリーンショットを貼って Ready にする

    ## Waiting
    - [#818](https://github.com/o/r/pull/818) のレビュー待ち → 返ってきたら直す

    ## Later
    - チケットを完了にする

    ## 予定
    - [11/12] 定例で報告する → 次の回の資料を作る

    ## 資料
    - [report.md](file:///Users/me/hub/workers/x/report.md)

- 項目は `- ` で始まる行。2 文字以上の字下げで続く行は、前の項目の続き。
- TODO の項目は、先頭に期日 `[11/11]`（`[11/11（水）]` も可）と優先の印 `!` を書ける
  （例: `- [11/11] ! 資料を読む`）。年は書かず、今日にいちばん近い年とみなす。
- 見出しの次の行に `略称: <短い名前>` を書くと、TODO の一覧でその名前を案件の印にする。
- Waiting の項目は ` → ` のあとに、待ちが解けたらやることを書ける。待ちが解けると
  その部分が「TODO」に移る。
- 予定の項目は、準備が済んで、あとはその日に出るだけのもの。先頭に日付 `[11/12]` を書き、
  ` → ` のあとに、予定が済んだらやることを書ける。日付が過ぎると sweep が消し、` → ` のあとを
  「TODO」に移す。TODO の一覧には出さず、その下に目立たない形で出す。
- 資料以外の 4 つの節に項目が無くなった案件は done/ に移す（sweep）。

Usage:
  cases.py sweep [--dry-run]
      Waiting の項目のうち、GitHub の PR のリンクがすべて merge・close 済みのものと、
      予定の項目のうち、日付が今日より前のものを消す。
      ` → ` のあとがあれば「TODO」に移す。項目が無くなった案件は done/ に移す。
      したことと、残った PR 付きの項目の状態を JSON Lines で出す（下の「出力」を参照）。
  cases.py resolve <案件> <文字列> [--section Waiting]
      節の中で文字列を含む項目を 1 つ消す（2 つ以上・0 個ならエラー）。Waiting・予定なら
      ` → ` のあとを「TODO」に移す。<案件> はファイル名（.md は省略可）。
  cases.py json
      全案件を JSON で標準出力に出す（Orca の Hub パネルが読む）。形は下の「json の出力」。
  cases.py log <案件> <1 行>
      「資料」の節に 1 行足す（節が無ければ作る）。Hub のパネルで答えたことを残すのに使う。
      改行と制御文字は空白にする。<案件> はファイル名（.md は省略可、パスの区切りは不可）。

sweep の出力（1 行に 1 つ）:
  {"action": "removed", "case", "section", "item", "next"?}   消した項目（next は移したもの）
  {"action": "archived", "case"}                               done/ に移した案件
  {"action": "stale", "case", "section", "item", "prs"}        Waiting 以外で、PR がすべて閉じた項目（消さない）
  {"action": "open", "case", "section", "item", "prs"}         Waiting で、まだ開いている PR がある項目
  prs は [{"url", "state", "reviewDecision", "isDraft", "reviews": [{"author", "state"}]}]（reviews は人ごとの最新のレビュー）

json の出力:
  {"today": "2026-11-19", "cases": [{"slug", "title", "short", "path",
    "todo": [{"text", "due" (YYYY-MM-DD か null), "bang", "overdue", "today"}]  急ぐ順,
    "waiting": [{"text", "next"}], "later": 件数, "schedule": [{"date", "text"}],
    "workers": [<worker 名>]}]}
  workers は、案件のファイルにリンクのある作業場所（~/hub/workers/<名前>/、.claude/worktrees/<名前>）の名前。
  案件は、期日のある TODO・! の TODO・TODO・Waiting だけ、の順に並べる（同じならファイル名の順）。

gh が失敗したら標準エラーに理由を出して終了コード 2 で終わる。Python の標準ライブラリと gh だけで動かす。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MINE = "TODO"
WAITING = "Waiting"
LATER = "Later"
REFS = "資料"
SCHEDULE = "予定"
TASK_SECTIONS = (MINE, WAITING, LATER, SCHEDULE)
NEXT_SECTIONS = (WAITING, SCHEDULE)  # ` → ` のあとに、済んだらやることを書く節
ARROW = " → "

SHORT_RE = re.compile(r"^略称[:：]\s*(.*)$")
SHORT_WIDTH = 12  # 略称が無いときに見出しを縮める幅
DUE_RE = re.compile(r"\[(\d{1,2})/(\d{1,2})(?:（[^）\]]*）|\([^)\]]*\))?\](?!\()")
BANG_RE = re.compile(r"!(?=\s|$)")
PR_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)")


class GhError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("AGENT_ORCHESTRATOR_HOME") or Path.home() / "hub")


def cases_dir() -> Path:
    env = os.environ.get("AGENT_CASES_DIR")
    return Path(env) if env else home() / "state" / "cases"


# ---------------------------------------------------------------- 案件のファイル


@dataclass(eq=False)  # 同じ文面の項目があっても、消すのは指した 1 つだけ
class Item:
    lines: list[str]

    @property
    def text(self) -> str:
        """`- ` と続きの行の字下げを外して 1 行にしたもの。"""
        first = self.lines[0][2:].strip()
        rest = [line.strip() for line in self.lines[1:]]
        return " ".join([first, *rest]).strip()


@dataclass
class Section:
    name: str
    heading: str | None  # 先頭（見出しの前）は None
    body: list[object] = field(default_factory=list)  # Item か、そのままの行（str）

    @property
    def items(self) -> list[Item]:
        return [b for b in self.body if isinstance(b, Item)]


@dataclass
class Case:
    path: Path
    sections: list[Section]

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def title(self) -> str:
        for b in self.sections[0].body:
            if isinstance(b, str) and b.startswith("# "):
                return b[2:].strip()
        return self.slug

    @property
    def short(self) -> str:
        """TODO の一覧で添える短い名前。`略称:` の行が無ければ見出しを縮める。"""
        for b in self.sections[0].body:
            if isinstance(b, str) and SHORT_RE.match(b):
                name = SHORT_RE.match(b).group(1).strip()
                if name:
                    return name
        return shorten(self.title, SHORT_WIDTH)

    def section(self, name: str) -> Section | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def items(self, name: str) -> list[Item]:
        s = self.section(name)
        return s.items if s else []

    def has_tasks(self) -> bool:
        return any(self.items(n) for n in TASK_SECTIONS)

    def remove(self, section: str, item: Item) -> None:
        s = self.section(section)
        assert s is not None
        s.body.remove(item)

    def add(self, section: str, text: str) -> None:
        s = self.section(section)
        if s is None:
            s = Section(section, f"## {section}", [])
            # 「TODO」は先頭の節にする。ほかは末尾に足す。
            at = 1 if section == MINE else len(self.sections)
            self.sections.insert(at, s)
        # 節の末尾の空行の前に足す。
        at = len(s.body)
        while at > 0 and isinstance(s.body[at - 1], str) and not s.body[at - 1].strip():
            at -= 1
        s.body.insert(at, Item([f"- {text}"]))
        if at == len(s.body) - 1 and s is not self.sections[-1]:
            s.body.append("")

    def dump(self) -> str:
        out: list[str] = []
        for s in self.sections:
            if s.heading is not None:
                out.append(s.heading)
            for b in s.body:
                out.extend(b.lines if isinstance(b, Item) else [b])
        return "\n".join(out).rstrip("\n") + "\n"


def parse(path: Path, text: str | None = None) -> Case:
    if text is None:
        text = path.read_text(encoding="utf-8")
    sections = [Section("", None)]
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append(Section(line[3:].strip(), line))
            continue
        cur = sections[-1]
        if line.startswith("- "):
            cur.body.append(Item([line]))
        elif line.startswith("  ") and line.strip() and cur.body and isinstance(cur.body[-1], Item):
            cur.body[-1].lines.append(line)
        else:
            cur.body.append(line)
    return Case(path, sections)


def load_cases(d: Path) -> list[Case]:
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        try:
            out.append(parse(p))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def write_case(case: Case) -> None:
    tmp = case.path.with_name(f".{case.path.name}.tmp")
    tmp.write_text(case.dump(), encoding="utf-8")
    os.replace(tmp, case.path)


def split_next(text: str) -> tuple[str, str | None]:
    if ARROW in text:
        wait, nxt = text.split(ARROW, 1)
        return wait.strip(), nxt.strip() or None
    return text, None


def pr_urls(text: str) -> list[str]:
    seen = []
    for m in PR_RE.finditer(text):
        url = m.group(0)
        if url not in seen:
            seen.append(url)
    return seen


def guess_date(month: int, day: int, today: dt.date) -> dt.date | None:
    """年の無い月日を、今日にいちばん近い年の日付にする。ありえない日付なら None。"""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            return None
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best




def todo_marks(text: str, today: dt.date) -> tuple[dt.date | None, bool, str]:
    """TODO の項目の先頭の期日 `[11/11]` と印 `!` を読む。(期日, 印, 残りの本文) を返す。"""
    due, bang, rest = None, False, text
    while True:
        rest = rest.lstrip()
        m = DUE_RE.match(rest)
        if m and due is None:
            d = guess_date(int(m.group(1)), int(m.group(2)), today)
            if d is None:
                break
            due, rest = d, rest[m.end() :]
            continue
        m = BANG_RE.match(rest)
        if m and not bang:
            bang, rest = True, rest[m.end() :]
            continue
        break
    return due, bang, rest








def event_date(text: str, today: dt.date) -> dt.date | None:
    return todo_marks(text, today)[0]


# ---------------------------------------------------------------- sweep


def gh_pr_states(urls: list[str]) -> dict[str, dict]:
    """PR の URL ごとに {state, reviewDecision, isDraft, reviews} を返す。読むだけ。"""
    if not urls:
        return {}
    parts = []
    for i, url in enumerate(urls):
        owner, name, number = PR_RE.fullmatch(url).groups()
        parts.append(
            f'p{i}: repository(owner:"{owner}",name:"{name}")'
            f"{{pullRequest(number:{number}){{state reviewDecision isDraft"
            f" latestReviews(first:20){{nodes{{author{{login}} state}}}}}}}}"
        )
    query = "query{" + " ".join(parts) + "}"
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhError(str(e)) from e
    # 見つからない PR があると errors が付くが、data の残りは使える。
    try:
        data = json.loads(res.stdout or "{}").get("data") or {}
    except json.JSONDecodeError as e:
        raise GhError(res.stderr.strip() or str(e)) from e
    if not data and res.returncode != 0:
        raise GhError(res.stderr.strip() or f"gh exited {res.returncode}")
    out = {}
    for i, url in enumerate(urls):
        pr = ((data.get(f"p{i}") or {}).get("pullRequest")) or None
        if pr:
            reviews = (pr.pop("latestReviews", None) or {}).get("nodes") or []
            pr["reviews"] = [
                {"author": (r.get("author") or {}).get("login"), "state": r.get("state")} for r in reviews
            ]
            out[url] = pr
    return out


def closed(pr: dict | None) -> bool:
    return bool(pr) and pr.get("state") in ("MERGED", "CLOSED")


def sweep(d: Path, states_fn=gh_pr_states, dry_run: bool = False, today: dt.date | None = None) -> list[dict]:
    today = today or current_date()
    cases = load_cases(d)
    urls = []
    for c in cases:
        for name in TASK_SECTIONS:
            for it in c.items(name):
                for u in pr_urls(it.text):
                    if u not in urls:
                        urls.append(u)
    states = states_fn(urls)

    actions: list[dict] = []
    for c in cases:
        changed = False
        # 日付が過ぎた予定は済んだものとして消し、` → ` のあとを「TODO」に移す。
        for it in list(c.items(SCHEDULE)):
            date = event_date(it.text, today)
            if date is None or date >= today:
                continue
            text = it.text
            c.remove(SCHEDULE, it)
            a = {"action": "removed", "case": c.slug, "section": SCHEDULE, "item": text}
            _, nxt = split_next(text)
            if nxt:
                c.add(MINE, nxt)
                a["next"] = nxt
            actions.append(a)
            changed = True
        for name in TASK_SECTIONS:
            for it in list(c.items(name)):
                text = it.text
                wait, nxt = split_next(text) if name == WAITING else (text, None)
                # 待ちの判定は ` → ` の前の PR だけで行う。後ろは解けたあとの話。
                urls_ = pr_urls(wait)
                if not urls_:
                    continue
                prs = [{"url": u, **(states.get(u) or {"state": "UNKNOWN"})} for u in urls_]
                all_closed = all(closed(states.get(u)) for u in urls_)
                if name == WAITING and all_closed:
                    c.remove(name, it)
                    a = {"action": "removed", "case": c.slug, "section": name, "item": text}
                    if nxt:
                        c.add(MINE, nxt)
                        a["next"] = nxt
                    actions.append(a)
                    changed = True
                elif all_closed:
                    actions.append({"action": "stale", "case": c.slug, "section": name, "item": text, "prs": prs})
                elif name == WAITING:
                    actions.append({"action": "open", "case": c.slug, "section": name, "item": text, "prs": prs})
        if changed and not dry_run:
            write_case(c)
        if changed and not c.has_tasks():
            if not dry_run:
                archive(c)
            actions.append({"action": "archived", "case": c.slug})
    return actions


def archive(case: Case) -> Path:
    done = case.path.parent / "done"
    done.mkdir(exist_ok=True)
    dest = done / case.path.name
    if dest.exists():
        dest = done / f"{case.path.stem}-{dt.datetime.now():%Y%m%d%H%M%S}.md"
    os.replace(case.path, dest)
    return dest


WORKER_LINK = re.compile(r"(?:/hub/workers|/\.claude/worktrees)/([A-Za-z0-9][A-Za-z0-9._-]*)")


def case_json(case: Case, today: dt.date) -> dict:
    todo = []
    for i, it in enumerate(case.items(MINE)):
        due, bang, text = todo_marks(it.text, today)
        todo.append({"text": text, "due": due.isoformat() if due else None, "bang": bang,
                     "overdue": bool(due and due < today), "today": due == today, "_i": i})
    todo.sort(key=lambda t: (0 if t["due"] else 1 if t["bang"] else 2, t["due"] or "9999", not t["bang"], t["_i"]))
    for t in todo:
        del t["_i"]
    waiting = [dict(zip(("text", "next"), split_next(it.text))) for it in case.items(WAITING)]
    schedule = []
    for it in case.items(SCHEDULE):
        text, _ = split_next(it.text)
        date, _, rest = todo_marks(text, today)
        schedule.append({"date": date.isoformat() if date else None, "text": rest})
    workers = []
    for line in case.dump().splitlines():
        for name in WORKER_LINK.findall(line):
            name = name.removesuffix(".md")
            if name not in workers and name != "report":
                workers.append(name)
    return {"slug": case.slug, "title": case.title, "short": case.short, "path": str(case.path),
            "todo": todo, "waiting": waiting, "later": len(case.items(LATER)), "schedule": schedule,
            "workers": workers}


def cases_json(d: Path, today: dt.date | None = None) -> dict:
    today = today or current_date()
    out = [case_json(c, today) for c in load_cases(d)]

    def rank(c):
        if any(t["due"] for t in c["todo"]):
            return (0, min(t["due"] for t in c["todo"] if t["due"]))
        if any(t["bang"] for t in c["todo"]):
            return (1, "")
        return (2 if c["todo"] else 3 if c["waiting"] else 4, "")

    out.sort(key=lambda c: (rank(c), c["slug"]))
    return {"today": today.isoformat(), "cases": out}


def log(d: Path, slug: str, text: str) -> dict:
    slug = slug.removesuffix(".md")
    if not slug or "/" in slug or slug.startswith("."):
        raise SystemExit(f"cases: 案件の名前ではありません: {slug}")
    path = d / f"{slug}.md"
    if not path.is_file():
        raise SystemExit(f"cases: 案件がありません: {path}")
    line = " ".join("".join(" " if unicodedata.category(c).startswith("C") else c for c in text).split())
    if not line:
        raise SystemExit("cases: 足す文がありません")
    case = parse(path)
    case.add(REFS, line)
    write_case(case)
    return {"action": "logged", "case": slug, "section": REFS, "item": line}


def resolve(d: Path, slug: str, needle: str, section: str = WAITING) -> dict:
    slug = slug.removesuffix(".md")
    path = d / f"{slug}.md"
    if not path.is_file():
        raise SystemExit(f"cases: 案件がありません: {path}")
    case = parse(path)
    hits = [it for it in case.items(section) if needle in it.text]
    if len(hits) != 1:
        raise SystemExit(f"cases: 「{section}」で「{needle}」を含む項目が {len(hits)} 個あります。1 つに絞ってください")
    it = hits[0]
    text = it.text
    case.remove(section, it)
    out = {"action": "removed", "case": slug, "section": section, "item": text}
    if section in NEXT_SECTIONS:
        _, nxt = split_next(text)
        if nxt:
            case.add(MINE, nxt)
            out["next"] = nxt
    write_case(case)
    if not case.has_tasks():
        archive(case)
        out["archived"] = True
    return out


# ---------------------------------------------------------------- board











def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_width(s: str) -> int:
    return sum(char_width(c) for c in s)










# ---------------------------------------------------------------- worker























def current_date() -> dt.date:
    return dt.date.today()



def shorten(text: str, width: int) -> str:
    """幅に収まらなければ、末尾を「…」にして縮める。"""
    if text_width(text) <= width:
        return text
    out, col = "", 0
    for ch in text:
        if col + char_width(ch) > width - 1:
            break
        out += ch
        col += char_width(ch)
    return out.rstrip() + "…"




















# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cases.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sweep")
    s.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("resolve")
    r.add_argument("case")
    r.add_argument("needle")
    r.add_argument("--section", default=WAITING, choices=TASK_SECTIONS)
    sub.add_parser("json")
    lg = sub.add_parser("log")
    lg.add_argument("case")
    lg.add_argument("text")
    args = ap.parse_args(argv)

    d = cases_dir()
    if args.cmd == "sweep":
        try:
            actions = sweep(d, dry_run=args.dry_run)
        except GhError as e:
            print(f"cases: gh が失敗しました: {e}", file=sys.stderr)
            return 2
        for a in actions:
            print(json.dumps(a, ensure_ascii=False))
        return 0
    if args.cmd == "resolve":
        print(json.dumps(resolve(d, args.case, args.needle, args.section), ensure_ascii=False))
        return 0
    if args.cmd == "json":
        print(json.dumps(cases_json(d), ensure_ascii=False))
        return 0
    if args.cmd == "log":
        print(json.dumps(log(d, args.case, args.text), ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
