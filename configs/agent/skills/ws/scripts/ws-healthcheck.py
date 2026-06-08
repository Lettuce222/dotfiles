#!/usr/bin/env python3
"""ws Vault の静的 health-check。

判断不要な機械検査だけをここで行う（統廃合などの判断は Claude 側）。
出力は JSON。Claude がこれを読んで自然言語の整理提案に変換する。

検査項目:
  - unresolved-link    : 実体の無い [[リンク]]（typo か、これから作る stub。エラーではなく情報）
  - orphan             : どこからも [[リンク]] されていないノート
  - unreachable        : HOME.md から [[リンク]] を辿って到達できないノート
  - missing-frontmatter: type / updated が欠落
  - duplicate-note-key : [[リンク]] 解決に使うファイル名 stem の重複
  - unexpected-root-note: トップ直下に HOME.md / MOC-*.md 以外のノートがある
  - misplaced-note     : frontmatter type と推奨ディレクトリが一致しない
  - stale-initiative   : status: active だが updated が古い（既定 30 日）
  - low-information-density: 長いのに読者の不確実性を減らす信号が少ない文章

リンク抽出時はコードスパン/コードブロック（バッククォート内の例）と
`...` を含むプレースホルダを除外する。Obsidian では未作成ノートへの
forward link は正常な運用（これから作る印）なので、unresolved は
エラーではなく「typo の疑い or 未作成 stub」の気づきとして扱う。

低情報量の文章は直接は測れないため、ここでは代理指標を見る。
「長いのに、読者の不確実性を減らす信号が少ない段落」を検出する。

Vault パス解決: --vault フラグ > $WORK_VAULT > ~/workspace
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

# daily/ や _archive/、templates/ は orphan/unreachable 判定の対象外にする。
# （日次ノートはリンクされなくて当然、archive は退避済み、templates は雛形）
EXCLUDED_DIRS = {"_archive", "templates", ".obsidian", ".trash"}
EXCLUDED_FILES = {"AGENTS.md"}
DAILY_DIR = "daily"
HOME_NOTE = "HOME"
TYPE_DIRS = {
    "concept": "concepts",
    "decision": "decisions",
    "initiative": "initiatives",
    "pattern": "patterns",
    "person": "people",
    "reference": "references",
}

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
NUMBER_RE = re.compile(r"\d")
URL_RE = re.compile(r"https?://")
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9/-]{1,}\b")
QUOTED_TERM_RE = re.compile(r"「[^」]{2,}」")

SIGNAL_TERMS = {
    "目的",
    "現状",
    "次",
    "未解決",
    "論点",
    "判断",
    "決定",
    "根拠",
    "リスク",
    "影響",
    "原因",
    "対応",
    "実行",
    "確認",
    "追加",
    "削除",
    "更新",
    "改善",
    "合意",
    "期限",
    "依頼",
    "共有",
    "説明",
    "指標",
    "タスク",
    "担当",
    "完了",
    "保留",
    "問題",
    "仮説",
    "検証",
}

FILLER_PATTERNS = [
    "することができる",
    "していく",
    "していきたい",
    "重要である",
    "必要がある",
    "可能性がある",
    "と考えられる",
    "と思われる",
]


def strip_code(text: str) -> str:
    """コードブロック/コードスパンを除去（その中の [[例]] はリンクではない）。"""
    text = FENCED_CODE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    return text


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def extract_links(text: str) -> set[str]:
    """本文から実リンクの集合を返す。コードと `...` プレースホルダは除外。"""
    targets = set()
    for raw in WIKILINK_RE.findall(strip_code(text)):
        target = raw.strip()
        if "..." in target or target == "":
            continue
        targets.add(target)
    return targets


def resolve_vault(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser()
    env = os.environ.get("WORK_VAULT")
    if env:
        return Path(env).expanduser()
    return Path.home() / "workspace"


def note_key(path: Path) -> str:
    """[[リンク]] の解決に使うキー = 拡張子なしのファイル名（stem）。"""
    return path.stem


def is_area_root_note(path: Path, vault: Path) -> bool:
    rel = path.relative_to(vault)
    return len(rel.parts) == 1 and (path.name == "HOME.md" or path.name.startswith("MOC-"))


def expected_meeting_year(path: Path) -> str | None:
    m = re.match(r"meeting-(\d{4})-\d{2}-\d{2}-", path.stem)
    if not m:
        return None
    return m.group(1)


def is_excluded(path: Path, vault: Path) -> bool:
    rel_parts = path.relative_to(vault).parts
    return any(part in EXCLUDED_DIRS for part in rel_parts[:-1])


def parse_frontmatter(text: str) -> dict[str, str]:
    """素朴な YAML frontmatter パーサ（PyYAML 非依存・1 階層の key: value のみ）。"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def parse_date(value: str) -> dt.date | None:
    value = value.strip().strip("'\"")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def compact_excerpt(text: str, limit: int = 120) -> str:
    excerpt = re.sub(r"\s+", " ", text).strip()
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: limit - 1] + "…"


def prose_blocks(text: str) -> list[tuple[int, str, str]]:
    """Markdown から prose block を取り出す。

    戻り値は (line, kind, body)。heading / code / dataview / tasks query は対象外。
    """
    stripped = strip_frontmatter(text)
    blocks: list[tuple[int, str, str]] = []
    in_code = False
    paragraph: list[str] = []
    paragraph_start = 1

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append((paragraph_start, "paragraph", " ".join(paragraph).strip()))
            paragraph = []

    for index, line in enumerate(stripped.splitlines(), start=1):
        raw = line.rstrip()
        if raw.startswith("```"):
            flush_paragraph()
            in_code = not in_code
            continue
        if in_code:
            continue
        if not raw.strip():
            flush_paragraph()
            continue
        if raw.startswith("#") or raw.startswith("|"):
            flush_paragraph()
            continue
        if re.match(r"^\s*[-*]\s+\[[ xX]\]", raw):
            flush_paragraph()
            continue
        list_match = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", raw)
        if list_match:
            flush_paragraph()
            blocks.append((index, "list-item", list_match.group(1).strip()))
            continue
        if not paragraph:
            paragraph_start = index
        paragraph.append(raw.strip())

    flush_paragraph()
    return blocks


def signal_count(text: str) -> int:
    count = 0
    count += len(WIKILINK_RE.findall(text))
    count += len(INLINE_CODE_RE.findall(text))
    count += len(DATE_RE.findall(text))
    count += len(ACRONYM_RE.findall(text))
    count += len(QUOTED_TERM_RE.findall(text))
    count += 1 if URL_RE.search(text) else 0
    count += 1 if NUMBER_RE.search(text) else 0
    count += sum(1 for term in SIGNAL_TERMS if term in text)
    return count


def filler_count(text: str) -> int:
    return sum(text.count(pattern) for pattern in FILLER_PATTERNS)


def information_density_findings(path: Path, vault: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    for line, kind, body in prose_blocks(text):
        cleaned = strip_code(body)
        char_count = len(cleaned)
        signals = signal_count(body)
        fillers = filler_count(cleaned)

        if char_count >= 140 and signals == 0:
            findings.append(
                {
                    "note": str(path.relative_to(vault)),
                    "line": line,
                    "kind": "long-low-signal-block",
                    "chars": char_count,
                    "signals": signals,
                    "reason": "長いが、リンク・日付・数値・判断語・行動語がない",
                    "excerpt": compact_excerpt(cleaned),
                }
            )
        elif char_count >= 220 and signals <= 1:
            findings.append(
                {
                    "note": str(path.relative_to(vault)),
                    "line": line,
                    "kind": "diffuse-block",
                    "chars": char_count,
                    "signals": signals,
                    "reason": "かなり長いが、読者の状態を変える信号が少ない",
                    "excerpt": compact_excerpt(cleaned),
                }
            )
        if fillers >= 2 and char_count >= 80:
            findings.append(
                {
                    "note": str(path.relative_to(vault)),
                    "line": line,
                    "kind": "filler-heavy-block",
                    "chars": char_count,
                    "signals": signals,
                    "fillers": fillers,
                    "reason": "一般的な言い回しが重なっている",
                    "excerpt": compact_excerpt(cleaned),
                }
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="ws Vault health-check")
    parser.add_argument("--vault", help="Vault パス（既定: $WORK_VAULT または ~/workspace）")
    parser.add_argument("--stale-days", type=int, default=30, help="initiative を stale とみなす経過日数")
    parser.add_argument("--today", help="基準日（YYYY-MM-DD, 既定は本日）。テスト用")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    if not vault.is_dir():
        print(json.dumps({"error": f"vault not found: {vault}"}, ensure_ascii=False))
        return 1

    today = parse_date(args.today) if args.today else dt.date.today()

    notes: dict[str, Path] = {}        # note_key -> path（本体ノート）
    note_paths: dict[str, list[Path]] = {}  # note_key -> 同じ stem を持つパス
    aliases: dict[str, str] = {}        # alias -> note_key
    frontmatters: dict[str, dict] = {}  # note_key -> frontmatter
    links_out: dict[str, set[str]] = {} # note_key -> 参照先 note_key 集合

    all_md = sorted(
        p
        for p in vault.rglob("*.md")
        if p.name not in EXCLUDED_FILES and not is_excluded(p, vault)
    )

    for path in all_md:
        note_paths.setdefault(note_key(path), []).append(path)

    duplicate_note_keys = [
        {
            "note_key": key,
            "paths": [str(path.relative_to(vault)) for path in paths],
        }
        for key, paths in note_paths.items()
        if len(paths) > 1
    ]

    # パス1: ノートと alias を登録
    # 同じ stem が重複している場合は最初のパスを使って解析を続け、重複は report で返す。
    for path in all_md:
        key = note_key(path)
        if key in notes:
            continue
        notes[key] = path
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        frontmatters[key] = fm
        raw_aliases = fm.get("aliases", "")
        for alias in re.findall(r"[^\[\],]+", raw_aliases):
            alias = alias.strip()
            if alias:
                aliases[alias] = key

    # パス2: リンク抽出
    for path in all_md:
        key = note_key(path)
        if notes.get(key) != path:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        links_out[key] = extract_links(text)

    def resolve_target(target: str) -> str | None:
        if target in notes:
            return target
        if target in aliases:
            return aliases[target]
        return None

    unresolved_links: list[dict] = []
    incoming: dict[str, set[str]] = {k: set() for k in notes}

    for key, targets in links_out.items():
        for target in targets:
            resolved = resolve_target(target)
            if resolved is None:
                unresolved_links.append({"note": str(notes[key].relative_to(vault)), "link": target})
            else:
                incoming[resolved].add(key)

    def is_daily(key: str) -> bool:
        return notes[key].relative_to(vault).parts[0] == DAILY_DIR

    # orphan: 誰からもリンクされていない（HOME と daily を除く）
    orphans = [
        str(notes[k].relative_to(vault))
        for k in notes
        if not incoming[k] and k != HOME_NOTE and not is_daily(k)
    ]

    # unreachable: HOME から辿れない（daily を除く）
    reachable: set[str] = set()
    if HOME_NOTE in notes:
        stack = [HOME_NOTE]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            for target in links_out.get(cur, set()):
                resolved = resolve_target(target)
                if resolved and resolved not in reachable:
                    stack.append(resolved)
    unreachable = [
        str(notes[k].relative_to(vault))
        for k in notes
        if k not in reachable and k != HOME_NOTE and not is_daily(k)
    ]

    # missing-frontmatter
    missing_frontmatter = [
        str(notes[k].relative_to(vault))
        for k in notes
        if not is_daily(k) and (not frontmatters[k].get("type") or not frontmatters[k].get("updated"))
    ]

    unexpected_root_note = [
        str(path.relative_to(vault))
        for path in all_md
        if len(path.relative_to(vault).parts) == 1 and not is_area_root_note(path, vault)
    ]

    misplaced_note = []
    for key, path in notes.items():
        if is_daily(key):
            continue
        rel = path.relative_to(vault)
        parts = rel.parts
        fm_type = frontmatters[key].get("type")
        expected_dir = TYPE_DIRS.get(fm_type)
        if fm_type == "area":
            if not is_area_root_note(path, vault):
                misplaced_note.append({
                    "note": str(rel),
                    "type": fm_type,
                    "expected": "HOME.md or MOC-*.md at vault root",
                })
        elif fm_type == "meeting":
            year = expected_meeting_year(path)
            expected = f"meetings/{year}/" if year else "meetings/YYYY/"
            if len(parts) < 3 or parts[0] != "meetings" or (year and parts[1] != year):
                misplaced_note.append({"note": str(rel), "type": fm_type, "expected": expected})
        elif expected_dir and parts[0] != expected_dir:
            misplaced_note.append({"note": str(rel), "type": fm_type, "expected": f"{expected_dir}/"})

    # stale-initiative
    stale = []
    for k, fm in frontmatters.items():
        if fm.get("type") == "initiative" and fm.get("status") == "active":
            updated = parse_date(fm.get("updated", ""))
            if updated and (today - updated).days > args.stale_days:
                stale.append({
                    "note": str(notes[k].relative_to(vault)),
                    "updated": updated.isoformat(),
                    "days_since": (today - updated).days,
                })

    low_information_density = []
    for key, path in notes.items():
        if is_daily(key):
            continue
        low_information_density.extend(information_density_findings(path, vault))

    report = {
        "vault": str(vault),
        "note_count": len(notes),
        "unresolved_link": sorted(unresolved_links, key=lambda x: x["note"]),
        "orphan": sorted(orphans),
        "unreachable": sorted(unreachable),
        "missing_frontmatter": sorted(missing_frontmatter),
        "duplicate_note_key": sorted(duplicate_note_keys, key=lambda x: x["note_key"]),
        "unexpected_root_note": sorted(unexpected_root_note),
        "misplaced_note": sorted(misplaced_note, key=lambda x: x["note"]),
        "stale_initiative": sorted(stale, key=lambda x: x["note"]),
        "low_information_density": sorted(
            low_information_density,
            key=lambda x: (x["note"], x["line"], x["kind"]),
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
