#!/usr/bin/env python3
"""窓口（hub）の状況と資料をブラウザで見るための、ローカル web ダッシュボード。

- 127.0.0.1 だけで待ち受ける。Host ヘッダーも確かめ、DNS rebinding で外のページから読まれないようにする
- ~/hub（AGENT_HUB_HOME）と記録ファイル（$XDG_STATE_HOME/agent-hub）は読むだけで、書き換えない
- 書き込むのは受信箱だけ。worker の報告（$XDG_STATE_HOME/agent-hub/reports/<セッション名>.md）に答えると、
  その worker の tmux pane へ send-keys で送り、報告のファイルに「回答」を追記する。
  POST は起動ごとに作るトークンと同じ origin を必須にし、送り先は記録ファイルがある worker の window に限る
- Python の標準ライブラリだけで動かす。markdown の整形は、手元の資料が読める程度の GFM の一部を自前で扱う
  （外部パッケージを入れずに macOS と Ubuntu の両方で `python3` だけで起動できるようにするため）

Usage: dash.py [--port PORT] [--interval SECONDS] [--open]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 8765
DOC_DIRS = ("notes", "minutes", "gtd")
GTD_FILES = ("inbox", "next-actions", "waiting-for", "projects", "someday", "done")
PR_CACHE_SECONDS = 60


def hub_home() -> Path:
    return Path(os.environ.get("AGENT_HUB_HOME") or Path.home() / "hub").expanduser()


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base).expanduser() / "agent-hub"


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------
# GTD の行

ATTR_RE = re.compile(r"(?:^|\s)([A-Za-z][\w-]*)::(?=\s|$)")
ITEM_RE = re.compile(r"^- \[(.)\] (.*)$")


@dataclass
class Item:
    file: str
    state: str  # " " 未完了 / "x" 完了 / "-" 取り消し
    body: str
    attrs: dict[str, str]
    sub: list[str] = field(default_factory=list)
    section: str = ""

    @property
    def open(self) -> bool:
        return self.state == " "

    @property
    def doing(self) -> bool:
        return self.open and ("worker" in self.attrs or "doing" in self.attrs)


def split_attrs(text: str) -> tuple[str, dict[str, str]]:
    matches = list(ATTR_RE.finditer(text))
    if not matches:
        return text.strip(), {}
    attrs: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        attrs[m.group(1)] = text[m.end() : end].strip()
    return text[: matches[0].start()].strip(), attrs


def parse_gtd(text: str, file: str) -> list[Item]:
    items: list[Item] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = ITEM_RE.match(line)
        if m:
            body, attrs = split_attrs(m.group(2))
            items.append(Item(file, m.group(1), body, attrs, section=section))
        elif items and line[:1] in (" ", "\t") and line.strip():
            items[-1].sub.append(line.strip().removeprefix("- "))
    return items


def load_gtd(home: Path) -> dict[str, list[Item]]:
    out = {}
    for name in GTD_FILES:
        path = home / "gtd" / f"{name}.md"
        try:
            out[name] = parse_gtd(path.read_text(encoding="utf-8"), name)
        except OSError:
            out[name] = []
    return out


# ---------------------------------------------------------------------------
# markdown（GFM の一部：見出し、段落、リスト、タスク、表、コード、引用、リンク、強調）

INLINE_RE = re.compile(
    r"(?P<code>`+)(?P<codetext>.+?)(?P=code)"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<lurl>[^)\s]+)\)"
    r"|(?P<auto>https?://[^\s<>()\[\]]+[^\s<>()\[\].,:;!?、。）」])"
    r"|\*\*(?P<strong>.+?)\*\*"
    r"|~~(?P<del>.+?)~~"
    r"|(?<![\w*])\*(?P<em>[^*\s][^*]*?)\*(?![\w*])"
)


class Renderer:
    """markdown を HTML にする。base は資料の hub からの相対パスで、相対リンクの解決に使う。"""

    def __init__(self, base: str = ""):
        self.base = base

    def href(self, url: str) -> tuple[str, bool] | None:
        """(href, 外部か) を返す。javascript: などは None。"""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme in ("http", "https", "mailto"):
            return url, True
        if parsed.scheme or url.startswith("//"):
            return None
        if url.startswith("#"):
            return url, False
        path = urllib.parse.unquote(parsed.path)
        if path.startswith("~/") or path.startswith("/"):
            return None
        joined = os.path.normpath(os.path.join(os.path.dirname(self.base), path))
        frag = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"/doc?path={urllib.parse.quote(joined)}{frag}", False

    def link(self, label_html: str, url: str) -> str:
        resolved = self.href(url)
        if resolved is None:
            return f"{label_html} <span class=muted>({esc(url)})</span>"
        href, external = resolved
        extra = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return f'<a href="{esc(href)}"{extra}>{label_html}</a>'

    def inline(self, text: str) -> str:
        out = []
        pos = 0
        for m in INLINE_RE.finditer(text):
            out.append(esc(text[pos : m.start()]))
            pos = m.end()
            if m.group("code"):
                out.append(f"<code>{esc(m.group('codetext').strip())}</code>")
            elif m.group("ltext") is not None:
                out.append(self.link(self.inline(m.group("ltext")), m.group("lurl")))
            elif m.group("auto"):
                out.append(self.link(esc(m.group("auto")), m.group("auto")))
            elif m.group("strong") is not None:
                out.append(f"<strong>{self.inline(m.group('strong'))}</strong>")
            elif m.group("del") is not None:
                out.append(f"<del>{self.inline(m.group('del'))}</del>")
            elif m.group("em") is not None:
                out.append(f"<em>{self.inline(m.group('em'))}</em>")
        out.append(esc(text[pos:]))
        return "".join(out)

    def render(self, text: str) -> str:
        lines = text.replace("\t", "    ").splitlines()
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
            elif stripped.startswith("```") or stripped.startswith("~~~"):
                i = self._code(lines, i, out)
            elif m := re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped):
                level = len(m.group(1))
                slug = re.sub(r"\s+", "-", m.group(2).strip().lower())
                out.append(f'<h{level} id="{esc(slug)}">{self.inline(m.group(2))}</h{level}>')
                i += 1
            elif re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", stripped):
                out.append("<hr>")
                i += 1
            elif stripped.startswith(">"):
                block = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    block.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                out.append(f"<blockquote>{self.render(chr(10).join(block))}</blockquote>")
            elif LIST_RE.match(line):
                i = self._list(lines, i, out)
            elif "|" in line and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
                i = self._table(lines, i, out)
            else:
                para = []
                while i < len(lines) and lines[i].strip() and not self._starts_block(lines, i):
                    para.append(lines[i].strip())
                    i += 1
                if not para:  # 念のため無限ループを避ける
                    para.append(lines[i].strip())
                    i += 1
                out.append(f"<p>{'<br>'.join(self.inline(p) for p in para)}</p>")
        return "\n".join(out)

    @staticmethod
    def _starts_block(lines: list[str], i: int) -> bool:
        s = lines[i].strip()
        return bool(
            s.startswith(("```", "~~~", "#", ">"))
            or LIST_RE.match(lines[i])
            or ("|" in s and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]))
        )

    def _code(self, lines: list[str], i: int, out: list[str]) -> int:
        fence = lines[i].strip()[:3]
        lang = lines[i].strip()[3:].strip()
        i += 1
        body = []
        while i < len(lines) and not lines[i].strip().startswith(fence):
            body.append(lines[i])
            i += 1
        cls = f' class="lang-{esc(lang)}"' if lang else ""
        out.append(f"<pre><code{cls}>{esc(chr(10).join(body))}</code></pre>")
        return i + 1

    def _table(self, lines: list[str], i: int, out: list[str]) -> int:
        header = split_row(lines[i])
        aligns = []
        for cell in split_row(lines[i + 1]):
            c = cell.strip()
            aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "")
        i += 2
        rows = []
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            rows.append(split_row(lines[i]))
            i += 1

        def cell(tag: str, text: str, col: int) -> str:
            align = aligns[col] if col < len(aligns) else ""
            cls = f' class="al-{align}"' if align else ""
            return f"<{tag}{cls}>{self.inline(text)}</{tag}>"

        head = "".join(cell("th", c, n) for n, c in enumerate(header))
        body = "".join(
            "<tr>" + "".join(cell("td", c, n) for n, c in enumerate(r)) + "</tr>" for r in rows
        )
        out.append(f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
        return i

    def _list(self, lines: list[str], i: int, out: list[str]) -> int:
        stack: list[tuple[int, str]] = []  # (字下げ, タグ)
        html_parts: list[str] = []
        while i < len(lines):
            line = lines[i]
            m = LIST_RE.match(line)
            if not line.strip():
                # 空行の次が字下げされた行かリストなら続ける
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and (LIST_RE.match(lines[j]) or lines[j].startswith("  ")):
                    i = j
                    continue
                break
            if m:
                indent = len(m.group(1))
                tag = "ol" if m.group(2)[0].isdigit() else "ul"
                while stack and indent < stack[-1][0]:
                    html_parts.append(f"</li></{stack.pop()[1]}>")
                if not stack or indent > stack[-1][0]:
                    stack.append((indent, tag))
                    html_parts.append(f"<{tag}><li>")
                else:
                    if stack[-1][1] != tag:
                        html_parts.append(f"</li></{stack.pop()[1]}><{tag}><li>")
                        stack.append((indent, tag))
                    else:
                        html_parts.append("</li><li>")
                content = m.group(3)
                task = re.match(r"^\[(.)\]\s+(.*)$", content)
                if task:
                    mark = {" ": "☐", "x": "☑", "X": "☑", "-": "☒"}.get(task.group(1), "☐")
                    cls = "" if task.group(1) == " " else ' class="done"'
                    html_parts.append(f'<span class="check">{mark}</span> <span{cls}>{self.inline(task.group(2))}</span>')
                else:
                    html_parts.append(self.inline(content))
                i += 1
            elif line.startswith(" ") and stack:
                s = line.strip()
                if s.startswith("```") or s.startswith("~~~"):
                    sub: list[str] = []
                    i = self._code([l[stack[-1][0] + 2 :] if l.strip() else l for l in lines], i, sub)
                    html_parts.extend(sub)
                else:
                    html_parts.append("<br>" + self.inline(s))
                    i += 1
            else:
                break
        while stack:
            html_parts.append(f"</li></{stack.pop()[1]}>")
        out.append("".join(html_parts))
        return i


LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


# ---------------------------------------------------------------------------
# worker（記録ファイル、tmux、gh）

HEADER_KEYS = {
    "窓口（hub）のセッション名": "hub",
    "あなたのセッション名": "name",
    "作業場所": "worktree",
    "作業ブランチ": "branch",
}


@dataclass
class Worker:
    name: str
    path: Path
    mtime: float
    text: str
    worktree: str = ""
    branch: str = ""
    repo: str = ""
    window: dict | None = None
    item: Item | None = None


def parse_record(path: Path) -> Worker:
    text = path.read_text(encoding="utf-8", errors="replace")
    w = Worker(name=path.stem, path=path, mtime=path.stat().st_mtime, text=text)
    for line in text.splitlines()[:10]:
        key, sep, value = line.partition(":")
        if sep and key.strip() in HEADER_KEYS:
            attr = HEADER_KEYS[key.strip()]
            if attr != "hub":
                setattr(w, attr, value.strip())
    w.name = w.name or path.stem
    return w


def run_full(cmd: list[str], cwd: str | None = None, timeout: float = 10) -> tuple[str | None, str]:
    """(成功時の標準出力, 失敗理由) を返す。"""
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{type(e).__name__}: {e}"
    if res.returncode != 0:
        return None, (res.stderr.strip().splitlines() or [f"exit {res.returncode}"])[0]
    return res.stdout, ""


def run(cmd: list[str], cwd: str | None = None, timeout: float = 10) -> str | None:
    return run_full(cmd, cwd, timeout)[0]


def github_repo(remote_url: str) -> str:
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote_url.strip())
    return m.group(1) if m else ""


def tmux_windows() -> dict[str, dict]:
    """@agent-hub-worker の印が付いた window を worker のセッション名ごとに返す。pane は window の現在の pane。"""
    fmt = "#{window_id}\t#{@agent-hub-worker}\t#{window_name}\t#{session_name}\t#{pane_id}"
    out = run(["tmux", "list-windows", "-a", "-F", fmt])
    windows = {}
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 5 and parts[1]:
            windows[parts[1]] = {"id": parts[0], "name": parts[2], "session": parts[3], "pane": parts[4]}
    return windows


class PRCache:
    """gh の結果を (repo, branch) ごとに覚えておく。取得は裏で行い、ページの表示を待たせない。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.data: dict[tuple[str, str], tuple[float, dict | None]] = {}
        self.pending: set[tuple[str, str]] = set()
        self.pool = ThreadPoolExecutor(max_workers=4)

    def get(self, repo: str, branch: str) -> tuple[bool, dict | None]:
        """(取得済みか, PR) を返す。古ければ取り直しを始める。"""
        key = (repo, branch)
        with self.lock:
            entry = self.data.get(key)
            stale = entry is None or time.time() - entry[0] > PR_CACHE_SECONDS
            if stale and key not in self.pending:
                self.pending.add(key)
                self.pool.submit(self._fetch, key)
        return (entry is not None, entry[1] if entry else None)

    def _fetch(self, key: tuple[str, str]) -> None:
        repo, branch = key
        fields = "number,title,url,state,isDraft,statusCheckRollup,updatedAt"
        out, err = run_full(["gh", "pr", "list", "-R", repo, "--head", branch, "--state", "all", "--json", fields, "--limit", "5"], timeout=30)
        pr: dict | None = {"error": err}
        if out is not None:
            try:
                prs = json.loads(out)
            except json.JSONDecodeError:
                prs = []
            prs.sort(key=lambda p: (p.get("state") != "OPEN", -(p.get("number") or 0)))
            pr = prs[0] if prs else {"none": True}
        with self.lock:
            self.data[key] = (time.time(), pr)
            self.pending.discard(key)


PR_CACHE = PRCache()


def ci_summary(rollup: list[dict] | None) -> tuple[str, str]:
    """(表示, クラス) を返す。"""
    if not rollup:
        return "CI なし", "muted"
    ok = fail = pending = 0
    for c in rollup:
        if c.get("__typename") == "StatusContext":
            state = c.get("state", "")
            if state == "SUCCESS":
                ok += 1
            elif state in ("FAILURE", "ERROR"):
                fail += 1
            else:
                pending += 1
            continue
        if c.get("status") != "COMPLETED":
            pending += 1
        elif c.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            ok += 1
        else:
            fail += 1
    if fail:
        return f"CI 失敗 {fail}/{ok + fail + pending}", "bad"
    if pending:
        return f"CI 実行中 {pending}/{ok + pending}", "warn"
    return f"CI 成功 {ok}", "good"


def load_workers(gtd: dict[str, list[Item]]) -> list[Worker]:
    by_worker = {}
    for name in GTD_FILES:
        for it in gtd.get(name, []):
            if "worker" in it.attrs:
                by_worker.setdefault(it.attrs["worker"], it)
    windows = tmux_windows()
    workers = []
    try:
        paths = sorted(state_dir().glob("*.md"))
    except OSError:
        paths = []
    for path in paths:
        try:
            w = parse_record(path)
        except OSError:
            continue
        w.window = windows.get(w.name)
        w.item = by_worker.get(w.name)
        if w.worktree and Path(w.worktree).is_dir():
            if not w.branch:
                w.branch = (run(["git", "branch", "--show-current"], cwd=w.worktree) or "").strip()
            w.repo = github_repo(run(["git", "remote", "get-url", "origin"], cwd=w.worktree) or "")
        if not w.repo and w.item:
            w.repo = w.item.attrs.get("repo", "")
        workers.append(w)
    workers.sort(key=lambda w: (w.window is None, -w.mtime))
    return workers


# ---------------------------------------------------------------------------
# 受信箱（worker の報告と、ダッシュボードからの回答）
#
# 報告のファイルは worker ごとに 1 つで、worker（report.sh）とダッシュボードが追記する。各項目は
#   ## <YYYY-MM-DD HH:MM:SS> <完了|要判断|ブロック>
#   ## <YYYY-MM-DD HH:MM:SS> <回答|対応済み> <答えた報告の時刻>
# の見出しで始まり、次の見出しまでが本文。報告の時刻が、その worker の中での報告の ID になる。

TS = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d"
REPORT_HEAD_RE = re.compile(rf"^## ({TS}) (完了|要判断|ブロック|回答|対応済み)(?: ({TS}))?\s*$")
REPORT_KINDS = ("完了", "要判断", "ブロック")
ASK_KINDS = ("要判断", "ブロック")
ANSWER_KINDS = ("回答", "対応済み")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CHOICE_RE = re.compile(r"^\s*(?:[-*]\s+)?選択肢[:：]\s*(.+?)\s*$")
MAX_ANSWER = 1000
MAX_FORM_BYTES = 16 * 1024
ANSWER_PREFIX = "[ダッシュボードから回答 {ref}] "
# Unicode の双方向制御文字。表示と実際の並びを食い違わせられるので落とす
BIDI_CONTROLS = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f")
# 許可などの確認画面。ここに文字と Enter を送ると選択肢を選んでしまうので、送らない
DIALOG_RE = re.compile(r"Do you want to|Esc to cancel|❯\s*\d+\.\s|\(y/n\)", re.IGNORECASE)


def reports_dir() -> Path:
    return state_dir() / "reports"


@dataclass
class Report:
    worker: str
    ts: str
    kind: str
    body: str
    ref: str = ""
    answers: list["Report"] = field(default_factory=list)
    superseded: bool = False  # 後に同じ worker から完了が届いた

    @property
    def summary(self) -> str:
        return next((l.strip() for l in self.body.splitlines() if l.strip()), "")

    @property
    def is_open(self) -> bool:
        return self.kind in ASK_KINDS and not self.answers and not self.superseded

    @property
    def choices(self) -> list[str]:
        out = []
        for line in self.body.splitlines():
            m = CHOICE_RE.match(line)
            if m and len(m.group(1)) <= MAX_ANSWER:
                out.append(m.group(1))
        return out


def parse_reports(text: str, worker: str) -> list[Report]:
    """報告と回答を出てきた順に返す。回答は答えた報告の answers にもつなぐ。"""
    entries: list[Report] = []
    body: list[str] = []

    def flush():
        if entries:
            entries[-1].body = "\n".join(body).strip("\n")
        body.clear()

    for line in text.splitlines():
        m = REPORT_HEAD_RE.match(line)
        if m:
            flush()
            entries.append(Report(worker, m.group(1), m.group(2), "", m.group(3) or ""))
        elif entries:
            body.append(line)
    flush()

    by_ts: dict[str, Report] = {}
    for e in entries:
        if e.kind in REPORT_KINDS:
            if e.kind == "完了":
                for prev in by_ts.values():
                    prev.superseded = True
            by_ts[e.ts] = e
        elif e.kind in ANSWER_KINDS and e.ref in by_ts:
            by_ts[e.ref].answers.append(e)
    return entries


def record_names() -> set[str]:
    """記録ファイルがある worker のセッション名。送り先はこの中に限る。"""
    try:
        return {p.stem for p in state_dir().glob("*.md") if p.is_file() and NAME_RE.match(p.stem)}
    except OSError:
        return set()


def load_reports() -> list[Report]:
    out: list[Report] = []
    try:
        paths = sorted(reports_dir().glob("*.md"))
    except OSError:
        return out
    for path in paths:
        if not NAME_RE.match(path.stem):
            continue
        try:
            out.extend(parse_reports(path.read_text(encoding="utf-8", errors="replace"), path.stem))
        except OSError:
            continue
    return out


def clean_answer(text: str) -> str:
    """改行とタブは空白に、ほかの制御文字と双方向制御文字は落とす。"""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc" and ch not in BIDI_CONTROLS)
    return text.strip()


def append_report(path: Path, kind: str, ref: str, body: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {now} {kind} {ref}\n\n{body}\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(entry)


def capture_pane(pane: str) -> str:
    return run(["tmux", "capture-pane", "-p", "-t", pane]) or ""


def send_to_pane(pane: str, text: str) -> bool:
    """文字列をそのまま打ち込んでから Enter を送る。続けて送ると貼り付けと見なされ、改行になることがあるので間を置く。"""
    if run(["tmux", "send-keys", "-t", pane, "-l", "--", text]) is None:
        return False
    time.sleep(0.3)
    return run(["tmux", "send-keys", "-t", pane, "Enter"]) is not None


def looks_like_dialog(window: dict) -> bool:
    if "🔴" in window.get("name", ""):
        return True
    lines = [l for l in capture_pane(window["pane"]).splitlines() if l.strip()]
    return bool(DIALOG_RE.search("\n".join(lines[-15:])))


ANSWER_MESSAGES = {
    "sent": ("送りました。worker の画面で受け取られたか確かめてください", "good"),
    "resolved": ("送らずに対応済みにしました", "good"),
    "unknown": ("記録ファイルにない worker には送れません", "bad"),
    "stale": ("その報告は見つからないか、すでに対応済みです", "bad"),
    "empty": ("答えが空です", "bad"),
    "toolong": (f"答えは {MAX_ANSWER} 文字までです", "bad"),
    "nowindow": ("worker の window がありません。window で答えるか、対応済みにしてください", "bad"),
    "dialog": ("worker が確認画面を出しているので送りませんでした。window で答えてください", "bad"),
    "sendfail": ("tmux で送れませんでした", "bad"),
    "writefail": ("送りましたが、報告のファイルに書き込めませんでした", "bad"),
}

ANSWER_LOCK = threading.Lock()


def answer_report(worker: str, ref: str, action: str, text: str) -> str:
    """報告に答える。結果を ANSWER_MESSAGES のキーで返す。"""
    with ANSWER_LOCK:  # 同じ報告へ二重に送らない
        if not NAME_RE.match(worker) or worker not in record_names():
            return "unknown"
        path = reports_dir() / f"{worker}.md"
        try:
            reports = parse_reports(path.read_text(encoding="utf-8", errors="replace"), worker)
        except OSError:
            return "stale"
        if not any(r.ts == ref and r.is_open for r in reports):
            return "stale"
        if action == "resolve":
            try:
                append_report(path, "対応済み", ref, "（ダッシュボードで、送らずに対応済みにした）")
            except OSError:
                return "writefail"
            return "resolved"
        if action != "send":
            return "stale"
        text = clean_answer(text)
        if not text:
            return "empty"
        if len(text) > MAX_ANSWER:
            return "toolong"
        window = tmux_windows().get(worker)
        if not window:
            return "nowindow"
        if looks_like_dialog(window):
            return "dialog"
        if not send_to_pane(window["pane"], ANSWER_PREFIX.format(ref=ref) + text):
            return "sendfail"
        try:
            append_report(path, "回答", ref, text)
        except OSError:
            return "writefail"
        return "sent"


# ---------------------------------------------------------------------------
# 画面

def worker_anchor(name: str) -> str:
    return "w-" + re.sub(r"[^\w-]", "_", name)


def chip(text: str, cls: str = "", href: str = "", external: bool = False) -> str:
    c = f"chip {cls}".strip()
    if href:
        extra = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return f'<a class="{c}" href="{esc(href)}"{extra}>{esc(text)}</a>'
    return f'<span class="{c}">{esc(text)}</span>'


def due_class(due: str, today: dt.date) -> str:
    try:
        d = dt.date.fromisoformat(due)
    except ValueError:
        return ""
    return "bad" if d < today else "warn" if d == today else "warn-soft" if d == today + dt.timedelta(days=1) else ""


def record_link(record: str) -> str:
    return f"/workers#{worker_anchor(Path(record).stem)}"


def note_href(note: str) -> str:
    return f"/doc?path={urllib.parse.quote(note)}"


def render_item(it: Item, today: dt.date, show_project: bool = True, show_sub: bool = False) -> str:
    r = Renderer()
    a = it.attrs
    chips = []
    if "worker" in a:
        chips.append(chip(f"worker: {a['worker']}", "accent", f"/workers#{worker_anchor(a['worker'])}"))
    elif "doing" in a:
        chips.append(chip(f"着手 {a['doing']}", "accent"))
    if "due" in a:
        chips.append(chip(f"期限 {a['due']}", due_class(a["due"], today)))
    if "note" in a:
        chips.append(chip("📄 資料", "link", note_href(a["note"])))
    if "record" in a and "worker" not in a:
        chips.append(chip("📝 記録", "link", record_link(a["record"])))
    if "link" in a and r.href(a["link"]) and r.href(a["link"])[1]:
        chips.append(chip("🔗 リンク", "link", a["link"], external=True))
    if "reported" in a:
        chips.append(chip(f"報告 {a['reported']}", "muted"))
    if show_project and "project" in a:
        chips.append(chip(a["project"], "muted"))
    sub = ""
    if show_sub and it.sub:
        sub = "<ul class=sub>" + "".join(f"<li>{r.inline(s)}</li>" for s in it.sub) + "</ul>"
    mark = {"x": "☑", "-": "☒"}.get(it.state, "☐")
    cls = "item" if it.open else "item closed"
    return f'<li class="{cls}"><span class="check">{mark}</span> <span class="body">{r.inline(it.body)}</span> <span class="chips">{"".join(chips)}</span>{sub}</li>'


def item_list(items: list[Item], today: dt.date, empty: str = "なし", **kw) -> str:
    if not items:
        return f'<p class="muted">{esc(empty)}</p>'
    return "<ul class=items>" + "".join(render_item(it, today, **kw) for it in items) + "</ul>"


def page_overview() -> tuple[str, str]:
    home = hub_home()
    gtd = load_gtd(home)
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)

    open_items = [it for name in ("next-actions", "waiting-for", "inbox", "projects") for it in gtd[name] if it.open]
    doing = [it for it in open_items if it.doing and it.file != "projects"]
    nexts = [it for it in gtd["next-actions"] if it.open and not it.doing]
    waiting = [it for it in gtd["waiting-for"] if it.open and not it.doing]
    inbox = [it for it in gtd["inbox"] if it.open]

    def closed_on(it: Item) -> str:
        return it.attrs.get("done") or it.attrs.get("cancelled") or it.section

    done_today = [it for it in gtd["done"] if closed_on(it) == today.isoformat()]
    done_yesterday = [it for it in gtd["done"] if closed_on(it) == yesterday.isoformat()]

    alive = sum(1 for w in tmux_windows())
    asks = sum(1 for r in load_reports() if r.is_open)
    stats = [
        ("受信箱（未対応）", asks, "/inbox"),
        ("DOING", len(doing), "#doing"),
        ("次にやること", len(nexts), "#next"),
        ("待ち", len(waiting), "#waiting"),
        ("inbox", len(inbox), "#inbox"),
        ("動いている worker", alive, "/workers"),
        ("今日の完了", len(done_today), "#done"),
    ]
    cards = "".join(
        f'<a class="stat{" alert" if href == "/inbox" and n else ""}" href="{href}">'
        f'<span class="num">{n}</span><span class="label">{esc(label)}</span></a>'
        for label, n, href in stats
    )

    projects_html = []
    r = Renderer()
    for p in gtd["projects"]:
        if not p.open:
            continue
        related = [it for it in open_items if it.attrs.get("project") == p.body]
        counts = f'<span class="muted">未完了 {len(related)} 件</span>' if related else ""
        sub = "".join(f"<li>{r.inline(s)}</li>" for s in p.sub)
        chips = "".join(chip(f"{k}: {v}", "muted") for k, v in p.attrs.items() if k in ("repo", "due"))
        projects_html.append(
            f'<div class="project"><div class="ptitle">{r.inline(p.body)} {chips} {counts}</div>'
            f"{'<ul class=sub>' + sub + '</ul>' if sub else ''}</div>"
        )

    body = f"""
<section class="stats">{cards}</section>
<section id="doing"><h2>DOING</h2>{item_list(doing, today, "着手中の項目はありません")}</section>
<section id="next"><h2>次にやること</h2>{item_list(nexts, today, "次にやることはありません")}</section>
<section id="waiting"><h2>待ち</h2>{item_list(waiting, today, "待っている項目はありません")}</section>
{f'<section id="inbox"><h2>inbox</h2>{item_list(inbox, today)}</section>' if inbox else ''}
<section id="done"><h2>完了（今日 {today.isoformat()}）</h2>{item_list(done_today, today, "まだありません", show_sub=True)}
<h3>昨日 {yesterday.isoformat()}</h3>{item_list(done_yesterday, today, "ありません", show_sub=True)}</section>
<section id="projects"><h2>プロジェクト</h2>{''.join(projects_html) or '<p class="muted">なし</p>'}</section>
"""
    return "Overview", body


def doc_files(home: Path) -> list[tuple[str, float]]:
    files = []
    for d in DOC_DIRS:
        root = home / d
        if not root.is_dir():
            continue
        for p in root.rglob("*.md"):
            if p.is_file():
                files.append((p.relative_to(home).as_posix(), p.stat().st_mtime))
    return files


def resolve_doc(rel: str) -> Path | None:
    """hub の notes/ minutes/ gtd/ 配下の .md だけを返す。外に出るパスは None。"""
    home = hub_home().resolve()
    try:
        path = (home / rel).resolve()
        inner = path.relative_to(home)
    except (ValueError, OSError):
        return None
    if not inner.parts or inner.parts[0] not in DOC_DIRS or path.suffix != ".md" or not path.is_file():
        return None
    return path


def page_docs() -> tuple[str, str]:
    files = doc_files(hub_home())
    sections = []
    for d in DOC_DIRS:
        rows = sorted((f for f in files if f[0].startswith(d + "/")), key=lambda f: -f[1])
        lis = "".join(
            f'<li><a href="{esc(note_href(rel))}">{esc(rel[len(d) + 1:])}</a> '
            f'<span class="muted">{dt.datetime.fromtimestamp(m).strftime("%m-%d %H:%M")}</span></li>'
            for rel, m in rows
        )
        sections.append(f"<section><h2>{d}/</h2>{'<ul class=files>' + lis + '</ul>' if lis else '<p class=muted>なし</p>'}</section>")
    return "資料", "".join(sections)


def page_doc(rel: str) -> tuple[str, str] | None:
    path = resolve_doc(rel)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    rel_norm = path.relative_to(hub_home().resolve()).as_posix()
    crumbs = f'<p class="crumbs"><a href="/docs">資料</a> / {esc(rel_norm)} <span class="muted">更新 {mtime}</span></p>'
    return rel_norm, crumbs + f'<article class="md">{Renderer(rel_norm).render(text)}</article>'


def render_pr(w: Worker) -> str:
    if not w.repo or not w.branch:
        return '<span class="muted">PR: リポジトリかブランチが分かりません</span>'
    fetched, pr = PR_CACHE.get(w.repo, w.branch)
    if not fetched:
        return '<span class="muted">PR: 取得中…</span>'
    if pr is None or "error" in pr:
        reason = esc((pr or {}).get("error", ""))
        return f'<span class="muted" title="{reason}">PR: gh で取得できませんでした</span> <span class="muted small">{reason}</span>'
    if pr.get("none"):
        return '<span class="muted">PR なし</span>'
    state = pr.get("state", "")
    label, cls = {
        "MERGED": ("merged", "merged"),
        "CLOSED": ("closed", "muted"),
    }.get(state, ("draft", "muted") if pr.get("isDraft") else ("open", "good"))
    ci, ci_cls = ci_summary(pr.get("statusCheckRollup"))
    pr_chip = chip("#{} {}".format(pr.get("number"), label), cls, pr.get("url", ""), external=True)
    ci_chip = chip(ci, ci_cls) if state == "OPEN" else ""
    title = esc(pr.get("title", ""))
    return f'{pr_chip} {ci_chip} <span class="prtitle">{title}</span>'


def page_workers() -> tuple[str, str]:
    gtd = load_gtd(hub_home())
    workers = load_workers(gtd)
    today = dt.date.today()
    open_by_worker: dict[str, int] = {}
    for r in load_reports():
        if r.is_open:
            open_by_worker[r.worker] = open_by_worker.get(r.worker, 0) + 1
    if not workers:
        return "Workers", f'<p class="muted">記録ファイルがありません（{esc(state_dir())}）</p>'
    cards = []
    for w in workers:
        anchor = worker_anchor(w.name)
        if w.window:
            status = chip(f"tmux {w.window['session']}:{w.window['name']}", "good")
        else:
            status = chip("window なし", "muted")
        wt = w.worktree.replace(str(Path.home()), "~") if w.worktree else "?"
        wt_state = "" if w.worktree and Path(w.worktree).is_dir() else ' <span class="muted">（削除済み）</span>'
        asks = open_by_worker.get(w.name, 0)
        if asks:
            status += " " + chip(f"未対応の報告 {asks}", "bad", f"/inbox#{report_anchor(w.name, '')}")
        item = ""
        if w.item:
            item = f'<ul class="items">{render_item(w.item, today)}</ul><p class="muted">gtd/{esc(w.item.file)}.md</p>'
        updated = dt.datetime.fromtimestamp(w.mtime).strftime("%m-%d %H:%M")
        cards.append(f"""
<section class="worker" id="{anchor}">
  <h2>{esc(w.name)} {status}</h2>
  <dl>
    <dt>worktree</dt><dd><code>{esc(wt)}</code>{wt_state}</dd>
    <dt>ブランチ</dt><dd><code>{esc(w.branch or "?")}</code> {chip(w.repo, "muted") if w.repo else ""}</dd>
    <dt>PR</dt><dd>{render_pr(w)}</dd>
    <dt>記録</dt><dd><span class="muted">{esc(w.path.name)}・更新 {updated}</span></dd>
  </dl>
  {item}
  <details id="d-{anchor}"><summary>指示の全文</summary><article class="md">{Renderer().render(w.text)}</article></details>
</section>""")
    return "Workers", "".join(cards)


def report_anchor(worker: str, ts: str) -> str:
    # リダイレクトの Location にも入るので ASCII だけにする
    return "r-" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{worker}-{ts}" if ts else worker)


KIND_CLASS = {"要判断": "warn", "ブロック": "bad", "完了": "good", "回答": "accent", "対応済み": "muted"}


def answer_form(r: Report, token: str, window: dict | None) -> str:
    hidden = (
        f'<input type="hidden" name="token" value="{esc(token)}">'
        f'<input type="hidden" name="worker" value="{esc(r.worker)}">'
        f'<input type="hidden" name="ref" value="{esc(r.ts)}">'
    )
    resolve = '<button class="ghost" name="action" value="resolve">送らずに対応済みにする</button>'
    if not window:
        note = '<p class="muted small">worker の window が無いので送れません。</p>'
        return f'<form class="answer" method="post" action="/inbox/answer">{hidden}{note}<div class="row">{resolve}</div></form>'
    choices = "".join(
        f'<button class="choice" name="choice" value="{esc(c)}">{esc(c)}</button>' for c in r.choices
    )
    return f"""<form class="answer" method="post" action="/inbox/answer">{hidden}
{f'<div class="row">{choices}</div>' if choices else ''}
<textarea name="text" maxlength="{MAX_ANSWER}" rows="2" placeholder="worker への答え（改行は空白になります）"></textarea>
<div class="row"><button name="action" value="send">送る</button>{resolve}
<span class="muted small">送り先: {esc(window['session'])}:{esc(window['name'])}</span></div></form>"""


def render_report(r: Report) -> str:
    head = f'{chip(r.kind, KIND_CLASS.get(r.kind, ""))} <a href="/workers#{worker_anchor(r.worker)}">{esc(r.worker)}</a> <span class="muted small">{esc(r.ts)}</span>'
    return f'<div class="rhead">{head}</div>'


def page_inbox(token: str, flash: str = "") -> tuple[str, str]:
    reports = load_reports()
    windows = tmux_windows()
    open_reports = sorted((r for r in reports if r.is_open), key=lambda r: r.ts, reverse=True)
    parts = []
    if flash in ANSWER_MESSAGES:
        msg, cls = ANSWER_MESSAGES[flash]
        parts.append(f'<p class="flash {cls}">{esc(msg)}</p>')
    cards = []
    for r in open_reports:
        cards.append(
            f'<section class="report open" id="{report_anchor(r.worker, r.ts)}">{render_report(r)}'
            f'<article class="md">{Renderer().render(r.body)}</article>'
            f"{answer_form(r, token, windows.get(r.worker))}</section>"
        )
    parts.append(f"<h2>未対応の要判断・ブロック（{len(open_reports)}）</h2>")
    parts.append("".join(cards) or '<p class="muted">未対応の報告はありません</p>')

    history = sorted(reports, key=lambda r: r.ts, reverse=True)[:50]
    rows = []
    for r in history:
        if r.kind in ANSWER_KINDS:
            text = f'<span class="muted">→ {esc(r.ref)} の報告へ</span> {Renderer().inline(r.body)}'
        else:
            state = ""
            if r.kind in ASK_KINDS:
                state = chip("未対応", "bad") if r.is_open else chip("対応済み", "muted")
            text = f"{Renderer().inline(r.summary)} {state}"
        details = ""
        if r.kind in REPORT_KINDS:
            details = (
                f'<details id="d-{report_anchor(r.worker, r.ts)}"><summary>本文</summary>'
                f'<article class="md">{Renderer().render(r.body)}</article></details>'
            )
        rows.append(f'<li class="item">{render_report(r)}<div class="rbody">{text}</div>{details}</li>')
    parts.append("<h2>最近の報告と回答</h2>")
    parts.append(f'<ul class="items">{"".join(rows)}</ul>' if rows else f'<p class="muted">報告はありません（{esc(reports_dir())}）</p>')
    # Workers の「未対応の報告」から飛ぶための印
    for name in sorted({r.worker for r in open_reports}):
        parts.insert(0, f'<span id="{report_anchor(name, "")}"></span>')
    return "受信箱", "".join(parts)


# ---------------------------------------------------------------------------
# HTTP

CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--card:#f6f8fa;--accent:#0969da;--good:#1a7f37;--warn:#9a6700;--bad:#cf222e;--merged:#8250df}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;--line:#30363d;--card:#161b22;--accent:#4493f8;--good:#3fb950;--warn:#d29922;--bad:#f85149;--merged:#a371f7}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans CJK JP","Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:1;display:flex;gap:1.2em;align-items:center;padding:.6em 1.2em;border-bottom:1px solid var(--line);background:var(--bg)}
header .brand{font-weight:700}
header nav a{margin-right:1em;color:var(--muted);text-decoration:none}
header nav a.active{color:var(--fg);font-weight:600;border-bottom:2px solid var(--accent)}
header .updated{margin-left:auto;color:var(--muted);font-size:.85em}
main{max-width:1100px;margin:0 auto;padding:1em 1.2em 4em}
a{color:var(--accent)}
h2{font-size:1.2em;border-bottom:1px solid var(--line);padding-bottom:.2em;margin-top:1.6em}
h3{font-size:1em;color:var(--muted)}
.muted{color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.6em}
.stat{display:flex;flex-direction:column;padding:.6em .8em;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);text-decoration:none}
.stat .num{font-size:1.8em;font-weight:700;line-height:1.2}
.stat .label{color:var(--muted);font-size:.85em}
ul.items{list-style:none;padding:0;margin:0}
li.item{padding:.45em .2em;border-bottom:1px solid var(--line)}
li.item.closed .body{color:var(--muted)}
.check{color:var(--muted)}
.chips{display:inline-flex;flex-wrap:wrap;gap:.3em;margin-left:.3em;vertical-align:middle}
.chip{display:inline-block;font-size:.78em;padding:0 .55em;border:1px solid var(--line);border-radius:999px;color:var(--fg);text-decoration:none;white-space:nowrap;max-width:28em;overflow:hidden;text-overflow:ellipsis}
.chip.muted{color:var(--muted)}
.chip.link{border-color:var(--accent);color:var(--accent)}
.chip.accent{background:var(--accent);border-color:var(--accent);color:#fff}
.chip.good{border-color:var(--good);color:var(--good)}
.chip.warn{border-color:var(--warn);color:var(--warn);font-weight:600}
.chip.warn-soft{border-color:var(--warn);color:var(--warn)}
.chip.bad{border-color:var(--bad);color:var(--bad);font-weight:600}
.chip.merged{border-color:var(--merged);color:var(--merged)}
ul.sub{margin:.2em 0 0 1.6em;padding-left:1em;color:var(--muted);font-size:.92em}
.project{padding:.5em 0;border-bottom:1px solid var(--line)}
.ptitle{font-weight:600}
.worker{border:1px solid var(--line);border-radius:8px;padding:.2em 1em .8em;margin:1em 0;background:var(--card)}
.worker h2{border:0;margin-top:.6em}
dl{display:grid;grid-template-columns:7em 1fr;gap:.2em .8em;margin:.4em 0}
dt{color:var(--muted)}dd{margin:0}
details summary{cursor:pointer;color:var(--accent);margin-top:.4em}
details article{border-top:1px solid var(--line);margin-top:.5em}
.small{font-size:.8em}
.prtitle{color:var(--muted);font-size:.9em}
ul.files li{margin:.15em 0}
.crumbs{color:var(--muted)}
.md{overflow-wrap:anywhere}
.md pre{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:.8em;overflow:auto;font-size:.88em;line-height:1.45}
.md code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--card);padding:.1em .3em;border-radius:4px}
.md pre code{background:none;padding:0}
.md blockquote{margin:0;padding:0 1em;border-left:4px solid var(--line);color:var(--muted)}
.md .table{overflow-x:auto}
.md table{border-collapse:collapse;margin:.6em 0}
.md th,.md td{border:1px solid var(--line);padding:.35em .7em;vertical-align:top}
.md th{background:var(--card)}
.md tr:nth-child(2n) td{background:color-mix(in srgb,var(--card) 50%,transparent)}
.md .al-center{text-align:center}.md .al-right{text-align:right}
.md .done{color:var(--muted);text-decoration:line-through}
.md li{margin:.15em 0}
.stat.alert{border-color:var(--bad)}
.stat.alert .num{color:var(--bad)}
.report{border:1px solid var(--line);border-radius:8px;padding:.6em 1em;margin:1em 0;background:var(--card)}
.report.open{border-left:4px solid var(--warn)}
.rhead{display:flex;gap:.5em;align-items:center;flex-wrap:wrap}
.rbody{margin:.2em 0 0 .2em}
form.answer{margin-top:.6em;display:flex;flex-direction:column;gap:.4em}
form.answer .row{display:flex;flex-wrap:wrap;gap:.4em;align-items:center}
form.answer textarea{width:100%;font:inherit;padding:.4em;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
form.answer button{font:inherit;padding:.2em .9em;border:1px solid var(--accent);border-radius:6px;background:var(--accent);color:#fff;cursor:pointer}
form.answer button.choice{background:var(--bg);color:var(--accent)}
form.answer button.ghost{background:none;border-color:var(--line);color:var(--muted)}
.flash{padding:.5em .8em;border:1px solid var(--line);border-radius:6px}
.flash.good{border-color:var(--good);color:var(--good)}
.flash.bad{border-color:var(--bad);color:var(--bad)}
"""

# 一定間隔で同じ URL を取り直し、<main> の中身が変わっていたら差し替える。
# 開いている <details> とスクロール位置は保つ。タブが隠れている間は止める。
APP_JS = """
(() => {
  const interval = Number(document.body.dataset.interval || 10) * 1000;
  const main = document.querySelector('main');
  const stamp = document.querySelector('.updated');
  let last = main.innerHTML;
  const show = (t) => { stamp.textContent = t; };
  show('更新 ' + new Date().toLocaleTimeString());
  async function tick() {
    if (document.hidden) return;
    // 答えを書いている途中なら差し替えない（入力が消えるので）
    const active = document.activeElement;
    if ((active && main.contains(active) && active.closest('form')) ||
        [...main.querySelectorAll('textarea')].some(t => t.value)) return;
    try {
      const res = await fetch(location.pathname + location.search, {headers: {'X-Partial': '1'}, cache: 'no-store'});
      if (!res.ok) { show('取得失敗 ' + res.status); return; }
      const html = await res.text();
      if (html !== last) {
        const open = [...main.querySelectorAll('details[open][id]')].map(d => d.id);
        main.innerHTML = html;
        last = main.innerHTML;
        open.forEach(id => { const d = document.getElementById(id); if (d) d.open = true; });
      }
      show('更新 ' + new Date().toLocaleTimeString());
    } catch (e) { show('サーバーに接続できません'); }
  }
  // 二度押しで同じ答えを二回送らない
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (form.dataset.sent) { e.preventDefault(); return; }
    form.dataset.sent = '1';
  });
  setInterval(tick, interval);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
})();
"""

NAV = (("/", "Overview"), ("/inbox", "受信箱"), ("/docs", "資料"), ("/workers", "Workers"))


def layout(title: str, body: str, path: str, interval: int) -> str:
    def active(href: str) -> str:
        on = path == href or (href == "/docs" and path == "/doc")
        return ' class="active"' if on else ""

    nav = "".join(f'<a href="{h}"{active(h)}>{esc(t)}</a>' for h, t in NAV)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · hub</title><link rel="stylesheet" href="/app.css"></head>
<body data-interval="{interval}"><header><span class="brand">hub</span><nav>{nav}</nav><span class="updated"></span></header>
<main>{body}</main><script src="/app.js"></script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "hub-dash"
    interval = 10
    allowed_hosts: set[str] = set()
    token = ""  # 起動ごとに作る。答えの POST にはこれが要る

    def log_message(self, fmt, *args):  # アクセスログは出さない（資料の名前が端末に残らないように）
        pass

    def send(self, status: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # no-referrer にすると POST の Origin が null になり、同じ origin か確かめられないので same-origin にする
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def forbidden(self, reason: str) -> None:
        self.send(HTTPStatus.FORBIDDEN, reason, "text/plain; charset=utf-8")

    def do_POST(self):
        if self.headers.get("Host", "") not in self.allowed_hosts:
            return self.forbidden("forbidden host")
        # ほかのサイトのページから送らせない。ブラウザは POST に必ず Origin を付ける
        if self.headers.get("Origin", "") not in {f"http://{h}" for h in self.allowed_hosts}:
            return self.forbidden("forbidden origin")
        if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            return self.forbidden("forbidden origin")
        if urllib.parse.urlsplit(self.path).path != "/inbox/answer":
            return self.send(HTTPStatus.NOT_FOUND, "not found", "text/plain; charset=utf-8")
        if not self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            return self.send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported media type", "text/plain; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.send(HTTPStatus.LENGTH_REQUIRED, "length required", "text/plain; charset=utf-8")
        if length < 0 or length > MAX_FORM_BYTES:
            return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too large", "text/plain; charset=utf-8")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            form = urllib.parse.parse_qs(raw, keep_blank_values=True, max_num_fields=10)
        except ValueError:
            return self.send(HTTPStatus.BAD_REQUEST, "bad form", "text/plain; charset=utf-8")
        def field_(key: str) -> str:
            return form.get(key, [""])[0]

        if not self.token or not hmac.compare_digest(field_("token").encode(), self.token.encode()):
            return self.forbidden("invalid token: ページを読み直してください")
        worker, ref = field_("worker"), field_("ref")
        if "choice" in form:
            result = answer_report(worker, ref, "send", field_("choice"))
        else:
            result = answer_report(worker, ref, field_("action"), field_("text"))
        anchor = "" if result in ("sent", "resolved") else f"#{report_anchor(worker, ref)}"
        self.redirect(f"/inbox?r={result}{anchor}")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.headers.get("Host", "") not in self.allowed_hosts:
            self.send(HTTPStatus.FORBIDDEN, "forbidden host", "text/plain; charset=utf-8")
            return
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/app.css":
            self.send(HTTPStatus.OK, CSS, "text/css; charset=utf-8")
            return
        if url.path == "/app.js":
            self.send(HTTPStatus.OK, APP_JS, "text/javascript; charset=utf-8")
            return
        try:
            if url.path == "/":
                page = page_overview()
            elif url.path == "/docs":
                page = page_docs()
            elif url.path == "/doc":
                page = page_doc(query.get("path", [""])[0])
            elif url.path == "/workers":
                page = page_workers()
            elif url.path == "/inbox":
                page = page_inbox(self.token, query.get("r", [""])[0])
            else:
                page = None
        except Exception as e:  # 読み込み中のファイルなどで落ちても、次の更新で直るようにする
            page = ("エラー", f'<p class="bad">読み込みに失敗しました: {esc(type(e).__name__)}: {esc(e)}</p>')
        if page is None:
            self.send(HTTPStatus.NOT_FOUND, layout("見つかりません", '<p class="muted">見つかりません</p>', url.path, self.interval))
            return
        title, body = page
        if self.headers.get("X-Partial") == "1":
            self.send(HTTPStatus.OK, body)
        else:
            self.send(HTTPStatus.OK, layout(title, body, url.path, self.interval))


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/app.css", timeout=2) as res:
            return res.headers.get("Server", "").startswith(Handler.server_version)
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("AGENT_HUB_DASH_PORT", DEFAULT_PORT)))
    ap.add_argument("--interval", type=int, default=10, help="再読み込みの間隔（秒）")
    ap.add_argument("--open", action="store_true", help="起動後にブラウザで開く")
    args = ap.parse_args(argv)

    Handler.interval = max(2, args.interval)
    Handler.allowed_hosts = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
    Handler.token = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{args.port}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        if already_running(args.port):
            print(f"hub-dash: すでに起動しています: {url}", file=sys.stderr)
            if args.open:
                webbrowser.open(url)
            return 0
        print(f"hub-dash: 127.0.0.1:{args.port} で待ち受けられません: {e}", file=sys.stderr)
        return 1
    print(f"hub-dash: {url} （hub: {hub_home()}、記録: {state_dir()}）", file=sys.stderr)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
