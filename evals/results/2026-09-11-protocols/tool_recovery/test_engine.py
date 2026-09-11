"""Local integration and real process-exit tests for the public resume entry point."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from engine import RecoveryStateError, RecoveryUnavailableError, ToolExecutionError, resume
from fakes import Model, Tools, encoded


CALLS = [
    {"call_id": "call-z", "operation_key": "op-3", "arguments": {"value": 3}},
    {"call_id": "call-a", "operation_key": "op-1", "arguments": {"value": 1}},
    {"call_id": "call-m", "operation_key": "op-2", "arguments": {"value": 2}},
]


def expected(calls=CALLS):
    return [{"call_id": call["call_id"], "result": {
        "operation_key": call["operation_key"], "value": call["arguments"]
    }} for call in calls]


def adapters(root, calls=CALLS, **kwargs):
    return Model(root / "model.db", copy.deepcopy(calls)), Tools(root / "tools.db", **kwargs)


class NeverCalled:
    def __getattr__(self, name):
        raise AssertionError(f"Unexpected adapter access: {name}")


class CheckpointStop(Exception):
    pass


def worker(root, stage, call_id):
    model, tools = adapters(root)
    if stage == "after_conflict":
        tools.execute("op-3", {"value": "previous content"})

        class ConflictExit(Tools):
            def execute(self, key, arguments):
                try:
                    return super().execute(key, arguments)
                except ValueError:
                    os._exit(47)
        tools = ConflictExit(root / "tools.db")
    if stage in {"before_effect", "after_effect"}:
        class ExitingTools(Tools):
            def execute(self, key, arguments):
                if key == "op-1":
                    if stage == "after_effect":
                        super().execute(key, arguments)
                    os._exit(47)
                return super().execute(key, arguments)
        tools = ExitingTools(root / "tools.db")
    if stage == "after_finish":
        class ExitingModel(Model):
            def finish(self, messages):
                super().finish(messages)
                os._exit(47)
        model = ExitingModel(root / "model.db", CALLS)

    def fault(event, identity):
        if event == stage and identity == call_id:
            os._exit(47)
    resume(root / "run.db", model, tools, fault)
    raise AssertionError("The process exit point was not reached")


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tool-recovery-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "run.db"

    def rows(self, sql, args=()):
        with sqlite3.connect(self.db_path) as db:
            return list(db.execute(sql, args))

    def assert_complete(self, model, tools, calls=CALLS):
        self.assertEqual(model.history()[-1], ("finish", expected(calls)))
        self.assertEqual(len(tools.effects()), len({c["operation_key"] for c in calls}))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM messages WHERE consumed=1"), [(len(calls),)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("PRAGMA integrity_check"), [("ok",)])
        lineage = self.rows(
            "SELECT c.call_id,o.operation_key,a.kind FROM calls c "
            "JOIN operations o USING(operation_key) "
            "JOIN attempts a ON a.id=o.result_attempt_id ORDER BY c.position"
        )
        self.assertEqual([(row[0], row[1]) for row in lineage],
                         [(c["call_id"], c["operation_key"]) for c in calls])
        decision = json.loads(self.rows("SELECT decision_json FROM run")[0][0])
        self.assertEqual(decision["calls"], calls)

    def test_order_pairing_history_and_repeat_final(self):
        model, tools = adapters(self.root)
        result = resume(self.db_path, model, tools)
        self.assertEqual(json.loads(result), expected())
        self.assert_complete(model, tools)
        self.assertEqual([kind for kind, _ in model.history()], ["plan", "finish"])
        self.assertEqual(tools.history(), [("execute", c["operation_key"]) for c in CALLS])
        self.assertEqual(resume(self.db_path, NeverCalled(), NeverCalled()), result)

    def test_exception_hooks_commit_before_callback_and_do_not_repeat(self):
        checkpoints = [("decision_saved", None)] + [
            (event, c["call_id"]) for event in ("result_saved", "message_saved") for c in CALLS
        ]
        for stage, call_id in checkpoints:
            with self.subTest(stage=stage, call_id=call_id), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                model, tools = adapters(root)
                fired = []

                def fault(event, identity):
                    fired.append((event, identity))
                    if (event, identity) != (stage, call_id):
                        return
                    with sqlite3.connect(root / "run.db") as db:
                        if event == "decision_saved":
                            self.assertEqual(db.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 3)
                        elif event == "result_saved":
                            row = db.execute("SELECT result_ready, result_json FROM calls "
                                             "JOIN operations USING(operation_key) WHERE call_id=?",
                                             (identity,)).fetchone()
                            self.assertEqual(row[0], 1)
                            self.assertIsNotNone(row[1])
                        else:
                            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages WHERE call_id=?",
                                                        (identity,)).fetchone()[0], 1)
                    raise CheckpointStop()

                with self.assertRaises(CheckpointStop):
                    resume(root / "run.db", model, tools, fault)
                self.assertNotIn("finish", [k for k, _ in model.history()])
                changed_model = Model(root / "model.db", [])
                after = []
                self.assertEqual(json.loads(resume(root / "run.db", changed_model, tools,
                                                   lambda e, i: after.append((e, i)))), expected())
                self.assertTrue(set(fired).isdisjoint(after))
                self.assertEqual([k for k, _ in model.history()], ["plan", "finish"])
                self.assertEqual(tools.history(), [("execute", c["operation_key"]) for c in CALLS])

    def test_real_process_exit_and_reopen_at_each_checkpoint(self):
        checkpoints = [("decision_saved", None)] + [
            (event, c["call_id"]) for event in ("result_saved", "message_saved") for c in CALLS
        ] + [("before_effect", None), ("after_effect", None)]
        for stage, call_id in checkpoints:
            with self.subTest(stage=stage, call_id=call_id), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                completed = subprocess.run(
                    [sys.executable, "-B", __file__, "--worker", str(root), stage, call_id or ""],
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(completed.returncode, 47, completed.stdout + completed.stderr)
                model, tools = adapters(root, calls=[])
                self.assertEqual(json.loads(resume(root / "run.db", model, tools)), expected())
                self.assertEqual([k for k, _ in model.history()], ["plan", "finish"])
                self.assertEqual([key for kind, key in tools.history() if kind == "execute"],
                                 [c["operation_key"] for c in CALLS])
                self.assertEqual(len(tools.effects()), 3)
                if stage in {"before_effect", "after_effect"}:
                    self.assertIn(("lookup", "op-1"), tools.history())

    def test_response_lost_after_effect_is_reconciled(self):
        model, tools = adapters(self.root, lose_once="op-1")
        self.assertEqual(json.loads(resume(self.db_path, model, tools)), expected())
        self.assert_complete(model, tools)
        self.assertEqual(tools.history().count(("execute", "op-1")), 1)
        self.assertEqual(tools.history().count(("lookup", "op-1")), 1)
        self.assertEqual(self.rows("SELECT kind,status FROM attempts WHERE operation_key='op-1'"),
                         [("execute", "unknown"), ("lookup", "completed")])

    def test_lookup_outage_preserves_partial_progress_and_never_resends(self):
        model, tools = adapters(self.root, lose_once="op-1", lookup_unavailable=True)
        for _ in range(2):
            with self.assertRaisesRegex(RecoveryUnavailableError, "op-1"):
                resume(self.db_path, model, tools)
        self.assertEqual([kind for kind, _ in model.history()], ["plan"])
        self.assertEqual(self.rows("SELECT call_id FROM messages"), [("call-z",)])
        self.assertEqual(tools.history().count(("execute", "op-3")), 1)
        self.assertEqual(tools.history().count(("execute", "op-1")), 1)
        self.assertNotIn(("execute", "op-2"), tools.history())
        self.assertEqual(self.rows("SELECT COUNT(*) FROM attempts WHERE status='unavailable'"), [(2,)])
        tools = Tools(self.root / "tools.db")
        self.assertEqual(json.loads(resume(self.db_path, model, tools)), expected())
        self.assert_complete(model, tools)
        self.assertEqual(tools.history().count(("execute", "op-1")), 1)

    def test_alias_call_reuses_result_but_preserves_both_messages(self):
        calls = copy.deepcopy(CALLS)
        calls.append({**calls[0], "call_id": "new-call-id"})
        model, tools = adapters(self.root, calls)
        self.assertEqual(json.loads(resume(self.db_path, model, tools)), expected(calls))
        self.assert_complete(model, tools, calls)
        self.assertEqual(len(tools.history()), 3)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM calls"), [(4,)])

    def test_changed_arguments_and_duplicate_call_ids_rejected_before_tools(self):
        variants = [
            CALLS + [{"call_id": "different-id", "operation_key": "op-3", "arguments": {"value": 99}}],
            CALLS + [CALLS[0]],
        ]
        for calls in variants:
            with self.subTest(calls=calls), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                model, tools = adapters(root, calls)
                with self.assertRaises(ValueError):
                    resume(root / "run.db", model, tools)
                self.assertEqual(tools.history(), [])
                self.assertEqual([k for k, _ in model.history()], ["plan"])

    def test_existing_downstream_key_conflict_does_not_reuse_wrong_result(self):
        model, tools = adapters(self.root)
        tools.execute("op-3", {"value": "previous content"})
        for _ in range(2):
            with self.assertRaises(ValueError):
                resume(self.db_path, model, tools)
        # The simulator rolls back its request row when it rejects content.
        self.assertEqual(tools.history(), [("execute", "op-3")])
        self.assertEqual(self.rows("SELECT result_json FROM operations WHERE operation_key='op-3'"), [(None,)])
        self.assertEqual(self.rows("SELECT status FROM attempts"), [("rejected",)])
        self.assertNotIn("finish", [k for k, _ in model.history()])

    def test_crash_before_conflict_record_cannot_import_different_content(self):
        completed = subprocess.run(
            [sys.executable, "-B", __file__, "--worker", str(self.root), "after_conflict", ""],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 47, completed.stderr)
        model, tools = adapters(self.root)
        for _ in range(2):
            with self.assertRaises(ValueError):
                resume(self.db_path, model, tools)
        self.assertEqual(tools.history(), [("execute", "op-3"), ("lookup", "op-3")])
        self.assertEqual(self.rows("SELECT result_json FROM operations WHERE operation_key='op-3'"), [(None,)])
        self.assertEqual(self.rows("SELECT kind,status FROM attempts ORDER BY id"),
                         [("execute", "pending"), ("lookup", "rejected")])

    def test_confirmed_no_effect_retries_only_on_later_resume(self):
        class FailBeforeEffect(Tools):
            def execute(self, key, arguments):
                raise TimeoutError("Never sent")
        model, _ = adapters(self.root)
        tools = FailBeforeEffect(self.root / "tools.db")
        with self.assertRaises(ToolExecutionError):
            resume(self.db_path, model, tools)
        self.assertEqual(tools.effects(), {})
        self.assertEqual(self.rows("SELECT kind,status FROM attempts"),
                         [("execute", "unknown"), ("lookup", "not_executed")])
        tools = Tools(self.root / "tools.db")
        self.assertEqual(json.loads(resume(self.db_path, model, tools)), expected())
        self.assert_complete(model, tools)

    def test_result_commit_failure_is_recovered_by_lookup_without_resend(self):
        model, tools = adapters(self.root)

        def block_results(event, identity):
            if event == "decision_saved":
                with sqlite3.connect(self.db_path) as db:
                    db.execute("CREATE TRIGGER reject_result BEFORE UPDATE OF result_json ON operations "
                               "BEGIN SELECT RAISE(ABORT, 'injected result failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected result failure"):
            resume(self.db_path, model, tools, block_results)
        self.assertEqual(len(tools.effects()), 1)
        self.assertEqual(self.rows("SELECT status FROM attempts"), [("pending",)])
        with sqlite3.connect(self.db_path) as db:
            db.execute("DROP TRIGGER reject_result")
        self.assertEqual(json.loads(resume(self.db_path, model, tools)), expected())
        self.assertEqual(tools.history().count(("execute", "op-3")), 1)
        self.assertIn(("lookup", "op-3"), tools.history())

    def test_finish_response_gap_can_repeat_finish_but_never_tools(self):
        completed = subprocess.run(
            [sys.executable, "-B", __file__, "--worker", str(self.root), "after_finish", ""],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 47, completed.stderr)
        model, tools = adapters(self.root)
        self.assertEqual(self.rows("SELECT status FROM finish_attempts"), [("pending",)])
        self.assertEqual(json.loads(resume(self.db_path, model, tools)), expected())
        self.assertEqual([k for k, _ in model.history()], ["plan", "finish", "finish"])
        self.assertEqual(len(tools.history()), 3)
        self.assertEqual(self.rows("SELECT status FROM finish_attempts ORDER BY id"),
                         [("pending",), ("completed",)])

    def test_empty_decision_and_empty_final_are_stable(self):
        class EmptyFinal(Model):
            def finish(self, messages):
                self.assert_messages = messages
                return ""
        model = EmptyFinal(self.root / "model.db", [])
        tools = Tools(self.root / "tools.db")
        self.assertEqual(resume(self.db_path, model, tools), "")
        self.assertEqual(model.assert_messages, [])
        self.assertEqual(resume(self.db_path, NeverCalled(), NeverCalled()), "")

    def test_legacy_and_future_states_fail_without_reexecution(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE outputs(text TEXT)")
            db.execute("INSERT INTO outputs VALUES ('legacy final')")
        with self.assertRaisesRegex(RecoveryStateError, "Legacy"):
            resume(self.db_path, NeverCalled(), NeverCalled())
        self.assertEqual(self.rows("SELECT * FROM outputs"), [("legacy final",)])
        with sqlite3.connect(self.db_path) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(RecoveryStateError, "version 99"):
            resume(self.db_path, NeverCalled(), NeverCalled())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), sys.argv[3], sys.argv[4] or None)
    else:
        unittest.main()
