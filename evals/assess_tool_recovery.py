"""Run behavioral checks only against an inspected, trusted fixture implementation."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
TARGET = Path(sys.argv.pop(1)).resolve()
def load(name):
    spec = importlib.util.spec_from_file_location(name, TARGET / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

engine, fakes = load("engine"), load("fakes")
CALLS = [
    {"call_id": "first", "operation_key": "archive-a-v1", "arguments": {"document": "a", "revision": 1}},
    {"call_id": "second", "operation_key": "archive-b-v1", "arguments": {"document": "b", "revision": 1}},
]

class ToolContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.db = self.base / "engine.sqlite"
        self.model = fakes.Model(self.base / "model.sqlite", CALLS)
        self.tools = fakes.Tools(self.base / "provider.sqlite")

    def run_engine(self, fault=None, model=None, tools=None):
        return engine.resume(str(self.db), model or self.model, tools or self.tools, fault=fault)

    def result_contract(self, text, calls=CALLS):
        result = json.loads(text)
        self.assertEqual(result, [{"call_id": c["call_id"], "result": {
            "operation_key": c["operation_key"], "value": c["arguments"]}} for c in calls])
        self.assertEqual([x[0] for x in self.model.history()].count("plan"), 1)
        self.assertEqual([x[0] for x in self.model.history()].count("finish"), 1)
        self.assertEqual(self.model.history()[-1], ("finish", result))

    def execute_count(self, key):
        return self.tools.history().count(("execute", key))

    @staticmethod
    def fail_at(point, call_id=None):
        def fault(kind, identity):
            if kind == point and (call_id is None or identity == call_id):
                raise RuntimeError("injected exit boundary")
        return fault

    def test_final_replay_uses_saved_text(self):
        first = self.run_engine()
        self.result_contract(first)
        self.assertEqual(self.run_engine(), first)
        self.result_contract(first)
        self.assertEqual([self.execute_count(c["operation_key"]) for c in CALLS], [1, 1])

    def test_saved_decision_is_not_regenerated(self):
        with self.assertRaises(RuntimeError):
            self.run_engine(self.fail_at("decision_saved"))
        replacement = fakes.Model(self.base / "model.sqlite", [
            {"call_id": "different", "operation_key": "wrong", "arguments": {}}])
        self.result_contract(self.run_engine(model=replacement))
        self.assertNotIn("wrong", self.tools.effects())

    def test_partial_results_survive_real_process_exit(self):
        script = """
import json,os,sys
sys.dont_write_bytecode=True
from engine import resume
from fakes import Model,Tools
calls=json.loads(sys.argv[4])
def fault(point, call_id):
    if point=='result_saved' and call_id=='first':os._exit(79)
resume(sys.argv[1],Model(sys.argv[2],calls),Tools(sys.argv[3]),fault=fault)
"""
        process = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.db), str(self.base / "model.sqlite"),
             str(self.base / "provider.sqlite"), json.dumps(CALLS)],
            cwd=TARGET, capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 79, process.stderr)
        self.result_contract(self.run_engine())
        self.assertEqual(self.execute_count("archive-a-v1"), 1)
        self.assertEqual(self.execute_count("archive-b-v1"), 1)

    def test_saved_result_is_reused_before_projection(self):
        with self.assertRaises(RuntimeError):
            self.run_engine(self.fail_at("result_saved", "first"))
        self.result_contract(self.run_engine())
        self.assertEqual(self.execute_count("archive-a-v1"), 1)

    def test_saved_message_is_not_appended_twice(self):
        with self.assertRaises(RuntimeError):
            self.run_engine(self.fail_at("message_saved", "first"))
        self.result_contract(self.run_engine())
        self.assertEqual(self.execute_count("archive-a-v1"), 1)

    def test_response_lost_recovers_by_query(self):
        self.tools.lose_once = "archive-a-v1"
        try:
            result = self.run_engine()
        except (TimeoutError, ConnectionError, RuntimeError):
            result = self.run_engine()
        self.result_contract(result)
        self.assertEqual(self.execute_count("archive-a-v1"), 1)
        self.assertGreaterEqual(self.tools.history().count(("lookup", "archive-a-v1")), 1)

    def test_query_unavailable_does_not_resend_unknown_write(self):
        self.tools.lose_once = "archive-a-v1"
        execute = self.tools.execute
        def interrupted(key, args):
            try:
                return execute(key, args)
            except TimeoutError:
                self.tools.lookup_unavailable = True
                raise
        self.tools.execute = interrupted
        with self.assertRaises(Exception):
            self.run_engine()
        self.assertEqual(self.execute_count("archive-a-v1"), 1)
        with self.assertRaises(Exception):
            self.run_engine()
        self.assertEqual(self.execute_count("archive-a-v1"), 1)
        self.assertEqual([x[0] for x in self.model.history()].count("finish"), 0)
        self.tools.lookup_unavailable = False
        self.result_contract(self.run_engine())
        self.assertEqual(self.execute_count("archive-a-v1"), 1)

    def test_new_call_id_same_operation_reuses_result(self):
        calls = [
            {"call_id": "alias-1", "operation_key": "shared", "arguments": {"a": 1, "b": 2}},
            {"call_id": "alias-2", "operation_key": "shared", "arguments": {"b": 2, "a": 1}},
            {"call_id": "new-version", "operation_key": "shared-v2", "arguments": {"a": 1, "b": 2}},
        ]
        self.model.calls = calls
        self.result_contract(self.run_engine(), calls=calls)
        self.assertEqual(self.execute_count("shared"), 1)
        self.assertEqual(self.execute_count("shared-v2"), 1)
        self.assertEqual(len(self.tools.effects()), 2)

    def test_changed_content_under_same_operation_is_rejected(self):
        self.model.calls = [
            {"call_id": "alias-1", "operation_key": "shared", "arguments": {"v": 1}},
            {"call_id": "alias-2", "operation_key": "shared", "arguments": {"v": 2}},
        ]
        with self.assertRaises(Exception):
            self.run_engine()
        self.assertEqual([x[0] for x in self.model.history()].count("finish"), 0)
        self.assertLessEqual(len(self.tools.effects()), 1)

    def test_no_database_write_transaction_spans_external_call(self):
        execute = self.tools.execute
        def observed(key, args):
            with sqlite3.connect(self.db, timeout=0.1) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
            return execute(key, args)
        self.tools.execute = observed
        self.result_contract(self.run_engine())

if __name__ == "__main__":
    unittest.main(verbosity=2)
