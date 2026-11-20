#!/usr/bin/env python3
"""Claude Code hook: route permission prompts of workers to the orchestrator.

Workers are background sessions (`claude --bg`) that the orchestrator started.
Nobody watches their screen, so a permission dialog in a worker used to stall
it until the user attached to it. This hook makes such calls come back to the
worker as a denial that tells it to ask the orchestrator, and lets the call
through once the user approved it there (approvals.py).

  approval-gate.py permission   (PermissionRequest: a dialog is about to show)
    - a one-shot record for this session matches the call -> allow, consume it
    - the session is a worker -> deny, and tell the worker to report the call
      as 「要判断」 to the orchestrator and rerun it unchanged once approved
    - with --panel, the orchestrator -> the call is written as an ask the Hub
      panel shows as a card (asks.new_permission), and the hook waits up to
      AGENT_PERMISSION_WAIT seconds (120 by default) for the panel's answer:
      allow -> allow this once, deny -> deny with the reason written, anything
      else (terminal, no answer in time, an answer that is not the panel's for
      the ask as written) -> no decision. The ask is removed when the hook ends.
    - otherwise (the orchestrator without --panel, sessions outside the
      orchestrator) -> no decision, the dialog shows as before

  approval-gate.py pre          (PreToolUse)
    - a session other than the orchestrator that would write approval records
      (`approvals.py add`, the approvals directory) -> deny
    - a session other than the orchestrator that would answer an ask
      (`asks.py answer` or `claim`, an `*.answer.json` file of the asks
      directory) -> deny. The Hub panel writes answers from Orca, outside any
      Claude Code session, and an answer to the orchestrator's question is
      what it turns into an approval.
    - the orchestrator too, when it would write the panel's answer
      (`asks.py answer … --by panel`) or an answer file itself -> deny. The
      panel's answer to a permission is what lets the orchestrator's call run.
    - a one-shot record for this session matches the call -> allow, consume
      it. This covers calls that get no dialog but would be refused, such as
      auto mode classifier blocks. gh writes and MCP calls with prose are left
      to external-post-guard.py, and the UI and typing commands it stops
      (orca, osascript, tmux send-keys, ...) to agent-ui-guard.py; those
      hooks consume records for them themselves.

Sessions are told apart by `claude agents --json` (see approvals.py).
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True  # keep __pycache__ out of the hooks directory
import approvals  # noqa: E402
import asks  # noqa: E402

RECORD_WRITE = re.compile(r"approvals\.py\b(?:(?![;&|\n]).)*\badd\b|state/approvals\b")
ANSWER_WRITE = re.compile(r"asks\.py\b(?:(?![;&|\n]).)*\b(?:answer|claim)\b|\.answer\.json\b")
PANEL_ANSWER = re.compile(r"asks\.py\b(?:(?![;&|\n]).)*\banswer\b(?:(?![;&|\n]).)*--by(?:=|\s+)['\"]?panel\b|\.answer\.json\b")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHOWN_LIMIT = 300


def load_guard(name="external-post-guard.py"):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py").replace("-", "_"), HERE / name)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except (OSError, SyntaxError):
        return None
    return mod


def left_to_guard(tool_name, tool_input):
    """Calls external-post-guard.py decides on (and consumes records for)."""
    guard = load_guard()
    if guard is None:
        return False
    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        ui_guard = load_guard("agent-ui-guard.py")
        if ui_guard is not None and ui_guard.problems(command):
            return True
        try:
            return bool(guard.gh_writes(command))
        except ValueError:
            return True  # unparsable; the guard checks it conservatively
    if tool_name.startswith("mcp__"):
        prose = []
        guard.collect_prose(tool_input, prose)
        return bool(prose)
    return False


def writes_records(tool_name, tool_input):
    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        return bool(RECORD_WRITE.search(command)) or str(approvals.approvals_dir()) in command
    if tool_name in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not path:
            return False
        target = Path(path).expanduser().resolve()
        root = approvals.approvals_dir().expanduser().resolve()
        return target == root or root in target.parents
    return False


def writes_answers(tool_name, tool_input):
    if tool_name == "Bash":
        return bool(ANSWER_WRITE.search(tool_input.get("command") or ""))
    if tool_name in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return path.endswith(".answer.json")
    return False


def writes_panel_answers(tool_name, tool_input):
    """Writing what only the Hub panel writes: its answers, or an answer file by hand."""
    if tool_name == "Bash":
        return bool(PANEL_ANSWER.search(tool_input.get("command") or ""))
    return writes_answers(tool_name, tool_input)


def shown(tool_name, tool_input):
    if tool_name == "Bash":
        text = tool_input.get("command") or ""
    else:
        text = json.dumps(tool_input, ensure_ascii=False)
    text = text.strip()
    if len(text) > SHOWN_LIMIT:
        text = text[:SHOWN_LIMIT] + "…"
    return f"{tool_name}: {text}"


def worker_guidance(tool_name, tool_input, why):
    lines = [
        "worker では確認ダイアログに答える人がいないので、この操作を止めました。",
        f"止めた操作: {shown(tool_name, tool_input)}",
        "別の手で回り込まずに、「要判断」として窓口（orchestrator）に SendMessage で報告し、止まってください。"
        "報告には、実行しようとしたコマンドの全文（MCP ならツール名と引数）、目的、送る本文があればその下書きのファイルのリンクを書きます。",
        "窓口から承認が届いたら、同じコマンドを 1 文字も変えずに実行し直してください。窓口の承認の記録と一致する 1 回だけ通ります。",
    ]
    if why:
        lines.append(f"（{why}）")
    return "\n".join(lines)


def emit(event, body):
    json.dump({"hookSpecificOutput": {"hookEventName": event, **body}}, sys.stdout, ensure_ascii=False)


def on_permission(data, panel=False):
    tool_name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    record, why = approvals.take(tool_name, tool_input, data.get("session_id"))
    if record:
        emit("PermissionRequest", {"decision": {"behavior": "allow"}})
        return 0
    entry = approvals.session_entry(data.get("session_id"))
    if approvals.is_worker(entry):
        emit(
            "PermissionRequest",
            {"decision": {"behavior": "deny", "message": worker_guidance(tool_name, tool_input, why)}},
        )
        return 0
    if panel and approvals.is_orchestrator(entry):
        decision = asks.panel_decision(entry, data)
        if decision:
            emit("PermissionRequest", {"decision": decision})
    return 0


def on_pre(data):
    tool_name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    session_id = data.get("session_id")

    if writes_records(tool_name, tool_input) and not approvals.is_orchestrator(approvals.session_entry(session_id)):
        emit(
            "PreToolUse",
            {
                "permissionDecision": "deny",
                "permissionDecisionReason": "承認の記録を書けるのは窓口（orchestrator）だけです。"
                "承認が要る操作は「要判断」として窓口に報告し、窓口からの承認を待ってください。",
            },
        )
        return 0

    if writes_answers(tool_name, tool_input) and not approvals.is_orchestrator(approvals.session_entry(session_id)):
        emit(
            "PreToolUse",
            {
                "permissionDecision": "deny",
                "permissionDecisionReason": "依頼に答えられるのは、人（Hub パネル）と窓口（orchestrator）だけです。"
                "答えが要るときは、窓口に報告して待ってください。",
            },
        )
        return 0

    if writes_panel_answers(tool_name, tool_input):
        emit(
            "PreToolUse",
            {
                "permissionDecision": "deny",
                "permissionDecisionReason": "パネルの答え（--by panel、答えのファイル）を書けるのは Hub パネルだけです。"
                "窓口が依頼を取るときは asks.py claim、窓口の答えは --by orchestrator を使ってください。"
                "許可の確認には、窓口からは答えられません。",
            },
        )
        return 0

    if not approvals.has_records() or left_to_guard(tool_name, tool_input):
        return 0
    record, _ = approvals.take(tool_name, tool_input, session_id)
    if record:
        emit(
            "PreToolUse",
            {
                "permissionDecision": "allow",
                "permissionDecisionReason": "窓口で承認済みの操作です: " + (record.get("note") or record.get("id", "")),
            },
        )
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else ""
    if mode not in ("pre", "permission"):
        print("usage: approval-gate.py pre|permission [--panel]", file=sys.stderr)
        return 0  # never block a tool call because of a wiring mistake
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    return on_pre(data) if mode == "pre" else on_permission(data, panel="--panel" in argv[1:])


if __name__ == "__main__":
    sys.exit(main())
