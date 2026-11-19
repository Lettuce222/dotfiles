"""asks.py（worker が書く依頼のファイル）のテスト。

実行: python3 -m unittest configs/agent/tests/test_asks.py

asks.py をサブプロセスで呼ぶ。`claude agents --json` は PATH に置いた偽の claude が返す。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "hooks" / "asks.py"

WORKER = "sess-worker"
OTHER = "sess-other"
ORCH = "sess-orchestrator"
WATCH = "sess-watch"
INTERACTIVE = "sess-interactive"


class AsksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.hub = root / "hub"
        (self.hub / "workers" / "impl-x").mkdir(parents=True)
        (self.hub / "workers" / "impl-x" / "report.md").write_text("# report\n")
        self.dir = self.hub / "state" / "asks"
        bindir = root / "bin"
        bindir.mkdir()
        agents = root / "agents.json"
        agents.write_text(
            json.dumps(
                [
                    {"sessionId": WORKER, "id": "aaaaaaaa", "name": "impl-x", "kind": "background", "cwd": "/w/x"},
                    {"sessionId": OTHER, "id": "bbbbbbbb", "name": "impl-y", "kind": "background", "cwd": "/w/y"},
                    {"sessionId": ORCH, "name": "orchestrator", "kind": "interactive"},
                    {"sessionId": WATCH, "name": "chore-hub-watch", "kind": "background"},
                    {"sessionId": INTERACTIVE, "name": "dotfiles-1", "kind": "interactive"},
                ]
            )
        )
        fake = bindir / "claude"
        fake.write_text(f"#!/bin/sh\ncat '{agents}'\n")
        fake.chmod(0o755)
        self.env = {
            **{k: v for k, v in os.environ.items() if k not in ("AGENT_ASKS_DIR", "AGENT_ORCHESTRATOR_NAME")},
            "AGENT_ORCHESTRATOR_HOME": str(self.hub),
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "CLAUDE_CODE_SESSION_ID": WORKER,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_asks(self, *args, session=WORKER):
        env = {**self.env, "CLAUDE_CODE_SESSION_ID": session} if session else {
            k: v for k, v in self.env.items() if k != "CLAUDE_CODE_SESSION_ID"
        }
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)

    def decide(self, session=WORKER, **extra):
        args = ["decide", "--question", "設定をどこに置きますか", "--option", "configs/x|configs/x に置く",
                "--option", "configs/y|configs/y に置く", "--recommended", "1"]
        for k, v in extra.items():
            args += [f"--{k}", v]
        return self.run_asks(*args, session=session)

    def files(self):
        return sorted(p.name for p in self.dir.glob("*.json")) if self.dir.is_dir() else []

    def test_decide_writes_an_ask_with_the_callers_identity(self):
        r = self.decide(case="orca-setup")
        self.assertEqual(r.returncode, 0, r.stderr)
        ask = json.loads(Path(r.stdout.strip()).read_text())
        self.assertEqual(ask["kind"], "decide")
        self.assertEqual((ask["worker"], ask["session_id"], ask["job_id"], ask["cwd"]), ("impl-x", WORKER, "aaaaaaaa", "/w/x"))
        self.assertEqual(ask["report"], str(self.hub / "workers" / "impl-x" / "report.md"))
        self.assertEqual(ask["options"][0], {"label": "configs/x", "description": "configs/x に置く"})
        self.assertEqual((ask["recommended"], ask["case"], ask["level"]), (1, "orca-setup", "B"))

    def test_only_workers_write_asks(self):
        for session in (ORCH, WATCH, INTERACTIVE, "sess-unknown", None):
            r = self.decide(session=session)
            self.assertEqual(r.returncode, 2, session)
        self.assertEqual(self.files(), [])

    def test_bad_input_is_refused(self):
        self.assertEqual(self.run_asks("decide", "--question", "q", "--option", "a|b").returncode, 2)
        self.assertEqual(self.run_asks("decide", "--question", "q", "--option", "ab", "--option", "c|d").returncode, 2)
        self.assertEqual(self.run_asks("decide", "--question", "q‮", "--option", "a|b", "--option", "c|d").returncode, 2)
        self.assertEqual(self.run_asks("decide", "--question", "q", "--option", "a|b", "--option", "c|d", "--recommended", "3").returncode, 2)
        self.assertEqual(self.decide(case="../x").returncode, 2)
        self.assertEqual(self.decide(level="Z").returncode, 2)
        self.assertEqual(self.run_asks("next", "--suggest", "a|-rf|r").returncode, 2)
        self.assertEqual(self.run_asks("next", "--suggest", "a|b").returncode, 2)
        self.assertEqual(self.run_asks("next", "--suggest", "x" * 31 + "|p|r").returncode, 2)
        self.assertEqual(self.run_asks("next", *["--suggest", "a|p|r"] * 4).returncode, 2)
        self.assertEqual(self.files(), [])

    def test_next_keeps_the_suggestions(self):
        r = self.run_asks("next", "--suggest", "CI を見る|PR の CI を見て、落ちていれば直して|push したので")
        self.assertEqual(r.returncode, 0, r.stderr)
        ask = json.loads(Path(r.stdout.strip()).read_text())
        self.assertEqual(ask["suggestions"], [{"label": "CI を見る", "prompt": "PR の CI を見て、落ちていれば直して", "reason": "push したので"}])

    def test_a_new_ask_replaces_the_open_ones_of_the_same_session(self):
        first = Path(self.decide().stdout.strip())
        other = Path(self.decide(session=OTHER).stdout.strip())
        second = Path(self.decide().stdout.strip())
        self.assertFalse(first.exists())
        self.assertTrue(other.exists() and second.exists())

    def test_answer_is_taken_once(self):
        path = Path(self.decide().stdout.strip())
        ask_id = path.stem
        shown = hashlib.sha256(path.read_bytes()).hexdigest()
        r = self.run_asks("answer", ask_id, "--by", "panel", "--choice", "1", "--shown", shown, session=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["id"], ask_id)
        answer = json.loads((self.dir / f"{ask_id}.answer.json").read_text())
        self.assertEqual((answer["by"], answer["choice"], answer["shown_sha256"]), ("panel", "1", shown))
        self.assertEqual(self.run_asks("claim", ask_id).returncode, 3)
        listed = json.loads(self.run_asks("list", "--json").stdout)
        self.assertEqual(listed, [])
        self.assertEqual(len(json.loads(self.run_asks("list", "--json", "--all").stdout)), 1)

    def test_changed_or_missing_ask_is_not_taken(self):
        path = Path(self.decide().stdout.strip())
        r = self.run_asks("answer", path.stem, "--by", "panel", "--choice", "1", "--shown", "0" * 64)
        self.assertEqual(r.returncode, 4)
        self.assertFalse((self.dir / f"{path.stem}.answer.json").exists())
        self.assertEqual(self.run_asks("answer", "20261119-000000-deadbeef", "--by", "panel", "--choice", "1").returncode, 4)
        self.assertEqual(self.run_asks("answer", "../x", "--by", "panel", "--choice", "1").returncode, 2)

    def test_only_one_of_simultaneous_answers_wins(self):
        path = Path(self.decide().stdout.strip())
        codes = []

        def take(by):
            codes.append(self.run_asks("answer", path.stem, "--by", by, "--choice", "1").returncode)

        threads = [threading.Thread(target=take, args=(by,)) for by in ("panel", "orchestrator") * 3]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(codes), [0, 3, 3, 3, 3, 3])

    def test_close_by_id_and_by_worker(self):
        a = Path(self.decide().stdout.strip())
        b = Path(self.decide(session=OTHER).stdout.strip())
        self.run_asks("claim", a.stem)
        self.assertEqual(self.run_asks("close", "--worker", "impl-x").returncode, 0)
        self.assertEqual(self.files(), [b.name])
        self.assertEqual(self.run_asks("close", b.stem).returncode, 0)
        self.assertEqual(self.files(), [])


class OrchestratorQuestionTest(AsksTest):
    def question(self, *extra, session=ORCH):
        body = Path(self.tmp.name) / "draft.md"
        body.write_text("レビューありがとうございます。\n直しました。\n")
        return self.run_asks("question", "--question", "#809 への返信を送りますか", "--option", "送る|gh pr comment で送る",
                             "--option", "見送る|送らない", "--body", str(body), "--approval", *extra, session=session)

    def test_only_the_orchestrator_writes_a_question_with_its_whole_body(self):
        for session in (WORKER, INTERACTIVE, None):
            self.assertEqual(self.question(session=session).returncode, 2, session)
        r = self.question()
        self.assertEqual(r.returncode, 0, r.stderr)
        ask = json.loads(Path(r.stdout.strip()).read_text())
        self.assertEqual((ask["kind"], ask["worker"], ask["approval"]), ("question", "orchestrator", True))
        self.assertEqual(ask["body"], "レビューありがとうございます。\n直しました。\n")
        self.assertEqual([o["label"] for o in ask["options"]], ["送る", "見送る"], "only the real answers")
        second = self.question()
        self.assertTrue(Path(r.stdout.strip()).exists(), "the orchestrator may wait on several questions")
        self.assertTrue(Path(second.stdout.strip()).exists())

    def test_the_panel_answer_is_checked_by_its_writer_and_verified_against_the_ask(self):
        path = Path(self.question().stdout.strip())
        shown = hashlib.sha256(path.read_bytes()).hexdigest()
        r = self.run_asks("answer", path.stem, "--by", "panel", "--choice", "1", "--shown", shown, session=None)
        self.assertEqual(r.returncode, 2, "not run from Orca's plugin host")
        self.assertIn("Hub パネルだけ", r.stderr)
        self.assertEqual(self.run_asks("verify", path.stem).returncode, 4, "no answer yet")

        sys.path.insert(0, str(SCRIPT.parent))
        import importlib
        asks = importlib.import_module("asks")
        with mock.patch.dict(os.environ, {"AGENT_ASKS_DIR": str(self.dir)}):
            code, _ = asks.answer(path.stem, "panel", "1", shown, panel_check=lambda: True)
            self.assertEqual(code, 0)
            code, out = asks.verify(path.stem)
            self.assertEqual((code, out["choice"], out["label"], out["approval"]), (0, 1, "送る", True))
            # The ask changed after the card showed it: not an answer to it.
            raw = json.loads(path.read_text())
            raw["body"] = "差し替えた本文"
            path.write_text(json.dumps(raw))
            self.assertEqual(asks.verify(path.stem)[0], 4)

    def test_an_answer_by_the_orchestrator_is_not_verified_as_the_panels(self):
        path = Path(self.question().stdout.strip())
        self.assertEqual(self.run_asks("claim", path.stem, session=ORCH).returncode, 0)
        r = self.run_asks("verify", path.stem)
        self.assertEqual(r.returncode, 4)
        self.assertIn("パネルの答えではありません", r.stderr)

    def test_from_panel_reads_the_parent_chain(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import importlib
        asks = importlib.import_module("asks")
        chain = {os.getppid(): (10, asks.ORCA_HELPER), 10: (1, asks.ORCA_MAIN)}
        read = lambda pid: chain.get(pid, (None, None))
        self.assertTrue(asks.from_panel(read, env={}))
        self.assertFalse(asks.from_panel(read, env={"CLAUDE_CODE_SESSION_ID": "x"}))
        self.assertFalse(asks.from_panel(lambda pid: {os.getppid(): (10, asks.ORCA_HELPER), 10: (1, "/bin/zsh")}.get(pid, (None, None)), env={}))
        self.assertFalse(asks.from_panel(lambda pid: {os.getppid(): (10, "/bin/zsh")}.get(pid, (None, None)), env={}))


if __name__ == "__main__":
    unittest.main()
