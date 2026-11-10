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
    - otherwise (the orchestrator, sessions outside the orchestrator) -> no
      decision, the dialog shows as before

  approval-gate.py pre          (PreToolUse)
    - a session other than the orchestrator that would write approval records
      (`approvals.py add`, the approvals directory) -> deny
    - a one-shot record for this session matches the call -> allow, consume
      it. This covers calls that get no dialog but would be refused, such as
      auto mode classifier blocks. gh writes and MCP calls with prose are left
      to external-post-guard.py, which consumes records for those itself.

Sessions are told apart by `claude agents --json` (see approvals.py).
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True  # keep __pycache__ out of the hooks directory
import approvals  # noqa: E402

RECORD_WRITE = re.compile(r"approvals\.py\b(?:(?![;&|\n]).)*\badd\b|state/approvals\b")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHOWN_LIMIT = 300


def load_guard():
    spec = importlib.util.spec_from_file_location("external_post_guard", HERE / "external-post-guard.py")
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
        try:
            return bool(guard.gh_writes(tool_input.get("command") or ""))
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


def on_permission(data):
    tool_name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    record, why = approvals.take(tool_name, tool_input, data.get("session_id"))
    if record:
        emit("PermissionRequest", {"decision": {"behavior": "allow"}})
        return 0
    if approvals.is_worker(approvals.session_entry(data.get("session_id"))):
        emit(
            "PermissionRequest",
            {"decision": {"behavior": "deny", "message": worker_guidance(tool_name, tool_input, why)}},
        )
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
        print("usage: approval-gate.py pre|permission", file=sys.stderr)
        return 0  # never block a tool call because of a wiring mistake
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    return on_pre(data) if mode == "pre" else on_permission(data)


if __name__ == "__main__":
    sys.exit(main())
