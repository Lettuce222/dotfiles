"""ダッシュボードの「話題」の画面のための、表示に依らない部分。

- Claude Code の transcript（~/.claude/projects/<作業ディレクトリを変換した名前>/<session-id>.jsonl）を読み、
  ユーザー・assistant・ほかのセッションからの発言と、まとめたツールの呼び出しに直す。追記された分だけを読み足す
- worker のセッションがどの transcript に書いているかを決める。`claude agents --json` の pid が
  worker の tmux pane の pid の子孫なら、その sessionId を使う。動いていなければ、worktree の
  transcript のうち、agent-name が worker のセッション名のもので最も新しいものを使う
- 話題の状態（返事待ち / 未読 / 進行中 / 完了・待機）の判定と、既読の記録
- 成果物のパスを開くときと画像を見せるときの、許可したディレクトリの制限

標準ライブラリだけで書き、tmux や claude を呼ぶのは dash.py に任せる（ここは引数で受け取る）。
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

# 入力を待つツール。結果がまだ無ければ、ユーザーの返事を待っている
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
SUMMARY_CHARS = 120
TOOL_RESULT_CHARS = 2000
HEAD_SCAN_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# transcript の場所


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def project_dir(cwd: str) -> Path:
    """Claude Code が作業ディレクトリごとに transcript を置くディレクトリ。英数字以外を - にした名前になる。"""
    return claude_dir() / "projects" / re.sub(r"[^A-Za-z0-9]", "-", cwd)


def parse_agents(text: str) -> list[dict]:
    """`claude agents --json` の出力。同じ名前のセッションが複数あってもすべて返す。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def parse_ps(text: str) -> dict[int, int]:
    """`ps -A -o pid= -o ppid=` の出力を {pid: 親の pid} にする。"""
    parents = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parents[int(parts[0])] = int(parts[1])
    return parents


def descends(pid: int, ancestor: int, parents: dict[int, int]) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = parents.get(pid, 0)
    return False


def find_agent(name: str, worktree: str, pane_pid: int | None, agents: list[dict], parents: dict[int, int]) -> dict | None:
    """worker のセッションを決める。pane の子孫のプロセスを最優先にし、無ければ名前と作業場所が一致する 1 つだけを使う。"""
    if pane_pid:
        for a in agents:
            if isinstance(a.get("pid"), int) and descends(a["pid"], pane_pid, parents):
                return a
    named = [a for a in agents if a.get("name") == name and (not worktree or a.get("cwd") == worktree)]
    return named[0] if len(named) == 1 else None


def agent_transcript(agent: dict) -> Path | None:
    sid, cwd = agent.get("sessionId"), agent.get("cwd")
    if not isinstance(sid, str) or not isinstance(cwd, str) or not re.fullmatch(r"[A-Za-z0-9-]+", sid):
        return None
    return project_dir(cwd) / f"{sid}.jsonl"


def transcript_agent_name(path: Path) -> str:
    """transcript の agent-name の記録（claude -n で付けた名前）。先頭の方だけを見る。"""
    try:
        with path.open("rb") as f:
            read = 0
            for line in f:
                read += len(line)
                if b'"agent-name"' in line:
                    try:
                        return str(json.loads(line).get("agentName") or "")
                    except ValueError:
                        return ""
                if read > HEAD_SCAN_BYTES:
                    break
    except OSError:
        pass
    return ""


def fallback_transcript(name: str, worktree: str) -> Path | None:
    """セッションが動いていないとき。作業場所の transcript のうち、名前の一致する最も新しいもの。"""
    if not worktree:
        return None
    try:
        files = sorted(project_dir(worktree).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for p in files:
        if transcript_agent_name(p) == name:
            return p
    return None


# ---------------------------------------------------------------------------
# transcript の中身


@dataclass
class ToolCall:
    id: str
    name: str
    summary: str
    result: str = ""
    error: bool = False
    done: bool = False


@dataclass
class Entry:
    kind: str  # user / assistant / peer / tools / note
    ts: float
    text: str = ""
    sender: str = ""
    tools: list[ToolCall] = field(default_factory=list)


def parse_ts(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


PEER_RE = re.compile(r"<cross-session-message\b[^>]*>\n?(.*?)\n?</cross-session-message>", re.S)
COMMAND_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
TOOL_INPUT_KEYS = ("command", "file_path", "path", "pattern", "query", "url", "description", "prompt", "skill", "to")


def tool_summary(name: str, inp: object) -> str:
    if not isinstance(inp, dict):
        return ""
    if name == "AskUserQuestion":
        qs = inp.get("questions")
        if isinstance(qs, list) and qs and isinstance(qs[0], dict):
            return str(qs[0].get("question", ""))
    for k in TOOL_INPUT_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


class Transcript:
    """1 つの transcript を読んだ結果。feed() に 1 行ずつ渡す。"""

    def __init__(self):
        self.entries: list[Entry] = []
        self.calls: dict[str, ToolCall] = {}
        self.asking: dict[str, ToolCall] = {}  # 結果を待っている AskUserQuestion など
        self.last_ts = 0.0  # 何かが書かれた最後の時刻
        self.last_reply_ts = 0.0  # assistant が最後に文章を書いた時刻
        self.offset = 0
        self.ident: tuple[int, int] | None = None

    def _add(self, entry: Entry) -> None:
        self.entries.append(entry)

    def _tool(self, call: ToolCall, ts: float) -> None:
        last = self.entries[-1] if self.entries else None
        if last and last.kind == "tools":
            last.tools.append(call)
        else:
            self._add(Entry("tools", ts, tools=[call]))
        self.calls[call.id] = call
        if call.name in ASK_TOOLS:
            self.asking[call.id] = call

    def feed(self, obj: object) -> None:
        if not isinstance(obj, dict) or obj.get("isSidechain"):
            return
        kind = obj.get("type")
        if kind not in ("user", "assistant"):
            return
        ts = parse_ts(obj.get("timestamp"))
        self.last_ts = max(self.last_ts, ts)
        msg = obj.get("message")
        if not isinstance(msg, dict):
            return
        content = msg.get("content")
        if kind == "assistant":
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    self._add(Entry("assistant", ts, block["text"].strip()))
                    self.last_reply_ts = max(self.last_reply_ts, ts)
                elif block.get("type") == "tool_use":
                    name = str(block.get("name", "?"))
                    self._tool(ToolCall(str(block.get("id", "")), name, tool_summary(name, block.get("input"))), ts)
            return
        self._user(obj, content, ts)

    def _user(self, obj: dict, content: object, ts: float) -> None:
        origin = obj.get("origin") if isinstance(obj.get("origin"), dict) else {}
        if obj.get("isCompactSummary"):
            self._add(Entry("note", ts, "ここまでの会話を要約して、続きを始めた"))
            return
        if isinstance(content, list):
            texts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    call = self.calls.get(str(block.get("tool_use_id", "")))
                    if call:
                        call.done = True
                        call.error = bool(block.get("is_error"))
                        call.result = result_text(block.get("content"))[:TOOL_RESULT_CHARS]
                        self.asking.pop(call.id, None)
                elif block.get("type") == "text":
                    texts.append(block.get("text", ""))
            text = "\n".join(texts).strip()
            if text and not obj.get("isMeta"):
                if text.startswith("[Request interrupted"):
                    self._add(Entry("note", ts, "ユーザーが中断した"))
                else:
                    self._add(Entry("user", ts, text))
            return
        if not isinstance(content, str) or obj.get("isMeta"):
            return
        okind = origin.get("kind")
        if okind == "peer":
            m = PEER_RE.search(content)
            self._add(Entry("peer", ts, (m.group(1) if m else content).strip(), sender=str(origin.get("name") or "?")))
        elif okind in (None, "human"):
            text = content.strip()
            cmd = COMMAND_RE.search(text)
            if cmd:
                self._add(Entry("note", ts, f"コマンド {cmd.group(1).strip()}"))
            elif text and not text.startswith(("<local-command", "<system-reminder>", "<task-notification>")):
                self._add(Entry("user", ts, text))
        # task-notification などの裏の知らせは出さない

    @property
    def waiting_input(self) -> bool:
        return bool(self.asking)

    def last_message(self) -> Entry | None:
        return next((e for e in reversed(self.entries) if e.kind in ("user", "assistant", "peer")), None)


# 大きな transcript（数十 MB）で毎回 json を読まないよう、行の種類を文字列で先に絞る
WANTED = (b'"type":"user"', b'"type":"assistant"', b'"type": "user"', b'"type": "assistant"')


def feed_bytes(t: Transcript, data: bytes) -> int:
    """完全な行だけを読み、読んだバイト数を返す。"""
    end = data.rfind(b"\n") + 1
    for line in data[:end].splitlines():
        if not any(w in line for w in WANTED):
            continue
        try:
            t.feed(json.loads(line))
        except ValueError:
            continue
    return end


class TranscriptCache:
    """path ごとに Transcript を覚え、ファイルに追記された分だけを読み足す。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.data: dict[Path, Transcript] = {}

    def get(self, path: Path) -> Transcript | None:
        with self.lock:
            try:
                st = path.stat()
            except OSError:
                self.data.pop(path, None)
                return None
            t = self.data.get(path)
            ident = (st.st_dev, st.st_ino)
            if t is None or t.ident != ident or st.st_size < t.offset:
                t = Transcript()
                t.ident = ident
                self.data[path] = t
            if st.st_size > t.offset:
                try:
                    with path.open("rb") as f:
                        f.seek(t.offset)
                        t.offset += feed_bytes(t, f.read())
                except OSError:
                    return t
            return t


def first_line(text: str, limit: int = SUMMARY_CHARS) -> str:
    for line in text.splitlines():
        s = re.sub(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        s = re.sub(r"[*`]", "", s)
        if s and not s.startswith(("```", "|---", "---")):
            return s if len(s) <= limit else s[: limit - 1] + "…"
    return ""


# ---------------------------------------------------------------------------
# 状態と既読

STATES = {
    "waiting": ("あなたの返事待ち", "bad"),
    "unread": ("新しい返答あり", "warn"),
    "busy": ("進行中", "accent"),
    "idle": ("完了・待機", "muted"),
}
STATE_ORDER = list(STATES)


def topic_state(*, dialog: bool, asking: bool, open_reports: int, unread: bool, busy: bool) -> str:
    if dialog or asking or open_reports:
        return "waiting"
    if unread:
        return "unread"
    if busy:
        return "busy"
    return "idle"


class SeenStore:
    """話題ごとに、ダッシュボードで最後に見た発言の時刻を覚える。ファイルは JSON の {名前: epoch 秒}。"""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict[str, float]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: float(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, (int, float))}

    def mark(self, name: str, ts: float) -> None:
        """見たことを記録する。時刻は戻さない。"""
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock_fd = os.open(self.path.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                data = self.load()
                if data.get(name, 0) >= ts:
                    return
                data[name] = ts
                tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, self.path)
            finally:
                os.close(lock_fd)


# ---------------------------------------------------------------------------
# 成果物のパス

# 文中の絶対パスか ~/ で始まるパス。前が英数字や / のときは URL などの一部とみなす
PATH_RE = re.compile(r"(?<![\w.~/:-])((?:~/|/)[^\s`'\"<>()\[\]{}|*?、。，．（）「」]+)")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def allowed_roots(hub_home: Path) -> list[Path]:
    """開いてよいディレクトリ。/tmp と hub と、AGENT_HUB_OPEN_DIRS（: 区切り）に足したもの。"""
    raw = ["/tmp", str(hub_home)] + [p for p in os.environ.get("AGENT_HUB_OPEN_DIRS", "").split(":") if p]
    roots = []
    for r in raw:
        try:
            p = Path(r).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if p.is_dir() and p != Path(p.anchor) and p not in roots:
            roots.append(p)
    return roots


def resolve_allowed(raw: str, roots: list[Path]) -> Path | None:
    """許可したディレクトリの下にあって、いま存在するものだけを返す。symlink は辿ったあとで確かめる。"""
    raw = raw.strip().rstrip(".,:;!?")
    if not raw or "\x00" in raw or len(raw) > 1024:
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        return None
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    for root in roots:
        if real == root or root in real.parents:
            return real
    return None


def find_paths(text: str) -> list[str]:
    return [m.group(1).rstrip(".,:;!?") for m in PATH_RE.finditer(text)]


def open_command(path: Path, platform: str | None = None) -> list[str]:
    """ファイルなら選んだ状態で、ディレクトリならそのディレクトリを開く。"""
    platform = platform or sys.platform
    if platform == "darwin":
        return ["open", str(path)] if path.is_dir() else ["open", "-R", str(path)]
    return ["xdg-open", str(path if path.is_dir() else path.parent)]


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_TYPES
