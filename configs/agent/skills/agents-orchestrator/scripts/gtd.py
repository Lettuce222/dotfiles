#!/usr/bin/env python3
"""hub v2 の項目（GTD の 1 件 1 ファイル）を読み書きするスクリプト。

項目は ${GTD_HOME:-${AGENT_ORCHESTRATOR_HOME:-~/hub}/gtd}/items/<id>.md に、frontmatter 付きの
Markdown で置く。成果物は items/<id>/ に置く。中身は社内の文脈なので dotfiles には置かない。
ここにあるのは形と操作だけ。デスク（Hub (local) の worker）も窓口も worker も見張りも、
このスクリプトか、同じ形の直接の編集で書く。

    ---
    id: 20261120-a3f2
    title: サンプルデータを 1 か所にまとめる
    list: next
    project: measurement
    actor: agent
    worker: research-sample
    due: 2026-11-28
    since: 2026-11-20
    links:
      - https://example.com/browse/X-1
    ---
    本文（Rich Markdown の正規形）

- list は inbox|next|planned|project|waiting|someday|reference|done。リストの所属は list の値で
  持ち、ファイルは動かさない。
- プロジェクト（list: project）は outcome・short・steps（行動の id の並び）を持つ。steps の項目は
  done・next・waiting・planned のどれか。ステップを done にすると、next のステップが無くなったとき、
  並びで最初の planned を next にする。
- 連絡待ち（list: waiting）は who・since・follow_up・then・watch を持つ。
- 本文は Rich Markdown の正規形で書く（lint を参照）。ファイル末尾の改行と frontmatter のあとの
  空行は問わない（Orca の Rich の保存で消えるため）。

履歴（記録係）: GTD_HOME はローカルの git（remote は無し）。
- エージェント（--by agent:<名前>）が書くときは、書く前に、まだコミットしていない人の変更を
  user のコミットにまとめ、書いたあとすぐ自分のコミットにする。
- 人（--by user。デスク）が書いたものと、Orca のエディタでの保存は、すぐにはコミットしない。
  `record` が、最後の変更から 10 分（--quiet）経ったときにまとめて user のコミットにする。
  Orca の file diff で見えるのは、このコミットの前の変更だけなので、人の変更をしばらく残す。
- add と commit は続けて行い、ステージした状態を残さない。
- 変更は .log/changes.jsonl にも 1 行ずつ足す（デスクが読み直しに使う）。

Usage:
  gtd.py init                     置き場所と git を用意する（何度実行してもよい）
  gtd.py add (<title> | --title T) [--list L] [--project P] [--actor me|agent] [--worker W] [--due D]
             [--who X] [--follow-up D] [--then T] [--watch URL]… [--link URL]… [--source S]
             [--outcome O] [--short S] [--id ID] [--body TEXT]
  gtd.py show <id> [--json]
  gtd.py json                     全項目と件数を JSON で出す（デスクが読む）
  gtd.py move <id> <list> [--hash H]
  gtd.py done <id> [--hash H]
  gtd.py set <id> key=value… [--unset key]… [--hash H] [--expect key=value]…
             リストの key は key+=value で足し、key-=value で除く
  gtd.py assign <id> <worker>     actor: agent にして worker を結ぶ
  gtd.py handback <id> <text>     actor: me に戻し、本文の「あなたの番」に何をしてほしいかを書く
  gtd.py note <id> <section> <text>   本文の節（「メモ」「メモへの返事」など）に 1 行足す
  gtd.py step add <project> (--id ID | --title T) [--at N]
  gtd.py step move <project> <id> <N>
  gtd.py step remove <project> <id>
  gtd.py cases                    旧案件（state/cases）の全部の行と、移したかどうかを JSON で出す
  gtd.py from-case <case> <section> <index> <to> [--text T] [--project P]
             旧案件の 1 行を項目にし、元の行に「〔移した→<id>〕」を足す。to は
             inbox|next|step|waiting|someday|reference|gcal|drop（drop は「〔移さない〕」だけ）
  gtd.py case-project <case>      旧案件からプロジェクトの項目を作る
  gtd.py sweep [--dry-run]        watch の PR がすべて閉じた連絡待ちを解き、次の行動にする
  gtd.py lint [<path>…] [--fix] [--json]
  gtd.py record [--quiet SECONDS] [--by user]   まだコミットしていない変更をまとめる

どの書き込みにも --by（既定は環境変数 GTD_BY、無ければ agent）を付けられる。デスクは
--by user で書く。--hash は読んだときの hash（json の hash）で、違えばぶつかりとして止まる
（set の --expect がすべて今の値と合うときだけは、キーごとにまとめて書く）。
ぶつかりは終了コード 3、形の誤りは 2、見つからないなどは 1。
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

LISTS = ("inbox", "next", "planned", "project", "waiting", "someday", "reference", "done")
ACTORS = ("me", "agent")
STEP_LISTS = ("next", "planned", "waiting")
# frontmatter のキーの並び（書くときの順）。知らないキーは、そのあとに元の順で残す。
KEYS = ("id", "title", "list", "project", "actor", "worker", "due", "since", "done", "who",
        "follow_up", "then", "watch", "outcome", "short", "steps", "links", "from", "source")
LIST_KEYS = ("watch", "steps", "links")
DATE_KEYS = ("due", "since", "done", "follow_up")
REQUIRED = ("id", "title", "list")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:[ \t]+(.*?))?[ \t]*$")
MOVED_RE = re.compile(r"〔移した→([a-z0-9][a-z0-9-]*)〕")
DROPPED = "〔移さない〕"
GCAL_PREFIX = "Google Calendar に入れる: "
QUIET_S = 600
CASE_SECTIONS = ("TODO", "Waiting", "Later", "予定", "資料")
FROM_CASE_TO = ("inbox", "next", "step", "waiting", "someday", "reference", "gcal", "drop")

EXIT_NOT_FOUND = 1
EXIT_INVALID = 2
EXIT_CONFLICT = 3
EXIT_GIT = 4


class GtdError(Exception):
    code = EXIT_NOT_FOUND


class Invalid(GtdError):
    code = EXIT_INVALID


class Conflict(GtdError):
    code = EXIT_CONFLICT


class GitError(GtdError):
    code = EXIT_GIT


# ---------------------------------------------------------------- 置き場所


def root() -> Path:
    env = os.environ.get("GTD_HOME")
    if env:
        return Path(env)
    hub = os.environ.get("AGENT_ORCHESTRATOR_HOME")
    return (Path(hub) if hub else Path.home() / "hub") / "gtd"


def hub_home() -> Path:
    hub = os.environ.get("AGENT_ORCHESTRATOR_HOME")
    return Path(hub) if hub else Path.home() / "hub"


def items_dir(r: Path | None = None) -> Path:
    return (r or root()) / "items"


def log_path(r: Path | None = None) -> Path:
    return (r or root()) / ".log" / "changes.jsonl"


def today() -> dt.date:
    env = os.environ.get("GTD_TODAY")
    return dt.date.fromisoformat(env) if env else dt.date.today()


def default_by() -> str:
    return os.environ.get("GTD_BY") or "agent"


def is_agent(by: str) -> bool:
    return by == "agent" or by.startswith("agent:")


_held: dict[str, int] = {}


@contextmanager
def locked(r: Path):
    """置き場所ごとのロック。同じプロセスの中では入れ子で取れる（確かめと書き込みを 1 回のロックで行うため）。"""
    r.mkdir(parents=True, exist_ok=True)
    key = str(r.resolve())
    if _held.get(key):
        _held[key] += 1
        try:
            yield
        finally:
            _held[key] -= 1
        return
    with open(r / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        _held[key] = 1
        try:
            yield
        finally:
            _held[key] = 0
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------- frontmatter


def _scalar(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise Invalid(f"引用符が閉じていない: {raw}")
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise Invalid(f"引用符が閉じていない: {raw}")
        return raw[1:-1].replace("''", "'")
    # 値のあとの「 # …」は注釈。
    raw = re.sub(r"[ \t]+#.*$", "", raw).strip()
    return raw or None


def _inline_list(raw: str) -> list[str]:
    inner = raw.strip()[1:-1]
    return [v for v in (_scalar(p) for p in inner.split(",")) if v]


def parse_frontmatter(lines: list[str]) -> dict:
    fm: dict = {}
    cur: str | None = None
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s+-\s+(.*)$", line) or re.match(r"^\s*-\s*$", line)
        if m and line.startswith((" ", "\t", "-")):
            if cur is None:
                raise Invalid(f"frontmatter の {n} 行目: キーの無いリストの行")
            value = _scalar(m.group(1)) if m.groups() else None
            if not isinstance(fm.get(cur), list):
                fm[cur] = []
            if value:
                fm[cur].append(value)
            continue
        m = KEY_RE.match(line)
        if not m:
            raise Invalid(f"frontmatter の {n} 行目を読めない: {line}")
        key, raw = m.group(1), m.group(2) or ""
        if key in fm:
            raise Invalid(f"frontmatter のキー {key} が 2 つある")
        cur = key
        if raw.startswith("[") and raw.rstrip().endswith("]"):
            fm[key] = _inline_list(raw)
        else:
            fm[key] = _scalar(raw)
    for key in LIST_KEYS:
        if key in fm and not isinstance(fm[key], list):
            fm[key] = [fm[key]] if fm[key] else []
    return fm


def _quote(value: str) -> str:
    if (not value or value != value.strip() or value[0] in "[]{}\"'#&*!|>%@`-?:,"
            or ": " in value or re.search(r"\s#", value) or value.endswith(":")
            or any(c.isspace() and c != " " for c in value)
            or value.lower() in ("null", "true", "false", "yes", "no", "~")):
        return json.dumps(value, ensure_ascii=False)
    return value


def dump_frontmatter(fm: dict) -> str:
    order = [k for k in KEYS if k in fm] + [k for k in fm if k not in KEYS]
    out = ["---"]
    for key in order:
        value = fm[key]
        if value is None or value == [] or value == "":
            continue
        if isinstance(value, list):
            out.append(f"{key}:")
            out.extend(f"  - {_quote(str(v))}" for v in value)
        else:
            out.append(f"{key}: {_quote(str(value))}")
    out.append("---")
    return "\n".join(out) + "\n"


def split_doc(text: str) -> tuple[list[str] | None, str]:
    """(frontmatter の行, 本文)。frontmatter が無ければ (None, text)。"""
    if not text.startswith("---\n") and text.rstrip("\n") != "---":
        return None, text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    raise Invalid("frontmatter の終わりの --- が無い")


# ---------------------------------------------------------------- 項目


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class Item:
    path: Path
    fm: dict
    body: str
    hash: str = ""

    @property
    def id(self) -> str:
        return self.fm.get("id") or self.path.stem

    def get(self, key: str):
        value = self.fm.get(key)
        if key in LIST_KEYS:
            return list(value or [])
        return value

    def dump(self) -> str:
        return dump_frontmatter(self.fm) + self.body

    def to_json(self) -> dict:
        out = {k: self.get(k) for k in KEYS}
        out["id"] = self.id
        for k, v in self.fm.items():
            if k not in out:
                out[k] = v
        out.update(body=self.body, hash=self.hash, path=str(self.path), deliverables=deliverables(self))
        return out


def read_item(path: Path) -> Item:
    data = path.read_bytes()
    lines, body = split_doc(data.decode("utf-8"))
    if lines is None:
        raise Invalid(f"{path.name}: frontmatter が無い")
    return Item(path, parse_frontmatter(lines), body, file_hash(data))


def item_path(item_id: str, r: Path | None = None) -> Path:
    if not ID_RE.match(item_id or ""):
        raise Invalid(f"id の形が違う: {item_id}")
    return items_dir(r) / f"{item_id}.md"


def load(item_id: str, r: Path | None = None) -> Item:
    path = item_path(item_id, r)
    if not path.exists():
        raise GtdError(f"項目が無い: {item_id}")
    return read_item(path)


def load_all(r: Path | None = None) -> tuple[list[Item], list[tuple[Path, str]]]:
    d = items_dir(r)
    items, broken = [], []
    if not d.is_dir():
        return items, broken
    for p in sorted(d.glob("*.md")):
        try:
            items.append(read_item(p))
        except (GtdError, UnicodeDecodeError, OSError) as e:
            broken.append((p, str(e)))
    return items, broken


def deliverables(item: Item) -> list[str]:
    d = item.path.with_suffix("")
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.rglob("*")):
        rel = p.relative_to(d)
        if p.is_file() and not p.is_symlink() and not any(part.startswith(".") for part in rel.parts):
            out.append(str(rel))
    # report.md を先に。
    return sorted(out, key=lambda s: (s != "report.md", s))


def new_id(r: Path) -> str:
    stamp = today().strftime("%Y%m%d")
    for _ in range(100):
        cand = f"{stamp}-{secrets.token_hex(2)}"
        if not item_path(cand, r).exists():
            return cand
    raise GtdError("id を作れなかった")


def write_item(item: Item) -> None:
    item.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = item.path.with_name(f".{item.path.name}.tmp")
    data = item.dump().encode("utf-8")
    tmp.write_bytes(data)
    os.replace(tmp, item.path)
    item.hash = file_hash(data)


def log_change(r: Path, item_id: str, action: str, by: str) -> None:
    p = log_path(r)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "id": item_id, "action": action, "by": by}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def validate_fm(fm: dict) -> None:
    lst = fm.get("list")
    if lst not in LISTS:
        raise Invalid(f"list が違う: {lst}（{'|'.join(LISTS)}）")
    if fm.get("actor") not in (None, *ACTORS):
        raise Invalid(f"actor が違う: {fm.get('actor')}（me|agent）")
    for key in DATE_KEYS:
        v = fm.get(key)
        if v is not None and not _is_date(v):
            raise Invalid(f"{key} が日付（YYYY-MM-DD）でない: {v}")
    if fm.get("worker") and not WORKER_RE.match(fm["worker"]):
        raise Invalid(f"worker の名前の形が違う: {fm['worker']}")
    if fm.get("project") and not ID_RE.match(fm["project"]):
        raise Invalid(f"project の id の形が違う: {fm['project']}")
    for s in fm.get("steps") or []:
        if not ID_RE.match(s):
            raise Invalid(f"steps の id の形が違う: {s}")


def _is_date(v) -> bool:
    if not isinstance(v, str) or not DATE_RE.match(v):
        return False
    try:
        dt.date.fromisoformat(v)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 記録係（git）


def _git(r: Path, *args: str, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    e = {**os.environ, **(env or {})}
    res = subprocess.run(["git", "-C", str(r), *args], capture_output=True, text=True, env=e)
    if check and res.returncode != 0:
        raise GitError(f"git {args[0]} に失敗した: {(res.stderr or res.stdout).strip().splitlines()[-1:] or ''}")
    return res


def is_repo(r: Path) -> bool:
    return (r / ".git").exists()


def author_of(by: str) -> tuple[str, str]:
    name = by if by else "user"
    local = re.sub(r"[^A-Za-z0-9._-]", "-", name.split(":", 1)[-1]) or "user"
    return name, f"{local}@gtd.hub.local"


def pending(r: Path) -> list[str]:
    if not is_repo(r):
        return []
    out = _git(r, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    paths = []
    for entry in out.split("\0"):
        if len(entry) > 3:
            paths.append(entry[3:])
    return paths


def commit(r: Path, by: str, message: str, paths: list[str] | None = None) -> bool:
    """変更をまとめて 1 つのコミットにする。add と commit を続けて行う。変更が無ければ False。"""
    if not is_repo(r) or not pending(r):
        return False
    name, email = author_of(by)
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    if paths:
        _git(r, "add", "-A", "--", *paths)
    else:
        _git(r, "add", "-A")
    res = _git(r, "commit", "-q", "--no-verify", "-m", message, env=env, check=False)
    if res.returncode != 0:
        # ステージした状態を残さない（入れ子の git では file diff --staged が出ないため）。
        _git(r, "reset", "-q", check=False)
        if "nothing to commit" in res.stdout + res.stderr:
            return False
        raise GtdError(f"コミットできなかった: {res.stderr.strip() or res.stdout.strip()}")
    return True


def newest_change(r: Path, paths: list[str]) -> float:
    newest = 0.0
    for p in paths:
        try:
            newest = max(newest, (r / p).stat().st_mtime)
        except OSError:
            # 消えたファイルは、フォルダが変わった時刻（消した時刻）で数える。
            parent = (r / p).parent
            while not parent.exists() and parent != r:
                parent = parent.parent
            newest = max(newest, parent.stat().st_mtime)
    return newest


def record(r: Path, quiet: float = QUIET_S, by: str = "user", now: float | None = None) -> dict:
    with locked(r):
        paths = pending(r)
        if not paths:
            return {"committed": False, "pending": 0}
        age = (now or time.time()) - newest_change(r, paths)
        if age < quiet:
            return {"committed": False, "pending": len(paths), "wait": round(quiet - age)}
        done = commit(r, by, f"記録係: 人の変更をまとめる（{len(paths)} 件）")
        return {"committed": done, "pending": 0 if done else len(paths)}


@contextmanager
def writing(r: Path, by: str):
    """書き込みの前後の記録係。エージェントなら、書く前に人の変更をまとめる。"""
    with locked(r):
        if is_agent(by):
            try:
                commit(r, "user", "記録係: エージェントが書く前に人の変更をまとめる")
            except GitError as e:
                # 履歴が取れなくても、項目は書く。
                print(f"gtd.py: 記録係: {e}", file=sys.stderr)
        messages: list[str] = []
        yield messages
        if is_agent(by) and messages:
            try:
                commit(r, by, "\n".join(messages))
            except GitError as e:
                print(f"gtd.py: 記録係: {e}", file=sys.stderr)


def _save(r: Path, item: Item, by: str, action: str, messages: list[str]) -> None:
    validate_fm(item.fm)
    write_item(item)
    log_change(r, item.id, action, by)
    messages.append(f"{action} {item.id}: {item.fm.get('title', '')}")


def check_hash(item: Item, expected: str | None) -> None:
    if expected and expected != item.hash:
        raise Conflict(f"{item.id} はほかの人が先に直した（読み直してください）")


# ---------------------------------------------------------------- 操作


def init(r: Path) -> dict:
    items_dir(r).mkdir(parents=True, exist_ok=True)
    log_path(r).parent.mkdir(parents=True, exist_ok=True)
    gi = r / ".gitignore"
    if not gi.exists():
        gi.write_text(".log/\n.lock\n*.tmp\n.DS_Store\n", encoding="utf-8")
    created = False
    if not is_repo(r):
        _git(r, "init", "-q")
        created = True
    # ローカルだけの履歴で、記録係が Orca の中から書く。署名の鍵が無くても止まらないようにする。
    _git(r, "config", "commit.gpgsign", "false")
    _git(r, "config", "user.name", "user")
    _git(r, "config", "user.email", "user@gtd.hub.local")
    commit(r, "user", "記録係: 置き場所を作る")
    return {"root": str(r), "created": created}


def add(r: Path, title: str, by: str, list_: str = "inbox", body: str = "", item_id: str | None = None, **fields) -> Item:
    title = " ".join((title or "").split())
    if not title:
        raise Invalid("title が空")
    with writing(r, by) as messages:
        iid = item_id or new_id(r)
        path = item_path(iid, r)
        if path.exists():
            raise Invalid(f"id がもうある: {iid}")
        fm = {"id": iid, "title": title, "list": list_, "since": today().isoformat()}
        for k, v in fields.items():
            if v is not None and v != []:
                fm[k] = v
        if list_ == "done":
            fm.setdefault("done", today().isoformat())
        item = Item(path, fm, fix_body(body) if body else "")
        _save(r, item, by, "add", messages)
        # 行動（next・planned・waiting）だけがプロジェクトのステップになる。資料やいつかは属するだけ。
        if fm.get("project") and list_ in STEP_LISTS:
            _attach_step(r, item, by, messages, at=None, only_if_missing=True)
    return item


def _projects_with_step(items: list[Item], step_id: str) -> list[Item]:
    return [it for it in items if it.get("list") == "project" and step_id in it.get("steps")]


def _attach_step(r: Path, step: Item, by: str, messages: list[str], at: int | None, only_if_missing: bool = False) -> None:
    """step を、その project の steps に足す（無いときだけ）。プロジェクトが無ければ何もしない。"""
    pid = step.get("project")
    try:
        proj = load(pid, r)
    except GtdError:
        return
    if proj.get("list") != "project":
        return
    steps = proj.get("steps")
    if step.id in steps:
        if only_if_missing:
            return
        steps.remove(step.id)
    steps.insert(len(steps) if at is None else max(0, min(at, len(steps))), step.id)
    proj.fm["steps"] = steps
    _save(r, proj, by, "step", messages)


def promote(r: Path, project: Item, by: str, messages: list[str]) -> list[str]:
    """next のステップが無くなったら、並びで最初の planned を next にする。"""
    steps = []
    for sid in project.get("steps"):
        try:
            steps.append(load(sid, r))
        except GtdError:
            continue
    if any(s.get("list") == "next" for s in steps):
        return []
    for s in steps:
        if s.get("list") == "planned":
            s.fm["list"] = "next"
            _save(r, s, by, "promote", messages)
            return [s.id]
    return []


def move(r: Path, item_id: str, list_: str, by: str, expect_hash: str | None = None) -> dict:
    if list_ not in LISTS:
        raise Invalid(f"list が違う: {list_}（{'|'.join(LISTS)}）")
    if list_ == "done":
        return done(r, item_id, by, expect_hash)
    with writing(r, by) as messages:
        item = load(item_id, r)
        check_hash(item, expect_hash)
        item.fm["list"] = list_
        item.fm.pop("done", None)
        _save(r, item, by, f"move:{list_}", messages)
        return {"id": item.id, "list": list_, "hash": item.hash}


def done(r: Path, item_id: str, by: str, expect_hash: str | None = None) -> dict:
    with writing(r, by) as messages:
        item = load(item_id, r)
        check_hash(item, expect_hash)
        item.fm["list"] = "done"
        item.fm["done"] = today().isoformat()
        _save(r, item, by, "done", messages)
        promoted: list[str] = []
        items, _ = load_all(r)
        for proj in _projects_with_step(items, item.id):
            promoted += promote(r, proj, by, messages)
        return {"id": item.id, "promoted": promoted, "hash": item.hash}


def _parse_assignments(pairs: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for p in pairs:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(\+=|-=|=)(.*)$", p, re.S)
        if not m:
            raise Invalid(f"key=value の形でない: {p}")
        out.append((m.group(1), m.group(2), m.group(3).strip()))
    return out


def set_fields(r: Path, item_id: str, pairs: list[str], by: str, unset: list[str] | None = None,
               expect_hash: str | None = None, expect: list[str] | None = None) -> dict:
    changes = _parse_assignments(pairs)
    expects = {k: v for k, _, v in _parse_assignments(expect or [])}
    if expects and not expect_hash:
        raise Invalid("--expect は --hash と一緒に使う")
    with writing(r, by) as messages:
        item = load(item_id, r)
        if expect_hash and expect_hash != item.hash:
            # ほかの人が先に直した。直すキーの今の値が、読んだときの値と同じならキーごとにまとめる。
            touched = {k for k, _, _ in changes} | set(unset or [])
            if not touched or not touched <= set(expects):
                raise Conflict(f"{item.id} はほかの人が先に直した（読み直してください）")
            for k in touched:
                cur = item.fm.get(k)
                cur_s = ",".join(cur) if isinstance(cur, list) else (cur or "")
                if cur_s != expects[k]:
                    raise Conflict(f"{item.id} の {k} はほかの人が先に直した（今は「{cur_s}」）")
        for key, op, value in changes:
            if key == "id":
                raise Invalid("id は変えない")
            if key in LIST_KEYS:
                cur = item.get(key)
                if op == "=":
                    cur = [v.strip() for v in value.split(",") if v.strip()] if value else []
                elif op == "+=":
                    if value and value not in cur:
                        cur.append(value)
                else:
                    cur = [v for v in cur if v != value]
                item.fm[key] = cur
            else:
                if op != "=":
                    raise Invalid(f"{key} はリストでない（+= と -= は使えない）")
                item.fm[key] = " ".join(value.split()) or None
        for key in unset or []:
            if key in REQUIRED:
                raise Invalid(f"{key} は消せない")
            item.fm.pop(key, None)
        if item.fm.get("list") == "done":
            item.fm.setdefault("done", today().isoformat())
        _save(r, item, by, "set", messages)
        return {"id": item.id, "hash": item.hash}


def add_note(item: Item, section: str, text: str) -> None:
    """本文の「## <section>」の節の末尾に「- <text>」を足す。節が無ければ本文の末尾に作る。"""
    text = " ".join(text.split())
    if not text:
        raise Invalid("足す文が空")
    lines = item.body.split("\n")
    head = f"## {section}"
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == head)
    except StopIteration:
        body = item.body.rstrip("\n")
        item.body = fix_body(f"{body}\n\n{head}\n\n- {text}" if body.strip() else f"{head}\n\n- {text}")
        return
    end = next((i for i, l, in_code, is_fence in _lines_outside_code(lines)
                if i > start and not in_code and not is_fence and re.match(r"^#{1,6} ", l)), len(lines))
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    if at == start + 1:
        lines[at:at] = ["", f"- {text}"]
    else:
        lines.insert(at, f"- {text}")
    item.body = fix_body("\n".join(lines))


def note(r: Path, item_id: str, section: str, text: str, by: str) -> dict:
    with writing(r, by) as messages:
        item = load(item_id, r)
        add_note(item, section, text)
        _save(r, item, by, "note", messages)
        return {"id": item.id, "hash": item.hash}


def assign(r: Path, item_id: str, worker: str, by: str) -> dict:
    if not WORKER_RE.match(worker or ""):
        raise Invalid(f"worker の名前の形が違う: {worker}")
    with writing(r, by) as messages:
        item = load(item_id, r)
        item.fm["actor"] = "agent"
        item.fm["worker"] = worker
        if item.get("list") in ("inbox", "planned", "someday"):
            item.fm["list"] = "next"
        _save(r, item, by, "assign", messages)
        return {"id": item.id, "hash": item.hash}


def handback(r: Path, item_id: str, text: str, by: str) -> dict:
    with writing(r, by) as messages:
        item = load(item_id, r)
        item.fm["actor"] = "me"
        add_note(item, "あなたの番", f"{today().strftime('%m/%d')}: {text}")
        _save(r, item, by, "handback", messages)
        return {"id": item.id, "hash": item.hash}


def step_add(r: Path, project_id: str, by: str, step_id: str | None = None, title: str | None = None, at: int | None = None) -> dict:
    with writing(r, by) as messages:
        proj = load(project_id, r)
        if proj.get("list") != "project":
            raise Invalid(f"{project_id} はプロジェクトでない")
        if step_id:
            step = load(step_id, r)
            if step.get("list") in ("inbox", "someday"):
                step.fm["list"] = "planned"
        else:
            if not title:
                raise Invalid("--id か --title が要る")
            step = Item(item_path(new_id(r), r), {"id": "", "title": " ".join(title.split()), "list": "planned", "since": today().isoformat()}, "")
            step.fm["id"] = step.path.stem
        step.fm["project"] = proj.id
        _save(r, step, by, "add" if not step_id else "set", messages)
        _attach_step(r, step, by, messages, at=None if at is None else at - 1)
        proj = load(project_id, r)
        promoted = promote(r, proj, by, messages)
        return {"id": step.id, "project": proj.id, "promoted": promoted}


def step_move(r: Path, project_id: str, step_id: str, pos: int, by: str) -> dict:
    with writing(r, by) as messages:
        proj = load(project_id, r)
        steps = proj.get("steps")
        if step_id not in steps:
            raise GtdError(f"{step_id} は {project_id} のステップでない")
        steps.remove(step_id)
        steps.insert(max(0, min(pos - 1, len(steps))), step_id)
        proj.fm["steps"] = steps
        _save(r, proj, by, "step", messages)
        return {"id": proj.id, "steps": steps}


def step_remove(r: Path, project_id: str, step_id: str, by: str) -> dict:
    with writing(r, by) as messages:
        proj = load(project_id, r)
        steps = proj.get("steps")
        if step_id not in steps:
            raise GtdError(f"{step_id} は {project_id} のステップでない")
        steps.remove(step_id)
        proj.fm["steps"] = steps
        _save(r, proj, by, "step", messages)
        return {"id": proj.id, "steps": steps}


# ---------------------------------------------------------------- 読む（json）


def mine_reason(it: Item, t: dt.date) -> str | None:
    lst = it.get("list")
    if lst == "next" and it.get("actor") == "me" and it.get("worker"):
        return "handback"
    if lst == "waiting" and it.get("follow_up") and it.get("follow_up") <= t.isoformat():
        return "follow_up"
    if lst in ("next", "waiting") and it.get("due") and it.get("due") <= t.isoformat():
        return "due"
    return None


def state_json(r: Path) -> dict:
    t = today()
    items, broken = load_all(r)
    out = []
    for it in items:
        j = it.to_json()
        j["mine"] = mine_reason(it, t)
        out.append(j)
    counts = {"mine": sum(1 for j in out if j["mine"])}
    for name in ("inbox", "next", "project", "waiting", "someday", "reference", "planned", "done"):
        counts[name] = sum(1 for j in out if j["list"] == name)
    return {"today": t.isoformat(), "root": str(r), "items": out, "counts": counts,
            "broken": [{"path": str(p), "error": e} for p, e in broken]}


# ---------------------------------------------------------------- 旧案件（state/cases）


def cases_module():
    """同じフォルダの cases.py（旧案件の形の持ち主）を読む。"""
    spec = importlib.util.spec_from_file_location("hub_cases", Path(__file__).resolve().with_name("cases.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("hub_cases", mod)
    spec.loader.exec_module(mod)
    return mod


def case_from_value(slug: str) -> str:
    return f"state/cases/{slug}.md"


def cases_json(r: Path) -> dict:
    cm = cases_module()
    items, _ = load_all(r)
    projects = {it.get("from"): it.id for it in items if it.get("list") == "project" and it.get("from")}
    out, total, moved = [], 0, 0
    for case in cm.load_cases(cm.cases_dir()):
        lines = []
        for section in CASE_SECTIONS:
            for i, it in enumerate(case.items(section)):
                text = it.text
                m = MOVED_RE.search(text)
                dropped = DROPPED in text
                total += 1
                moved += 1 if (m or dropped) else 0
                label = MOVED_RE.sub("", text).replace(DROPPED, "").strip()
                lines.append({"section": section, "index": i, "text": text, "label": label,
                              "moved": m.group(1) if m else None, "dropped": dropped})
        out.append({"slug": case.slug, "title": case.title, "short": case.short, "path": str(case.path),
                    "project": projects.get(case_from_value(case.slug)), "lines": lines})
    return {"cases": out, "total": total, "done": moved}


def _find_case(cm, slug: str):
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", slug.removesuffix(".md")):
        raise Invalid(f"案件の名前の形が違う: {slug}")
    path = cm.cases_dir() / f"{slug.removesuffix('.md')}.md"
    if not path.exists():
        raise GtdError(f"案件が無い: {slug}")
    return cm.parse(path)


def _clean_case_text(cm, section: str, text: str) -> tuple[str, dict]:
    """旧案件の行の文から、題と frontmatter の値を作る。"""
    t = today()
    text = MOVED_RE.sub("", text).replace(DROPPED, "").strip()
    fields: dict = {}
    if section == "TODO":
        due, _bang, rest = cm.todo_marks(text, t)
        if due:
            fields["due"] = due.isoformat()
        return rest.strip(), fields
    if section == "Waiting":
        wait, nxt = cm.split_next(text)
        if nxt:
            fields["then"] = nxt.strip()
        return wait.strip(), fields
    if section == "予定":
        body, nxt = cm.split_next(text)
        date, _bang, rest = cm.todo_marks(body, t)
        title = rest.strip()
        if date:
            title = f"{title}（{date.month}/{date.day}）"
        if nxt:
            fields["then"] = nxt.strip()
        return title, fields
    return text, fields


def from_case(r: Path, slug: str, section: str, index: int, to: str, by: str, text: str | None = None, project: str | None = None) -> dict:
    # 確かめ・項目の作成・元の行の印を 1 回のロックで行う（同じ行から 2 つ作らないため）。
    with locked(r):
        return _from_case(r, slug, section, index, to, by, text, project)


def _from_case(r: Path, slug: str, section: str, index: int, to: str, by: str, text: str | None, project: str | None) -> dict:
    if to not in FROM_CASE_TO:
        raise Invalid(f"移す先が違う: {to}（{'|'.join(FROM_CASE_TO)}）")
    if section not in CASE_SECTIONS:
        raise Invalid(f"節が違う: {section}（{'|'.join(CASE_SECTIONS)}）")
    cm = cases_module()
    with locked(r):
        case = _find_case(cm, slug)
        lines = case.items(section)
        if index < 0 or index >= len(lines):
            raise GtdError(f"{slug} の {section} に {index} 番目の行が無い")
        line = lines[index]
        if text is not None and " ".join(text.split()) != " ".join(line.text.split()):
            raise Conflict(f"{slug} の行が変わった（読み直してください）")
        if MOVED_RE.search(line.text) or DROPPED in line.text:
            raise Conflict(f"{slug} のこの行はもう片付いている")
    if to == "drop":
        mark = DROPPED
        new = None
    else:
        title, fields = _clean_case_text(cm, section, line.text)
        items, _ = load_all(r)
        case_project = next((it.id for it in items if it.get("list") == "project" and it.get("from") == case_from_value(case.slug)), None)
        proj = project or (case_project if to != "inbox" else None)
        list_ = {"inbox": "inbox", "next": "next", "step": "planned", "waiting": "waiting",
                 "someday": "someday", "reference": "reference", "gcal": "next"}[to]
        if to == "step" and not proj:
            raise Invalid("ステップにするには、先に案件をプロジェクトにする（--project）")
        if to == "gcal":
            title = f"{GCAL_PREFIX}{title}"
        if to in ("next", "gcal"):
            fields["actor"] = "me"
        body = f"- 元の行（{case.title}・{section}）: {MOVED_RE.sub('', line.text).replace(DROPPED, '').strip()}"
        new = add(r, title or line.text, by, list_=list_, body=body, project=proj,
                  **fields, **{"from": case_from_value(case.slug)})
        if to == "step":
            with writing(r, by) as messages:
                p = load(proj, r)
                promote(r, p, by, messages)
        mark = f"〔移した→{new.id}〕"
    with locked(r):
        case = _find_case(cm, slug)
        line = case.items(section)[index]
        line.lines[-1] = f"{line.lines[-1].rstrip()} {mark}"
        cm.write_case(case)
    return {"id": new.id if new else None, "case": case.slug, "mark": mark}


def case_project(r: Path, slug: str, by: str) -> dict:
    with locked(r):
        return _case_project(r, slug, by)


def _case_project(r: Path, slug: str, by: str) -> dict:
    cm = cases_module()
    case = _find_case(cm, slug)
    items, _ = load_all(r)
    for it in items:
        if it.get("list") == "project" and it.get("from") == case_from_value(case.slug):
            return {"id": it.id, "created": False}
    pid = re.sub(r"[^a-z0-9-]+", "-", case.slug.lower()).strip("-")[:48] or new_id(r)
    if item_path(pid, r).exists():
        pid = new_id(r)
    body = f"- 旧案件: [{case.slug}.md](file://{case.path})"
    item = add(r, case.title, by, list_="project", body=body, item_id=pid,
               short=case.short, **{"from": case_from_value(case.slug)})
    return {"id": item.id, "created": True}


def sweep(r: Path, by: str, states_fn=None, dry_run: bool = False) -> list[dict]:
    cm = cases_module()
    states_fn = states_fn or cm.gh_pr_states
    items, _ = load_all(r)
    waits = [it for it in items if it.get("list") == "waiting" and it.get("watch")]
    urls = sorted({u for it in waits for u in it.get("watch") if cm.PR_RE.search(u)})
    if not urls:
        return []
    states = states_fn(urls)
    out = []
    for it in waits:
        prs = [u for u in it.get("watch") if cm.PR_RE.search(u)]
        if not prs or not all(cm.closed(states.get(u)) for u in prs):
            continue
        out.append({"action": "resolved", "id": it.id, "then": it.get("then")})
        if dry_run:
            continue
        with writing(r, by) as messages:
            cur = load(it.id, r)
            old = cur.get("title")
            cur.fm["title"] = cur.get("then") or f"続き: {old}"
            cur.fm["list"] = "next"
            cur.fm["actor"] = "me"
            cur.fm["links"] = cur.get("links") + [u for u in cur.get("watch") if u not in cur.get("links")]
            for k in ("watch", "then", "follow_up"):
                cur.fm.pop(k, None)
            add_note(cur, "メモ", f"{today().strftime('%m/%d')}: 待ちが解けた（{old}）")
            _save(r, cur, by, "sweep", messages)
    return out


# ---------------------------------------------------------------- lint（形と本文の正規形）


@dataclass
class Finding:
    line: int
    code: str
    message: str
    fixable: bool = False

    def to_json(self) -> dict:
        return {"line": self.line, "code": self.code, "message": self.message, "fixable": self.fixable}


FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
RULE_RE = re.compile(r"^ {0,3}(?:([*_])(?:[ \t]*\1){2,}|-(?:[ \t]*-){2,})[ \t]*$")
BULLET_RE = re.compile(r"^(\s*)([*+])([ \t]+)(.*)$")
ORDERED_PAREN_RE = re.compile(r"^(\s*)(\d{1,9})\)([ \t]+.*|)$")
ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,9}[.)])(?:[ \t]+|$)")
HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
REF_DEF_RE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S")
REF_LINK_RE = re.compile(r"\[[^\]]+\]\[[^\]]*\]")
FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")
HTML_COMMENT_RE = re.compile(r"<!--")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s+[^<>]*)?/?>")
AUTOLINK_RE = re.compile(r"<(https?://[^<>\s]+)>")
LINK_RE = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\((?:[^()\s]|\([^()\s]*\))*(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\)")
# 括弧の対は URL の一部（https://en.wikipedia.org/wiki/Foo_(bar)）。末尾の句読点は含めない。
URL_RE = re.compile(r"https?://(?:[^\s<>\[\]()]|\([^\s<>\[\]()]*\))*(?:[^\s<>\[\]().,;:!?、。）」』]|\([^\s<>\[\]()]*\))")
CODE_SPAN_RE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
UNDER_STRONG_RE = re.compile(r"(?<![\w\\])__(?=\S)(.+?)(?<=\S)__(?!\w)")
UNDER_EM_RE = re.compile(r"(?<![\w\\_])_(?=[^\s_])([^_\n]*?[^\s_\\])_(?![\w_])")
SLOT = "\u0000"


def _fix_inline(line: str) -> str:
    """1 行の中の書き方を正規形にする（コードと既存のリンクには触らない）。"""
    store: list[str] = []

    def keep(text: str) -> str:
        store.append(text)
        return f"{SLOT}{len(store) - 1}{SLOT}"

    # 参照リンクの定義と HTML の行は直さない（どちらも lint が別に止める。書き換えると壊れる）。
    if REF_DEF_RE.match(line) or HTML_COMMENT_RE.search(line) or HTML_TAG_RE.search(AUTOLINK_RE.sub("", CODE_SPAN_RE.sub("", line))):
        return line
    line = line.replace(SLOT, "")
    line = CODE_SPAN_RE.sub(lambda m: keep(m.group(0)), line)
    line = AUTOLINK_RE.sub(lambda m: keep(f"[{m.group(1)}]({m.group(1)})"), line)
    line = LINK_RE.sub(lambda m: keep(m.group(0)), line)
    line = URL_RE.sub(lambda m: keep(f"[{m.group(0)}]({m.group(0)})"), line)
    line = UNDER_STRONG_RE.sub(r"**\1**", line)
    line = UNDER_EM_RE.sub(r"*\1*", line)
    slot = re.compile(f"{SLOT}(\\d+){SLOT}")
    while SLOT in line:
        line = slot.sub(lambda m: store[int(m.group(1))], line)
    return line


def _lines_outside_code(lines: list[str]):
    """(番号, 行, コードの中か, 囲みの行か) を順に返す。"""
    fence: str | None = None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(2)
            yield i, line, False, True
            continue
        if fence is not None:
            if m and m.group(2)[0] == fence[0] and len(m.group(2)) >= len(fence) and not m.group(3).strip():
                fence = None
                yield i, line, False, True
            else:
                yield i, line, True, False
            continue
        yield i, line, False, False


def _is_paragraph_line(line: str) -> bool:
    return bool(line.strip()) and not (HEADING_RE.match(line) or ITEM_RE.match(line) or line.lstrip().startswith(">")
                                       or line.lstrip().startswith("|") or FENCE_RE.match(line) or RULE_RE.match(line)
                                       or line.startswith("    "))


def body_findings(body: str, offset: int = 0) -> list[Finding]:
    """本文が Rich Markdown の正規形かどうか。offset は本文の前の行数（frontmatter）。"""
    out: list[Finding] = []
    lines = body.split("\n")
    blank_run = 0
    prev_text = None
    for i, line, in_code, is_fence in _lines_outside_code(lines):
        n = i + 1 + offset
        if in_code:
            blank_run = 0
            prev_text = None
            continue
        if is_fence:
            if line.lstrip().startswith("~"):
                out.append(Finding(n, "fence", "コードの囲みは ``` にする（~~~ は使わない）", True))
            blank_run = 0
            prev_text = None
            continue
        if not line.strip():
            blank_run += 1
            if blank_run == 2:
                out.append(Finding(n, "blank", "ブロックの間の空行は 1 つにする", True))
            prev_text = None
            continue
        blank_run = 0
        if prev_text is not None and SETEXT_RE.match(line) and _is_paragraph_line(prev_text):
            out.append(Finding(n, "setext", "見出しは # で書く（下線の見出しは使わない）", True))
            prev_text = None
            continue
        if RULE_RE.match(line) and line.strip() != "---":
            out.append(Finding(n, "rule", "区切り線は --- にする", True))
        elif BULLET_RE.match(line):
            out.append(Finding(n, "bullet", "リストの印は - にする", True))
        if ORDERED_PAREN_RE.match(line):
            out.append(Finding(n, "ordered", "番号のリストは 1. の形にする（1) は使わない）", True))
        code_free = CODE_SPAN_RE.sub("", line)
        if REF_DEF_RE.match(line) or REF_LINK_RE.search(code_free):
            out.append(Finding(n, "reflink", "参照リンクは使わない（Rich で編集できなくなる）。インラインのリンクにする"))
        if FOOTNOTE_RE.search(code_free):
            out.append(Finding(n, "footnote", "脚注は使わない（Rich で編集できなくなる）"))
        if HTML_COMMENT_RE.search(code_free):
            out.append(Finding(n, "html", "HTML コメントは使わない（Rich で編集できなくなる）"))
        elif HTML_TAG_RE.search(AUTOLINK_RE.sub("", code_free)):
            out.append(Finding(n, "html", "HTML は使わない（Rich で編集できなくなる）"))
        fixed = line if _is_indented_code(line) else _fix_inline(line)
        if fixed != line:
            out.append(Finding(n, "inline", "URL は [url](url)、強調は * と ** にする", True))
        prev_text = line
    out += _indent_findings(lines, offset)
    return out


def _list_blocks(lines: list[str]):
    """箇条書き（- だけ）のかたまりの、項目の行の番号の並び。"""
    block: list[int] = []
    fence = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fence = not fence
            if block:
                yield block
                block = []
            continue
        if fence:
            continue
        m = ITEM_RE.match(line)
        after_blank = i > 0 and not lines[i - 1].strip()
        if block and after_blank and not line.startswith((" ", "\t")):
            # 空行のあとの字下げの無い行は、新しいかたまり（別のリストか段落）。
            yield block
            block = []
        if m:
            block.append(i)
        elif line.strip() and not line.startswith(" ") and block:
            yield block
            block = []
    if block:
        yield block


def _canonical_indents(lines: list[str], block: list[int]) -> dict[int, int] | None:
    if any(not re.match(r"^\s*[-*+](?:[ \t]|$)", lines[i]) for i in block):
        return None  # 番号のリストを含むかたまりは見ない
    # 項目ごとの正しい字下げ（行の番号 → 字下げ）。上の項目より深ければ 1 段下、と順にたどる。
    out: dict[int, int] = {}
    stack: list[int] = []
    for i in block:
        ind = len(lines[i]) - len(lines[i].lstrip(" "))
        while stack and stack[-1] >= ind:
            stack.pop()
        out[i] = 2 * len(stack)
        stack.append(ind)
    return out


def _indent_findings(lines: list[str], offset: int) -> list[Finding]:
    out = []
    for block in _list_blocks(lines):
        canon = _canonical_indents(lines, block)
        if not canon:
            continue
        for i in block:
            ind = len(lines[i]) - len(lines[i].lstrip(" "))
            if canon[i] != ind:
                out.append(Finding(i + 1 + offset, "indent", "入れ子のリストは 2 スペースずつ下げる", True))
    return out


def _longest_backtick_fence(lines: list[str], start: int) -> int:
    """~~~ の囲み（start の行から）の中にある ``` の囲みのいちばん長い長さ。"""
    open_m = FENCE_RE.match(lines[start])
    longest = 0
    for line in lines[start + 1:]:
        m = FENCE_RE.match(line)
        if m and m.group(2)[0] == "~" and len(m.group(2)) >= len(open_m.group(2)) and not m.group(3).strip():
            break
        if m and m.group(2)[0] == "`":
            longest = max(longest, len(m.group(2)))
    return longest


def _is_indented_code(line: str) -> bool:
    """4 つ以上の字下げで、箇条書きの項目でない行（字下げのコードか、項目の続きの行）。触らない。"""
    return line.startswith(("    ", "\t")) and bool(line.strip()) and not ITEM_RE.match(line)


def fix_body(body: str) -> str:
    lines = body.split("\n")
    # 入れ子の字下げ（項目の行と、その続きの行を同じだけ動かす）。
    for block in _list_blocks(lines):
        canon = _canonical_indents(lines, block)
        if not canon:
            continue
        for k, i in enumerate(block):
            ind = len(lines[i]) - len(lines[i].lstrip(" "))
            delta = canon[i] - ind
            if not delta:
                continue
            end = block[k + 1] if k + 1 < len(block) else len(lines)
            for j in range(i, end):
                if j == i or (lines[j].startswith(" ") and lines[j].strip()):
                    cur = len(lines[j]) - len(lines[j].lstrip(" "))
                    lines[j] = " " * max(0, cur + delta) + lines[j].lstrip(" ")
    out: list[str] = []
    fence_open: str | None = None
    fence_new = "```"
    for i, line, in_code, is_fence in _lines_outside_code(lines):
        if in_code:
            out.append(line)
            continue
        if is_fence:
            m = FENCE_RE.match(line)
            if fence_open is None:
                fence_open = m.group(2)
                fence_new = "`" * max(3, _longest_backtick_fence(lines, i) + 1)
                out.append(f"{m.group(1)}{fence_new}{m.group(3)}" if m.group(2).startswith("~") else line)
            else:
                out.append(f"{m.group(1)}{fence_new}" if fence_open.startswith("~") else line)
                fence_open = None
            continue
        if _is_indented_code(line):
            out.append(line)
            continue
        if not line.strip():
            if out and not out[-1].strip():
                continue
            out.append("")
            continue
        if out and SETEXT_RE.match(line) and _is_paragraph_line(out[-1]):
            # 下線の見出しは、上の段落の全部の行が見出しになる。
            para: list[str] = []
            while out and _is_paragraph_line(out[-1]):
                para.insert(0, out.pop().strip())
            level = "#" if line.strip().startswith("=") else "##"
            out.append(f"{level} {' '.join(para)}")
            continue
        if RULE_RE.match(line):
            # 段落のすぐ下の --- は下線の見出しになるので、空行を挟む。
            if out and _is_paragraph_line(out[-1]):
                out.append("")
            out.append("---")
            continue
        m = BULLET_RE.match(line)
        if m:
            line = f"{m.group(1)}-{m.group(3)}{m.group(4)}"
        m = ORDERED_PAREN_RE.match(line)
        if m:
            line = f"{m.group(1)}{m.group(2)}.{m.group(3)}"
        out.append(_fix_inline(line))
    return "\n".join(out)


def item_findings(path: Path, known: dict[str, Item] | None = None) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [Finding(1, "read", f"読めない: {e}")]
    try:
        fm_lines, body = split_doc(text)
    except GtdError as e:
        return [Finding(1, "frontmatter", str(e))]
    if fm_lines is None:
        return [Finding(1, "frontmatter", "frontmatter（--- で囲んだ id・title・list）が無い")]
    try:
        fm = parse_frontmatter(fm_lines)
    except GtdError as e:
        return [Finding(1, "frontmatter", str(e))]
    out: list[Finding] = []
    for key in REQUIRED:
        if not fm.get(key):
            out.append(Finding(1, "required", f"frontmatter に {key} が無い"))
    if fm.get("id") and fm["id"] != path.stem:
        out.append(Finding(1, "id", f"id（{fm['id']}）がファイル名（{path.stem}）と違う"))
    if fm.get("list") and fm["list"] not in LISTS:
        out.append(Finding(1, "list", f"list が違う: {fm['list']}（{'|'.join(LISTS)}）"))
    if fm.get("actor") not in (None, *ACTORS):
        out.append(Finding(1, "actor", f"actor が違う: {fm['actor']}（me|agent）"))
    for key in DATE_KEYS:
        if fm.get(key) is not None and not _is_date(fm[key]):
            out.append(Finding(1, "date", f"{key} が日付（YYYY-MM-DD）でない: {fm[key]}"))
    if fm.get("list") == "done" and not fm.get("done"):
        out.append(Finding(1, "required", "list: done には done（済んだ日）が要る"))
    if fm.get("worker") and not WORKER_RE.match(str(fm["worker"])):
        out.append(Finding(1, "worker", f"worker の名前の形が違う: {fm['worker']}"))
    if known is not None:
        pid = fm.get("project")
        if pid:
            target = known.get(pid)
            if target is None:
                out.append(Finding(1, "ref", f"project の {pid} が無い"))
            elif target.get("list") != "project":
                out.append(Finding(1, "ref", f"project の {pid} はプロジェクト（list: project）でない"))
        steps = fm.get("steps") or []
        if steps and fm.get("list") != "project":
            out.append(Finding(1, "ref", "steps を持てるのはプロジェクト（list: project）だけ"))
        seen = set()
        for sid in steps:
            if sid in seen:
                out.append(Finding(1, "ref", f"steps に {sid} が 2 回ある"))
            seen.add(sid)
            step = known.get(sid)
            if step is None:
                out.append(Finding(1, "ref", f"steps の {sid} が無い"))
            elif step.get("project") != fm.get("id"):
                out.append(Finding(1, "ref", f"steps の {sid} の project が {fm.get('id')} でない"))
    out += body_findings(body, offset=len(fm_lines) + 2)
    return out


def lint(r: Path, paths: list[Path] | None = None, fix: bool = False) -> dict[str, list[Finding]]:
    items, _ = load_all(r)
    known = {it.id: it for it in items}
    targets = paths if paths else sorted(items_dir(r).glob("*.md"))
    result: dict[str, list[Finding]] = {}
    for p in targets:
        p = Path(p)
        if fix and p.resolve().parent == items_dir(r).resolve():
            try:
                with locked(r):
                    text = p.read_text(encoding="utf-8")
                    fm_lines, body = split_doc(text)
                    if fm_lines is not None:
                        new_body = fix_body(body)
                        if new_body != body:
                            head = text[: len(text) - len(body)]
                            tmp = p.with_name(f".{p.name}.tmp")
                            tmp.write_text(head + new_body, encoding="utf-8")
                            os.replace(tmp, p)
                            log_change(r, p.stem, "format", default_by())
            except (GtdError, OSError, UnicodeDecodeError):
                pass
        found = item_findings(p, known)
        if found:
            result[str(p)] = found
    return result


# ---------------------------------------------------------------- CLI


def _take(args: list[str], flag: str, many: bool = False, default=None):
    vals = []
    # --flag=value の形（値が - で始まっても、フラグの名前そのものでも読み違えない）。
    for a in [a for a in args if a.startswith(flag + "=")]:
        vals.append(a[len(flag) + 1:])
        args.remove(a)
    while flag in args:
        i = args.index(flag)
        if i + 1 >= len(args):
            raise Invalid(f"{flag} のあとに値が要る")
        vals.append(args[i + 1])
        del args[i:i + 2]
    if many:
        return vals
    return vals[-1] if vals else default


def _flag(args: list[str], flag: str) -> bool:
    if flag in args:
        args.remove(flag)
        return True
    return False


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=None))


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = args.pop(0)
    r = root()
    try:
        by = _take(args, "--by", default=default_by())
        if cmd == "init":
            _print(init(r))
        elif cmd == "add":
            fields = {
                "project": _take(args, "--project"), "actor": _take(args, "--actor"), "worker": _take(args, "--worker"),
                "due": _take(args, "--due"), "who": _take(args, "--who"), "follow_up": _take(args, "--follow-up"),
                "then": _take(args, "--then"), "watch": _take(args, "--watch", many=True), "links": _take(args, "--link", many=True),
                "source": _take(args, "--source"), "outcome": _take(args, "--outcome"), "short": _take(args, "--short"),
            }
            list_ = _take(args, "--list", default="inbox")
            iid = _take(args, "--id")
            body = _take(args, "--body", default="")
            title = _take(args, "--title") or " ".join(args)
            if not title:
                raise Invalid("title が要る")
            item = add(r, title, by, list_=list_, body=body, item_id=iid, **fields)
            _print({"id": item.id, "path": str(item.path), "hash": item.hash})
        elif cmd == "show":
            as_json = _flag(args, "--json")
            item = load(args[0], r)
            if as_json:
                _print(item.to_json())
            else:
                sys.stdout.write(item.dump())
        elif cmd == "json":
            _print(state_json(r))
        elif cmd == "move":
            h = _take(args, "--hash")
            _print(move(r, args[0], args[1], by, h))
        elif cmd == "done":
            h = _take(args, "--hash")
            _print(done(r, args[0], by, h))
        elif cmd == "set":
            h = _take(args, "--hash")
            unset = _take(args, "--unset", many=True)
            expect = _take(args, "--expect", many=True)
            _print(set_fields(r, args[0], args[1:], by, unset=unset, expect_hash=h, expect=expect))
        elif cmd == "assign":
            _print(assign(r, args[0], args[1], by))
        elif cmd == "handback":
            _print(handback(r, args[0], " ".join(args[1:]), by))
        elif cmd == "note":
            _print(note(r, args[0], args[1], " ".join(args[2:]), by))
        elif cmd == "step":
            sub = args.pop(0) if args else ""
            if sub == "add":
                sid, title, at = _take(args, "--id"), _take(args, "--title"), _take(args, "--at")
                _print(step_add(r, args[0], by, step_id=sid, title=title, at=int(at) if at else None))
            elif sub == "move":
                _print(step_move(r, args[0], args[1], int(args[2]), by))
            elif sub == "remove":
                _print(step_remove(r, args[0], args[1], by))
            else:
                raise Invalid("step add|move|remove")
        elif cmd == "cases":
            _print(cases_json(r))
        elif cmd == "from-case":
            text, proj = _take(args, "--text"), _take(args, "--project")
            _print(from_case(r, args[0], args[1], int(args[2]), args[3], by, text=text, project=proj))
        elif cmd == "case-project":
            _print(case_project(r, args[0], by))
        elif cmd == "sweep":
            for entry in sweep(r, by, dry_run=_flag(args, "--dry-run")):
                _print(entry)
        elif cmd == "lint":
            fix, as_json = _flag(args, "--fix"), _flag(args, "--json")
            result = lint(r, [Path(a) for a in args] or None, fix=fix)
            if as_json:
                _print({p: [f.to_json() for f in fs] for p, fs in result.items()})
            else:
                for p, fs in result.items():
                    for f in fs:
                        mark = "（--fix で直る）" if f.fixable else ""
                        print(f"{p}:{f.line}: {f.message}{mark}")
            return EXIT_INVALID if result else 0
        elif cmd == "record":
            quiet = float(_take(args, "--quiet", default=str(QUIET_S)))
            _print(record(r, quiet=quiet, by=by))
        else:
            raise Invalid(f"知らないコマンド: {cmd}（gtd.py --help）")
    except IndexError:
        print(f"gtd.py {cmd}: 引数が足りない（gtd.py --help）", file=sys.stderr)
        return EXIT_INVALID
    except GtdError as e:
        print(f"gtd.py {cmd}: {e}", file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
