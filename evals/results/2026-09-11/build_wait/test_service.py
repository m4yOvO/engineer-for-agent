import concurrent.futures
import inspect
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

import service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.sqlite"
        self.db = service.open_db(self.path)
        self.addCleanup(lambda: self.db.close())

    def reopen(self):
        self.db.close()
        self.db = service.open_db(self.path)

    def waiting(self, task_id="task", wait_id="wait", snapshot=None):
        service.create(self.db, task_id)
        service.pause(self.db, task_id, wait_id, snapshot)

    def facts(self):
        return {
            table: [tuple(row) for row in self.db.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("tasks", "commands", "jobs", "history")
        }

    def task(self, task_id="task"):
        return dict(self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def count(self, table):
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def race(self, operations):
        barrier = threading.Barrier(len(operations))

        def run(operation):
            db = service.open_db(self.path)
            try:
                barrier.wait(timeout=10)
                try:
                    return ("ok", operation(db))
                except ValueError as error:
                    return ("rejected", str(error))
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_public_entry_and_signatures(self):
        self.assertEqual(Path(service.__file__).resolve(), Path(__file__).with_name("service.py").resolve())
        expected = {
            "open_db": "(path)", "create": "(db, task_id)",
            "pause": "(db, task_id, wait_id, snapshot, inject_failure=False)",
            "resume": "(db, task_id, wait_id, value, message_id)",
            "cancel": "(db, task_id)",
        }
        for name, signature in expected.items():
            self.assertEqual(str(inspect.signature(getattr(service, name))), signature)

    def test_reopen_retains_snapshot_result_and_dispatch_input(self):
        snapshot = {"position": 4, "messages": ["你好", None]}
        value = {"answer": [False, 0, "", None], "accepted": True}
        self.waiting(snapshot=snapshot)
        self.reopen()
        self.assertEqual(self.task()["state"], "waiting")
        self.assertEqual(json.loads(self.task()["snapshot"]), snapshot)
        result = service.resume(self.db, "task", "wait", value, "message")
        self.reopen()
        self.assertEqual(result, {"task_id": "task", "state": "ready"})
        job = self.db.execute("""
            SELECT jobs.id, tasks.snapshot, commands.input, commands.result
            FROM jobs JOIN tasks ON tasks.id=jobs.task_id
            JOIN commands ON commands.message_id=jobs.message_id
            WHERE tasks.state='ready'
        """).fetchone()
        self.assertIsNotNone(job)
        self.assertEqual(json.loads(job["snapshot"]), snapshot)
        self.assertEqual(json.loads(job["input"]), value)
        self.assertEqual(json.loads(job["result"]), result)
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual([row[0] for row in self.db.execute("SELECT action FROM history ORDER BY id")],
                         ["pause", "resume"])

    def test_pause_injected_failure_rolls_back_and_can_retry(self):
        service.create(self.db, "task")
        before = self.facts()
        with self.assertRaisesRegex(RuntimeError, "snapshot persistence interrupted"):
            service.pause(self.db, "task", "wait", {"step": 2}, inject_failure=True)
        self.assertFalse(self.db.in_transaction)
        self.reopen()
        self.assertEqual(self.facts(), before)
        service.pause(self.db, "task", "wait", {"step": 2})
        self.assertEqual(self.task()["state"], "waiting")
        self.assertEqual(self.count("history"), 1)

    def test_abrupt_process_exit_during_pause_is_rolled_back(self):
        service.create(self.db, "task")
        before = self.facts()
        program = """
import os, sys
import service
db = service.open_db(sys.argv[1])
db.create_function('interrupt_process', 0, lambda: os._exit(23))
db.execute('''CREATE TEMP TRIGGER interrupt_pause AFTER UPDATE OF state ON tasks
    WHEN NEW.state='waiting' BEGIN SELECT interrupt_process(); END''')
service.pause(db, 'task', 'wait', {'step': 3})
"""
        completed = subprocess.run([sys.executable, "-c", program, str(self.path)],
                                   cwd=Path(service.__file__).parent, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 23, completed.stderr.decode())
        self.reopen()
        self.assertEqual(self.facts(), before)
        service.pause(self.db, "task", "wait", {"step": 3})
        self.assertEqual(self.task()["state"], "waiting")

    def test_pause_only_accepts_active(self):
        self.waiting()
        before = self.facts()
        for task_id in ("task", "missing"):
            with self.assertRaises(ValueError):
                service.pause(self.db, task_id, "other", {"changed": True})
            self.assertEqual(self.facts(), before)

    def test_duplicate_resume_replays_persisted_result(self):
        self.waiting()
        result = service.resume(self.db, "task", "wait", {"a": 1, "b": [2, 3]}, "message")
        before = self.facts()
        result["state"] = "caller-mutated"
        self.reopen()
        duplicate = service.resume(self.db, "task", "wait", {"b": [2, 3], "a": 1}, "message")
        self.assertEqual(duplicate, {"task_id": "task", "state": "ready"})
        self.assertEqual(self.facts(), before)

    def test_message_id_conflicts_reject_all_content_changes(self):
        self.waiting()
        self.waiting("other", "other-wait")
        service.resume(self.db, "task", "wait", {"answer": 1}, "message")
        before = self.facts()
        for task_id, wait_id, value in (
            ("task", "wait", {"answer": 2}),
            ("task", "wait", {"answer": True}),
            ("task", "old-wait", {"answer": 1}),
            ("other", "other-wait", {"answer": 1}),
            ("missing", "wait", {"answer": 1}),
        ):
            with self.assertRaises(ValueError):
                service.resume(self.db, task_id, wait_id, value, "message")
            self.assertEqual(self.facts(), before)

    def test_wrong_wait_or_task_does_not_consume_command_id(self):
        self.waiting()
        self.waiting("other", "other-wait")
        before = self.facts()
        for task_id, wait_id in (("missing", "wait"), ("task", "wrong"), ("other", "wait")):
            with self.assertRaises(ValueError):
                service.resume(self.db, task_id, wait_id, None, "message")
            self.assertEqual(self.facts(), before)
        service.resume(self.db, "task", "wait", None, "message")
        self.assertEqual(self.count("jobs"), 1)

    def test_json_scalar_values_round_trip(self):
        for index, value in enumerate((None, False, True, 0, 1, 1.5, "", "你好", [])):
            with self.subTest(value=value):
                task_id = str(index)
                self.waiting(task_id, "wait")
                first = service.resume(self.db, task_id, "wait", value, task_id)
                self.assertEqual(service.resume(self.db, task_id, "wait", value, task_id), first)
                stored = json.loads(self.db.execute(
                    "SELECT input FROM commands WHERE message_id=?", (task_id,)).fetchone()[0])
                self.assertEqual(stored, value)
                self.assertIs(type(stored), type(value))

    def test_invalid_json_or_command_id_does_not_mutate(self):
        self.waiting()
        before = self.facts()
        for value in (float("nan"), float("inf"), {"nested": (1, 2)}, {1: "not a JSON key"}, object()):
            with self.assertRaises(ValueError):
                service.resume(self.db, "task", "wait", value, "message")
            self.assertEqual(self.facts(), before)
        for message_id in (None, "", 42):
            with self.assertRaises(ValueError):
                service.resume(self.db, "task", "wait", None, message_id)
            self.assertEqual(self.facts(), before)

    def test_cancel_preserves_wait_and_history_and_blocks_resume(self):
        self.waiting(snapshot={"step": 9})
        waiting = self.task()
        self.assertIsNone(service.cancel(self.db, "task"))
        self.reopen()
        self.assertEqual(self.task(), dict(waiting, state="cancelled"))
        before = self.facts()
        for operation in (
            lambda: service.resume(self.db, "task", "wait", None, "message"),
            lambda: service.cancel(self.db, "task"),
            lambda: service.cancel(self.db, "missing"),
            lambda: service.pause(self.db, "task", "again", None),
        ):
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.facts(), before)
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual([row[0] for row in self.db.execute("SELECT action FROM history ORDER BY id")],
                         ["pause", "cancel"])

    def test_ready_task_rejects_cancel_pause_and_new_resume(self):
        self.waiting()
        service.resume(self.db, "task", "wait", None, "message")
        before = self.facts()
        for operation in (
            lambda: service.cancel(self.db, "task"),
            lambda: service.pause(self.db, "task", "again", None),
            lambda: service.resume(self.db, "task", "wait", None, "new-message"),
        ):
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.facts(), before)

    def test_history_write_failure_rolls_back_each_operation(self):
        for action in ("pause", "resume", "cancel"):
            with self.subTest(action=action):
                task_id = action
                service.create(self.db, task_id)
                if action != "pause":
                    service.pause(self.db, task_id, "wait", None)
                before = self.facts()
                self.db.execute(f"""CREATE TEMP TRIGGER fail_history BEFORE INSERT ON history
                    WHEN NEW.action='{action}' BEGIN SELECT RAISE(ABORT, 'history failed'); END""")
                operations = {
                    "pause": lambda: service.pause(self.db, task_id, "wait", None),
                    "resume": lambda: service.resume(self.db, task_id, "wait", None, "message"),
                    "cancel": lambda: service.cancel(self.db, task_id),
                }
                with self.assertRaisesRegex(sqlite3.IntegrityError, "history failed"):
                    operations[action]()
                self.reopen()
                self.assertEqual(self.facts(), before)
                operations[action]()

    def test_job_write_failure_rolls_back_resume_and_allows_retry(self):
        self.waiting()
        before = self.facts()
        self.db.execute("""CREATE TEMP TRIGGER fail_job BEFORE INSERT ON jobs
            BEGIN SELECT RAISE(ABORT, 'dispatch failed'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "dispatch failed"):
            service.resume(self.db, "task", "wait", None, "message")
        self.reopen()
        self.assertEqual(self.facts(), before)
        service.resume(self.db, "task", "wait", None, "message")
        self.assertEqual(self.count("jobs"), 1)

    def test_concurrent_duplicate_resume_returns_one_result_and_job(self):
        self.waiting()
        results = self.race([
            lambda db: service.resume(db, "task", "wait", {"answer": "yes"}, "message")
            for _ in range(8)
        ])
        self.assertEqual(results, [("ok", {"task_id": "task", "state": "ready"})] * 8)
        self.reopen()
        self.assertEqual(self.count("commands"), 1)
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("history"), 2)

    def test_concurrent_distinct_resume_accepts_only_one(self):
        self.waiting()
        results = self.race([
            lambda db: service.resume(db, "task", "wait", "one", "one"),
            lambda db: service.resume(db, "task", "wait", "two", "two"),
        ])
        self.assertEqual(sorted(status for status, _ in results), ["ok", "rejected"])
        self.reopen()
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("commands"), 1)
        self.assertEqual(self.count("history"), 2)

    def test_same_message_race_across_tasks_preserves_loser(self):
        self.waiting("one", "wait")
        self.waiting("two", "wait")
        results = self.race([
            lambda db: service.resume(db, "one", "wait", None, "message"),
            lambda db: service.resume(db, "two", "wait", None, "message"),
        ])
        self.assertEqual(sorted(status for status, _ in results), ["ok", "rejected"])
        self.reopen()
        self.assertEqual(sorted(self.task(task)["state"] for task in ("one", "two")), ["ready", "waiting"])
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("commands"), 1)
        self.assertEqual(self.count("history"), 3)

    def test_cancel_resume_race_has_one_persistent_winner(self):
        for index in range(30):
            with self.subTest(race=index):
                task_id = str(index)
                self.waiting(task_id, "wait", {"round": index})
                results = self.race([
                    lambda db: service.resume(db, task_id, "wait", None, task_id),
                    lambda db: service.cancel(db, task_id),
                ])
                self.assertEqual(sorted(status for status, _ in results), ["ok", "rejected"])
                self.reopen()
                state = self.task(task_id)["state"]
                self.assertIn(state, ("ready", "cancelled"))
                winner = "resume" if state == "ready" else "cancel"
                history = [row[0] for row in self.db.execute(
                    "SELECT action FROM history WHERE task_id=? ORDER BY id", (task_id,))]
                self.assertEqual(history, ["pause", winner])
                for table in ("commands", "jobs"):
                    self.assertEqual(self.db.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE task_id=?", (task_id,)).fetchone()[0],
                        int(state == "ready"))

    def test_legacy_schema_and_history_are_preserved(self):
        self.db.close()
        legacy = sqlite3.connect(self.path)
        legacy.execute("INSERT INTO tasks VALUES ('old', 'waiting', 'old-wait', ?)",
                       (json.dumps({"legacy": True}),))
        legacy.execute("INSERT INTO history(task_id, action) VALUES ('old', 'pause')")
        legacy.commit()
        legacy.close()
        self.db = service.open_db(self.path)
        result = service.resume(self.db, "old", "old-wait", None, "message")
        self.assertEqual(result, {"task_id": "old", "state": "ready"})
        self.assertEqual(self.count("history"), 2)

    def test_pending_caller_transaction_is_not_committed_or_rolled_back(self):
        self.db.execute("INSERT INTO tasks(id, state) VALUES ('pending', 'active')")
        with self.assertRaisesRegex(ValueError, "pending transaction"):
            service.pause(self.db, "pending", "wait", None)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.task("pending")["state"], "active")
        self.db.rollback()
        self.assertEqual(self.count("tasks"), 0)


if __name__ == "__main__":
    unittest.main()
