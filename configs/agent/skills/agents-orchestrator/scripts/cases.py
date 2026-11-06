#!/usr/bin/env python3
"""窓口（orchestrator）の案件の一覧（ケースボード）を扱うスクリプト。

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

    ## 資料
    - [report.md](file:///Users/me/hub/threads/x/report.md)

- 項目は `- ` で始まる行。2 文字以上の字下げで続く行は、前の項目の続き。
- Waiting の項目は ` → ` のあとに、待ちが解けたらやることを書ける。待ちが解けると
  その部分が「TODO」に移る。
- 資料以外の 3 つの節に項目が無くなった案件は done/ に移す（sweep）。

Usage:
  cases.py board [--once] [--width N] [--height N]
      案件の一覧と、その上にスレッドの節（下の「スレッドの節」を参照）を描く。--once が無ければ、
      ファイルの変化と端末の大きさの変化とスレッドの変化（THREAD_POLL 秒ごと）を見て描き直し続ける。
      リンクは OSC 8 で出す（tmux の open-link.sh でクリックして開ける）。
      このスクリプト自身が書き換わったら、自分を起動し直して新しいコードで描く。
  cases.py sweep [--dry-run]
      Waiting の項目のうち、GitHub の PR のリンクがすべて merge・close 済みのものを消す。
      ` → ` のあとがあれば「TODO」に移す。項目が無くなった案件は done/ に移す。
      したことと、残った PR 付きの項目の状態を JSON Lines で出す（下の「出力」を参照）。
  cases.py resolve <案件> <文字列> [--section Waiting]
      節の中で文字列を含む項目を 1 つ消す（2 つ以上・0 個ならエラー）。Waiting なら
      ` → ` のあとを「TODO」に移す。<案件> はファイル名（.md は省略可）。

sweep の出力（1 行に 1 つ）:
  {"action": "removed", "case", "section", "item", "next"?}   消した項目（next は移したもの）
  {"action": "archived", "case"}                               done/ に移した案件
  {"action": "stale", "case", "section", "item", "prs"}        Waiting 以外で、PR がすべて閉じた項目（消さない）
  {"action": "open", "case", "section", "item", "prs"}         Waiting で、まだ開いている PR がある項目
  prs は [{"url", "state", "reviewDecision", "isDraft", "reviews": [{"author", "state"}]}]（reviews は人ごとの最新のレビュー）

スレッドの節:
  `claude agents --json --all` の background のスレッドを、1 つ 1〜2 行で出す（名前・状態・いまの作業）。
  窓口（AGENT_ORCHESTRATOR_NAME、既定は orchestrator）と見張り（chore-hub-watch）は出さない。
  作業の説明は、ジョブの状態ファイル（${CLAUDE_CONFIG_DIR:-~/.claude}/jobs/<id>/state.json）の
  needs（止まったとき）・output.result（終わったとき）・detail を使い、無ければ起動時の依頼の先頭にする。
  claude agents が失敗しても、案件の一覧はそのまま描く。

gh が失敗したら標準エラーに理由を出して終了コード 2 で終わる。Python の標準ライブラリと gh・claude だけで動かす。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MINE = "TODO"
WAITING = "Waiting"
LATER = "Later"
REFS = "資料"
TASK_SECTIONS = (MINE, WAITING, LATER)
ARROW = " → "

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


def sweep(d: Path, states_fn=gh_pr_states, dry_run: bool = False) -> list[dict]:
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
    if section == WAITING:
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

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
STYLE = {
    "title": "\x1b[1;38;2;192;202;245m",  # fg
    MINE: "\x1b[1;38;2;224;175;104m",  # yellow
    WAITING: "\x1b[1;38;2;125;207;255m",  # cyan
    LATER: "\x1b[1;38;2;158;206;106m",  # green
    REFS: "\x1b[38;2;86;95;137m",  # comment
    "other": "\x1b[1;38;2;169;177;214m",
    "text": "\x1b[38;2;169;177;214m",
    "dim": "\x1b[38;2;86;95;137m",
    "link": "\x1b[4;38;2;122;162;247m",
    "code": "\x1b[38;2;187;154;247m",
}
LABEL = {MINE: "▶ TODO", WAITING: "◇ Waiting", LATER: "・Later", REFS: "資料"}

# スレッドの状態ごとの (印, 名前, 色)。窓口の番は TODO と、動いているは Waiting とそろえる。
THREAD_STATE = {
    "blocked": ("▶", "窓口の番", STYLE[MINE]),
    "dialog": ("▶", "確認ダイアログ", STYLE[MINE]),
    "working": ("●", "動いている", STYLE[WAITING]),
    "done": ("✓", "終わった", STYLE["dim"]),
}
THREAD_ORDER = ("dialog", "blocked", "working")  # これ以外（done など）は後ろ
THREADS_TITLE = "スレッド"

INLINE_RE = re.compile(
    r"\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)\)"  # [text](url)
    r"|`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>[^*]+)\*\*"
    r"|(?P<url>https?://[^\s)]+)"
    r"|(?P<ticket>\b[A-Z][A-Z0-9]+-\d+\b)"
)


def jira_base() -> str | None:
    try:
        conf = json.loads((home() / "pane.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    base = conf.get("jira") if isinstance(conf, dict) else None
    return base if isinstance(base, str) and base else None


def inline(text: str, style: str, jira: str | None) -> list[tuple[str, str, str | None]]:
    """Markdown の行内を (文字列, 色, リンク先) の並びにする。"""
    out: list[tuple[str, str, str | None]] = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos : m.start()], style, None))
        if m.group("lt") is not None:
            out.append((m.group("lt"), STYLE["link"], m.group("lu")))
        elif m.group("code") is not None:
            out.append((m.group("code"), STYLE["code"], None))
        elif m.group("bold") is not None:
            out.append((m.group("bold"), style + BOLD, None))
        elif m.group("url") is not None:
            url = m.group("url")
            out.append((short_url(url), STYLE["link"], url))
        elif jira:
            out.append((m.group("ticket"), STYLE["link"], jira + m.group("ticket")))
        else:
            out.append((m.group("ticket"), style, None))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], style, None))
    return out


def short_url(url: str) -> str:
    m = PR_RE.match(url)
    if m:
        return f"{m.group(2)}#{m.group(3)}"
    rest = re.sub(r"^\w+://", "", url)
    return rest if len(rest) <= 40 else rest[:39] + "…"


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_width(s: str) -> int:
    return sum(char_width(c) for c in s)


def wrap(segs, width: int, indent: int, hang: int) -> list[list[tuple[str, str, str | None]]]:
    """文字単位で折り返す。1 行目は indent、2 行目からは hang だけ字下げする。"""
    lines: list[list[tuple[str, str, str | None]]] = [[(" " * indent, "", None)]]
    col = indent
    for text, style, url in segs:
        buf = ""
        for ch in text:
            w = char_width(ch)
            if col + w > width and col > hang:
                if buf:
                    lines[-1].append((buf, style, url))
                    buf = ""
                lines.append([(" " * hang, "", None)])
                col = hang
                if ch == " ":
                    continue
            buf += ch
            col += w
        if buf:
            lines[-1].append((buf, style, url))
    return lines


def paint(line: list[tuple[str, str, str | None]]) -> str:
    out = []
    for text, style, url in line:
        if not text:
            continue
        s = f"{style}{text}{RESET}" if style else text
        if url:
            s = f"\x1b]8;;{url}\x1b\\{s}\x1b]8;;\x1b\\"
        out.append(s)
    return "".join(out)


def sort_key(case: Case):
    try:
        mtime = case.path.stat().st_mtime
    except OSError:
        mtime = 0
    return (0 if case.items(MINE) else 1, -mtime)


def case_rows(cases: list[Case], width: int, jira: str | None, level: int):
    """案件の部分の行。level が上がるほど畳む。
    1: 資料を出さない  2: Later を件数だけにする  3: Waiting の ` → ` のあとを出さない
    """
    rows: list[list[tuple[str, str, str | None]]] = []
    for i, c in enumerate(cases):
        if i:
            rows.append([])
        rows.extend(wrap([(c.title, STYLE["title"], c.path.as_uri())], width, 0, 2))
        for s in c.sections[1:]:
            items = s.items
            if not items:
                continue
            if s.name == REFS:
                if level >= 1:
                    continue
                segs = [(LABEL[REFS] + ": ", STYLE[REFS], None)]
                for j, it in enumerate(items):
                    if j:
                        segs.append((" / ", STYLE["dim"], None))
                    segs.extend(inline(it.text, STYLE["dim"], jira))
                rows.extend(wrap(segs, width, 1, 3))
                continue
            label = LABEL.get(s.name, s.name)
            style = STYLE.get(s.name, STYLE["other"])
            if s.name == LATER and level >= 2:
                rows.append([(" ", "", None), (f"{label} {len(items)} 件", style, c.path.as_uri())])
                continue
            rows.append([(" ", "", None), (label, style, None)])
            for it in items:
                segs = [("• ", STYLE["dim"], None)]
                text = it.text
                wait, nxt = split_next(text) if s.name == WAITING else (text, None)
                segs.extend(inline(wait, STYLE["text"], jira))
                if nxt and level < 3:
                    segs.append((ARROW, STYLE["dim"], None))
                    segs.extend(inline(nxt, STYLE["dim"], jira))
                rows.extend(wrap(segs, width, 3, 5))
    return rows


# ---------------------------------------------------------------- スレッド

THREAD_POLL = 5  # 秒。claude agents は 0.2 秒ほどで返るが、毎秒は呼ばない
HIDDEN_THREADS = ("chore-hub-watch",)


@dataclass(frozen=True)
class Thread:
    name: str
    state: str  # THREAD_STATE のキーか、claude agents の state のまま
    summary: str
    cwd: str | None = None
    started: int = 0


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def job_state(job_id: str | None) -> dict:
    """ジョブの状態ファイル。Claude Code の内部のファイルなので、読めなければ空にする。"""
    if not job_id or "/" in job_id:
        return {}
    try:
        data = json.loads((claude_dir() / "jobs" / job_id / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def one_line(text) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


def thread_summary(state: str, job: dict) -> str:
    output = job.get("output")
    result = output.get("result") if isinstance(output, dict) else None
    order = {"blocked": ("needs",), "done": ("result",)}.get(state, ())
    for key in (*order, "detail"):
        text = one_line(result if key == "result" else job.get(key))
        if text:
            return text
    intent = one_line(job.get("intent"))
    if intent.startswith("/"):  # 先頭のスキル（/agents-thread）は飛ばす
        intent = intent.partition(" ")[2]
    return intent


def parse_threads(agents, job_state_fn=job_state) -> list[Thread]:
    """`claude agents --json --all` の出力から、出すスレッドを並べる。"""
    hidden = {os.environ.get("AGENT_ORCHESTRATOR_NAME") or "orchestrator", *HIDDEN_THREADS}
    threads = []
    for a in agents if isinstance(agents, list) else []:
        if not isinstance(a, dict) or a.get("kind") != "background":
            continue
        name = a.get("name") or a.get("id") or "?"
        if name in hidden:
            continue
        state = a.get("state") or a.get("status") or "?"
        job = job_state_fn(a.get("id"))
        summary = thread_summary(state, job)
        if a.get("waitingFor"):
            state = "dialog"
            summary = f"{a['waitingFor']}: {summary}" if summary else a["waitingFor"]
        started = a.get("startedAt")
        threads.append(
            Thread(name, state, summary, a.get("cwd"), started if isinstance(started, int) else 0)
        )
    rank = {s: i for i, s in enumerate(THREAD_ORDER)}
    threads.sort(key=lambda t: (rank.get(t.state, len(rank)), -t.started))
    return threads


def fetch_threads() -> list[Thread] | None:
    """いまのスレッド。claude agents が呼べなければ None。"""
    claude = shutil.which("claude")
    if not claude:
        return None
    try:
        proc = subprocess.run(
            [claude, "agents", "--json", "--all"], capture_output=True, text=True, timeout=10, check=False
        )
        if proc.returncode != 0:
            return None
        return parse_threads(json.loads(proc.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def clip(segs, width: int, indent: int) -> list[tuple[str, str, str | None]]:
    """1 行に収まらなければ、末尾を「…」にして切る。"""
    lines = wrap(segs, width, indent, indent)
    if len(lines) == 1:
        return lines[0]
    line, col = [], 0
    for text, style, url in lines[0]:
        buf = ""
        for ch in text:
            if col + char_width(ch) > width - 1:
                break
            buf += ch
            col += char_width(ch)
        if buf:
            line.append((buf, style, url))
        if col >= width - 1 or len(buf) < len(text):
            break
    line.append(("…", STYLE["dim"], None))
    return line


def thread_rows(threads: list[Thread] | None, width: int, jira: str | None, level: int):
    """スレッドの節の行。level 1 で、終わったスレッドの説明を出さない。"""
    if threads is None:
        return [[(f"{THREADS_TITLE}: claude agents を読めませんでした", STYLE["dim"], None)]]
    if not threads:
        return []
    rows = [[(THREADS_TITLE, STYLE["title"], None)]]
    for t in threads:
        mark, label, style = THREAD_STATE.get(t.state, ("・", t.state, STYLE["dim"]))
        done = t.state not in THREAD_ORDER
        url = Path(t.cwd).as_uri() if t.cwd and t.cwd.startswith("/") else None
        rows.append(
            clip(
                [
                    (f"{mark} ", style, None),
                    (t.name, STYLE["dim"] if done else STYLE["text"], url),
                    (" " + label, style, None),
                ],
                width,
                1,
            )
        )
        if t.summary and not (done and level >= 1):
            rows.append(clip(inline(t.summary, STYLE["dim"], jira), width, 3))
    rows.append([])
    return rows


def render(d: Path, width: int, height: int, threads: list[Thread] | None = ()) -> list[str]:
    """スレッドの節と案件の一覧を描く。見出しや区切り線は出さない。
    threads が空ならスレッドの節を出さず、1 行目から案件にする。None は読めなかったとき。"""
    width = max(width, 20)
    jira = jira_base()
    cases = sorted(load_cases(d), key=sort_key)
    empty = [[("案件はありません", STYLE["dim"], None)]] if not cases else []

    # 入りきらなければ、資料、Later、終わったスレッドの説明、Waiting の次の手、の順に畳む。
    for t_level, c_level in ((0, 0), (0, 1), (0, 2), (1, 2), (1, 3)):
        head = thread_rows(threads, width, jira, t_level) + empty
        body = case_rows(cases, width, jira, c_level)
        if len(head) + len(body) <= height:
            break
    rows = head + body

    if len(rows) > height:
        hidden = len(rows) - (height - 1)
        rows = rows[: height - 1]
        rows.append([(f"… ほか {hidden} 行", STYLE["dim"], d.as_uri() if d.is_dir() else None)])
    return [paint(r) for r in rows]


def signature(d: Path) -> tuple:
    sig = []
    for p in [home() / "pane.json", *(sorted(d.glob("*.md")) if d.is_dir() else [])]:
        try:
            st = p.stat()
            sig.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(sig)


def code_signature() -> tuple | None:
    """このスクリプト自身の状態。動いている board が古いコードのまま描き続けないように見る。"""
    try:
        st = Path(__file__).resolve().stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def board(d: Path, once: bool, width: int | None, height: int | None) -> int:
    def size():
        ts = shutil.get_terminal_size((60, 30))
        return width or ts.columns, height or ts.lines

    if once:
        w, h = size()
        sys.stdout.write("\n".join(render(d, w, h, fetch_threads())) + "\n")
        return 0

    resized = [True]
    signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
    out = sys.stdout
    out.write("\x1b[?25l")  # カーソルを隠す
    last = None
    code = seen = code_signature()
    threads, polled = None, None
    try:
        while True:
            now_code = code_signature()
            # 書き換えの途中で読まないよう、変わったあと 1 秒落ち着いてから起動し直す。
            if now_code is not None and now_code != code and now_code == seen:
                out.write("\x1b[?25h")
                out.flush()
                os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
            seen = now_code
            w, h = size()
            if polled is None or time.monotonic() - polled >= THREAD_POLL:
                threads, polled = fetch_threads(), time.monotonic()
            key = (signature(d), w, h, threads)
            if key != last or resized[0]:
                resized[0] = False
                last = key
                try:
                    lines = render(d, w, h, threads)
                except Exception as e:  # 描けなくてもペインは閉じない
                    lines = [f"cases: 描けませんでした: {e}"]
                out.write("\x1b[H\x1b[2J" + "\r\n".join(lines))
                out.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        out.write("\x1b[?25h")
        out.flush()


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cases.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("board")
    b.add_argument("--once", action="store_true")
    b.add_argument("--width", type=int)
    b.add_argument("--height", type=int)
    s = sub.add_parser("sweep")
    s.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("resolve")
    r.add_argument("case")
    r.add_argument("needle")
    r.add_argument("--section", default=WAITING, choices=TASK_SECTIONS)
    args = ap.parse_args(argv)

    d = cases_dir()
    if args.cmd == "board":
        return board(d, args.once, args.width, args.height)
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
