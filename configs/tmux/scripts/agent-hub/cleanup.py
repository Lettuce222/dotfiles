#!/usr/bin/env python3
"""窓口（hub）が worker を片付けるコマンド。

Usage: cleanup.py [--dry-run] [--force-unmerged] [--kill-other-windows] <セッション名>
  例: cleanup.py dotfiles.hub-pr-notify

記録ファイル（${XDG_STATE_HOME:-~/.local/state}/agent-hub/<セッション名>.md）の
「作業場所:」「作業ブランチ:」から worktree とブランチ agent/<task> を読み、
元のリポジトリは worktree のパス（<親>/<repo>.worktrees/agent/<task>）から求める。

順に行うこと:
1. merge の判定。dotfiles（main に直接 push する運用）は origin の既定ブランチの祖先か、
   それ以外は gh で探した PR のうち手元のブランチを含み、MERGED のものがあるか。
   判定できない、または merge されていなければ、何も消さずに止まる（--force-unmerged で続ける）
2. worker の window を閉じる。ほかにその worktree を開いている window があれば止まる
   （--kill-other-windows で一緒に閉じる）
3. git worktree remove（--force は使わない。作業ツリーが汚れていれば何も消さずに止まる）
4. 手元のブランチを消す。merge 済みなら、リモートに残ったブランチも消す
5. 記録ファイルを消す（報告のファイル reports/<セッション名>.md は履歴として残す）
6. 元のリポジトリが既定ブランチを checkout していて、作業ツリーがきれいなら git pull --ff-only

行ったことを 1 行ずつ標準出力に出す。--dry-run では何も変えずに予定だけ出す
（判定のための git fetch だけは行う）。止まったときは理由を標準エラーに出し、終了コード 1 で終わる。

gh は AGENT_HUB_GH、なければ PATH の gh。tmux は AGENT_HUB_TMUX、なければ PATH の tmux。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# PR を作らず、作業ブランチを既定ブランチへ直接 push するリポジトリ
DIRECT_PUSH_REPOS = {"Lettuce222/dotfiles"}

SESSION_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
HEADER_KEYS = {"あなたのセッション名": "name", "作業場所": "worktree", "作業ブランチ": "branch"}


class Stop(Exception):
    """何かを理由に止まる。メッセージは hub が読む理由。"""


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base).expanduser() / "agent-hub"


def gh_cmd() -> str:
    return os.environ.get("AGENT_HUB_GH") or "gh"


def tmux_cmd() -> str:
    return os.environ.get("AGENT_HUB_TMUX") or "tmux"


def run(cmd: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(e).__name__}: {e}")


def first_line(res: subprocess.CompletedProcess) -> str:
    lines = (res.stderr or res.stdout or "").strip().splitlines()
    return lines[0] if lines else f"exit {res.returncode}"


def git(repo: str | Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args])


# ---------------------------------------------------------------------------
# 記録ファイルと対象


@dataclass
class Target:
    session: str
    record: Path
    worktree: Path
    branch: str
    repo_root: Path
    owner_repo: str = ""  # origin から読めなければ空


def parse_record(path: Path) -> dict[str, str]:
    """記録ファイルの先頭の見出しを読む（spawn.fish が先頭に書く）。"""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:10]:
        key, sep, value = line.partition(":")
        if sep and key.strip() in HEADER_KEYS:
            found.setdefault(HEADER_KEYS[key.strip()], value.strip())
    return found


def owner_repo_from_url(url: str) -> str:
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def load_target(session: str) -> Target:
    if not SESSION_RE.match(session) or ".." in session:
        raise Stop(f"セッション名が不正です: {session}")
    record = state_dir() / f"{session}.md"
    if not record.is_file():
        raise Stop(f"記録ファイルがありません: {record}")
    header = parse_record(record)
    if header.get("name", session) != session:
        raise Stop(f"記録ファイルのセッション名が {header['name']} です: {record}")
    worktree, branch = header.get("worktree", ""), header.get("branch", "")
    if not worktree or not branch:
        raise Stop(f"記録ファイルに作業場所か作業ブランチがありません: {record}")
    if not branch.startswith("agent/"):
        raise Stop(f"作業ブランチが agent/ で始まりません: {branch}")
    # spawn.fish は <親>/<repo>.worktrees/<ブランチ> に置く。worktree が消えていても求められるようにパスから読む
    suffix = f".worktrees/{branch}"
    if not worktree.endswith(suffix):
        raise Stop(f"作業場所が <repo>.worktrees/{branch} の形ではありません: {worktree}")
    repo_root = Path(worktree[: -len(suffix)])
    if not (repo_root / ".git").exists():
        raise Stop(f"元のリポジトリが見つかりません: {repo_root}")
    url = git(repo_root, "remote", "get-url", "origin")
    owner_repo = owner_repo_from_url(url.stdout) if url.returncode == 0 else ""
    return Target(session, record, Path(worktree), branch, repo_root, owner_repo)


# ---------------------------------------------------------------------------
# 1. merge の判定


def ref_exists(repo: Path, ref: str) -> bool:
    return git(repo, "show-ref", "--quiet", "--verify", ref).returncode == 0


def default_branch(repo: Path) -> str:
    """origin の既定ブランチ（例 origin/main）。"""
    res = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    name = res.stdout.strip() if res.returncode == 0 else ""
    if not name or not ref_exists(repo, f"refs/remotes/{name}"):
        git(repo, "remote", "set-head", "origin", "--auto")
        res = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
        name = res.stdout.strip() if res.returncode == 0 else ""
    return name or "origin/main"


def is_ancestor(repo: Path, a: str, b: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


@dataclass
class MergeResult:
    merged: bool
    reason: str  # merged なら根拠、そうでなければ止まった理由


def branch_ref(t: Target) -> str | None:
    """判定に使うブランチの ref。手元に無ければ origin のもの。"""
    if ref_exists(t.repo_root, f"refs/heads/{t.branch}"):
        return t.branch
    if ref_exists(t.repo_root, f"refs/remotes/origin/{t.branch}"):
        return f"origin/{t.branch}"
    return None


def rev(repo: Path, ref: str) -> str:
    res = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return res.stdout.strip() if res.returncode == 0 else ""


def created_at(repo: Path, branch: str) -> str:
    """ブランチを作ったときのコミット（reflog の最も古い記録）。reflog が無ければ空。"""
    res = git(repo, "reflog", "show", "--format=%H", f"refs/heads/{branch}", "--")
    lines = res.stdout.split() if res.returncode == 0 else []
    return lines[-1] if lines else ""


def check_merged(t: Target) -> MergeResult:
    fetch = git(t.repo_root, "fetch", "--prune", "--quiet", "origin")
    if fetch.returncode != 0:
        return MergeResult(False, f"origin を fetch できません: {first_line(fetch)}")
    ref = branch_ref(t)
    if ref is None:
        return MergeResult(False, f"ブランチ {t.branch} が手元にも origin にもありません")
    if t.owner_repo in DIRECT_PUSH_REPOS:
        # 作り直後のブランチは既定ブランチの祖先なので、コミットが 1 つも無いものは merge 済みと扱わない
        if ref == t.branch and created_at(t.repo_root, t.branch) == rev(t.repo_root, t.branch):
            return MergeResult(False, f"{t.branch} に作ったときからのコミットがありません")
        base = default_branch(t.repo_root)
        if is_ancestor(t.repo_root, ref, base):
            return MergeResult(True, f"{t.branch} は {base} に含まれています")
        return MergeResult(False, f"{t.branch} は {base} に含まれていません")
    return check_pr_merged(t, ref)


def check_pr_merged(t: Target, ref: str) -> MergeResult:
    cmd = [gh_cmd(), "pr", "list", "--head", t.branch, "--state", "all",
           "--json", "number,state,headRefOid,url"]
    if t.owner_repo:
        cmd += ["-R", t.owner_repo]
    res = run(cmd, cwd=t.repo_root)
    if res.returncode != 0:
        return MergeResult(False, f"gh pr list に失敗しました: {first_line(res)}")
    try:
        prs = json.loads(res.stdout or "[]")
    except json.JSONDecodeError:
        return MergeResult(False, "gh pr list の出力を読めません")
    if not prs:
        return MergeResult(False, f"{t.branch} の PR がありません")
    containing = []
    for pr in prs:
        number, oid = pr.get("number"), pr.get("headRefOid", "")
        fetch = git(t.repo_root, "fetch", "--quiet", "origin", f"pull/{number}/head")
        if fetch.returncode != 0 or not oid:
            continue
        if is_ancestor(t.repo_root, ref, oid):
            containing.append(pr)
    merged = [pr for pr in containing if pr.get("state") == "MERGED"]
    if merged:
        pr = merged[0]
        return MergeResult(True, f"PR #{pr['number']} が MERGED で、{t.branch} を含んでいます")
    states = ", ".join(f"#{pr.get('number')} {pr.get('state')}" for pr in prs)
    if not containing:
        return MergeResult(False, f"手元の {t.branch} を含む PR がありません（{states}）")
    return MergeResult(False, f"{t.branch} を含む PR が merge されていません（{states}）")


# ---------------------------------------------------------------------------
# 2. window


@dataclass
class Windows:
    worker: list[str] = field(default_factory=list)  # @agent-hub-worker がこのセッションの window
    others: list[tuple[str, str]] = field(default_factory=list)  # (window_id, 開いているパス)


def inside(path: str, root: Path) -> bool:
    try:
        p = Path(os.path.realpath(path))
        r = Path(os.path.realpath(root))
    except OSError:
        return False
    return p == r or r in p.parents


def find_windows(t: Target) -> Windows:
    fmt = "#{window_id}\t#{@agent-hub-worker}\t#{pane_current_path}"
    res = run([tmux_cmd(), "list-panes", "-a", "-F", fmt])
    if res.returncode != 0:
        msg = first_line(res)
        if "no server running" in msg or "error connecting" in msg:
            return Windows()
        raise Stop(f"tmux の window を一覧できません: {msg}")
    w = Windows()
    for line in res.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        window_id, worker, path = parts
        if worker == t.session:
            if window_id not in w.worker:
                w.worker.append(window_id)
        elif inside(path, t.worktree):
            if window_id not in [o[0] for o in w.others]:
                w.others.append((window_id, path))
    w.others = [o for o in w.others if o[0] not in w.worker]
    return w


# ---------------------------------------------------------------------------
# 計画と実行


@dataclass
class Step:
    plan: str  # --dry-run で出す予定
    done: str  # 実行したあとに出す行
    action: Callable[[], None]


def must(res: subprocess.CompletedProcess, what: str) -> None:
    if res.returncode != 0:
        raise Stop(f"{what}に失敗しました: {first_line(res)}")


def worktree_registered(t: Target) -> bool:
    res = git(t.repo_root, "worktree", "list", "--porcelain")
    target = os.path.realpath(t.worktree)
    return any(
        line.startswith("worktree ") and os.path.realpath(line[len("worktree "):]) == target
        for line in res.stdout.splitlines()
    )


def pull_step(t: Target) -> Step | str:
    """元のリポジトリを pull する Step か、pull しない理由。"""
    head = git(t.repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    current = head.stdout.strip() if head.returncode == 0 else ""
    base = default_branch(t.repo_root).removeprefix("origin/")
    if current != base:
        return f"元のリポジトリは {base} ではなく '{current or '(detached)'}' を checkout しているので pull しません"
    status = git(t.repo_root, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        return "元のリポジトリの作業ツリーに変更があるので pull しません"

    def act() -> None:
        res = git(t.repo_root, "pull", "--ff-only", "--quiet")
        if res.returncode != 0:
            # 片付けそのものは済んでいるので、止めずに 1 行で伝える
            print(f"{t.repo_root} の git pull --ff-only に失敗しました: {first_line(res)}")
        else:
            print(f"{t.repo_root} を pull しました（{base}）")

    return Step(f"{t.repo_root} で git pull --ff-only", "", act)


def build_steps(t: Target, merge: MergeResult, wins: Windows, kill_others: bool) -> list[Step]:
    steps: list[Step] = []
    tmux = tmux_cmd()
    to_kill = list(wins.worker) + ([o[0] for o in wins.others] if kill_others else [])
    for window_id in to_kill:
        def kill(window_id: str = window_id) -> None:
            must(run([tmux, "kill-window", "-t", window_id]), f"window {window_id} を閉じるの")
        kind = "worker の" if window_id in wins.worker else "worktree を開いている"
        steps.append(Step(f"{kind} window {window_id} を閉じる", f"{kind} window {window_id} を閉じました", kill))

    if t.worktree.exists():
        def remove() -> None:
            res = git(t.repo_root, "worktree", "remove", str(t.worktree))
            if res.returncode != 0:
                status = git(t.worktree, "status")
                raise Stop(f"git worktree remove に失敗しました: {first_line(res)}\n{status.stdout.rstrip()}")
        steps.append(Step(f"worktree {t.worktree} を消す", f"worktree {t.worktree} を消しました", remove))
    elif worktree_registered(t):
        steps.append(Step("消えている worktree の登録を git worktree prune で外す",
                          "消えている worktree の登録を外しました",
                          lambda: must(git(t.repo_root, "worktree", "prune"), "git worktree prune の実行")))

    if ref_exists(t.repo_root, f"refs/heads/{t.branch}"):
        steps.append(Step(f"手元のブランチ {t.branch} を消す", f"手元のブランチ {t.branch} を消しました",
                          lambda: must(git(t.repo_root, "branch", "-D", t.branch), f"ブランチ {t.branch} の削除")))

    if ref_exists(t.repo_root, f"refs/remotes/origin/{t.branch}"):
        if merge.merged:
            steps.append(Step(f"origin のブランチ {t.branch} を消す", f"origin のブランチ {t.branch} を消しました",
                              lambda: must(git(t.repo_root, "push", "--quiet", "origin", "--delete", t.branch),
                                           f"origin の {t.branch} の削除")))
        else:
            steps.append(Step(f"merge されていないので origin のブランチ {t.branch} は残す",
                              f"merge されていないので origin のブランチ {t.branch} は残しました", lambda: None))

    steps.append(Step(f"記録ファイル {t.record} を消す", f"記録ファイル {t.record} を消しました",
                      lambda: t.record.unlink()))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cleanup.py", description="worker を片付ける")
    parser.add_argument("session", help="worker のセッション名（例 dotfiles.some-task）")
    parser.add_argument("--dry-run", action="store_true", help="何も変えずに予定だけ出す")
    parser.add_argument("--force-unmerged", action="store_true",
                        help="merge されていなくても片付ける（origin のブランチは残す）")
    parser.add_argument("--kill-other-windows", action="store_true",
                        help="worker 以外でその worktree を開いている window も閉じる")
    args = parser.parse_args(argv)
    # 標準出力と標準エラーを混ぜて読んでも、順番が崩れないようにする
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    prefix = "予定: " if args.dry_run else ""

    try:
        t = load_target(args.session)
        merge = check_merged(t)
        if merge.merged:
            print(f"{prefix}merge 済み: {merge.reason}")
        elif args.force_unmerged:
            print(f"{prefix}merge されていませんが --force-unmerged で続けます: {merge.reason}")
        else:
            raise Stop(f"merge 済みと判定できないので、何も消さずに止まります: {merge.reason}"
                       "（不要と決まったなら --force-unmerged）")

        wins = find_windows(t)
        if wins.others and not args.kill_other_windows:
            listing = "\n".join(f"  {wid} {path}" for wid, path in wins.others)
            raise Stop("worker のほかにその worktree を開いている window があるので、何も消さずに止まります"
                       f"（閉じてよければ --kill-other-windows）:\n{listing}")

        if t.worktree.exists():
            status = git(t.worktree, "status", "--porcelain")
            if status.returncode != 0 or status.stdout.strip():
                full = git(t.worktree, "status")
                raise Stop("worktree に commit されていない変更があるので、何も消さずに止まります:\n"
                           + (full.stdout or full.stderr).rstrip())

        steps = build_steps(t, merge, wins, args.kill_other_windows)
        for step in steps:
            if args.dry_run:
                print(f"{prefix}{step.plan}")
            else:
                step.action()
                print(step.done)

        pull = pull_step(t)
        if isinstance(pull, str):
            print(f"{prefix}{pull}")
        elif args.dry_run:
            print(f"{prefix}{pull.plan}")
        else:
            pull.action()
    except Stop as e:
        print(f"cleanup: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
