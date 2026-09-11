#!/usr/bin/env python3
"""Run behavioral assertions against a trusted, isolated build_wait copy."""
import concurrent.futures
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


if len(sys.argv) != 2:
    raise SystemExit("usage: assess_build.py /path/to/isolated/build_wait")
PROJECT = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("evaluated_service", PROJECT / "service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class WaitContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-wait-assert-")
        self.path = Path(self.temp.name) / "tasks.sqlite"
        self.db = service.open_db(str(self.path))
        service.create(self.db, "report-a")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def reopen(self):
        self.db.close()
        self.db = service.open_db(str(self.path))

    def task(self, task_id="report-a"):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row)

    def count(self, table):
        return self.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def waiting(self):
        service.pause(self.db, "report-a", "approval-v1", {"node": "publish", "revision": 1})

    def resume(self, **overrides):
        args = {
            "task_id": "report-a", "wait_id": "approval-v1",
            "value": {"approved": True, "revision": 1}, "message_id": "reply-a",
        }
        args.update(overrides)
        return service.resume(self.db, **args)

    def test_pause_failure_is_atomic_after_reopen(self):
        with self.assertRaises(RuntimeError):
            service.pause(self.db, "report-a", "approval-v1", {"node": "publish"}, True)
        self.reopen()
        self.assertEqual(self.task()["state"], "active")
        self.assertIsNone(self.task()["wait_id"])
        self.assertIsNone(self.task()["snapshot"])
        self.assertEqual(self.count("history"), 0)

    def test_process_exit_after_interrupted_pause_preserves_consistency(self):
        self.db.close()
        code = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('case', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
db = m.open_db(sys.argv[2])
try:
    m.pause(db, 'report-a', 'approval-v1', {'node': 'publish'}, inject_failure=True)
except RuntimeError:
    os._exit(77)
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(PROJECT / "service.py"), str(self.path)],
            capture_output=True, text=True, timeout=10,
        )
        self.db = service.open_db(str(self.path))
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertEqual(self.task()["state"], "active")
        self.assertIsNone(self.task()["wait_id"])
        self.assertIsNone(self.task()["snapshot"])
        self.assertEqual(self.count("history"), 0)

    def test_pause_roundtrip_and_invalid_transition(self):
        self.waiting()
        self.reopen()
        original = self.task()
        self.assertEqual(json.loads(original["snapshot"])["revision"], 1)
        with self.assertRaises(ValueError):
            service.pause(self.db, "report-a", "approval-v2", {"revision": 2})
        with self.assertRaises(ValueError):
            service.pause(self.db, "missing", "approval-v2", {})
        self.assertEqual(self.task(), original)
        self.assertEqual(self.count("history"), 1)

    def test_resume_replay_and_conflicting_content(self):
        self.waiting()
        first = self.resume()
        self.reopen()
        self.assertEqual(self.resume(value={"revision": 1, "approved": True}), first)
        with self.assertRaises(ValueError):
            self.resume(value={"approved": False, "revision": 1})
        self.assertEqual(self.task()["state"], "ready")
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("commands"), 1)
        self.assertEqual(self.count("history"), 2)

    def test_wait_and_task_identity_are_checked(self):
        self.waiting()
        original = self.task()
        with self.assertRaises(ValueError):
            self.resume(wait_id="stale-approval")
        with self.assertRaises(ValueError):
            self.resume(task_id="missing")
        self.assertEqual(self.task(), original)
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual(self.count("commands"), 0)

    def test_message_identity_is_bound_to_task(self):
        self.waiting()
        self.resume()
        service.create(self.db, "report-b")
        service.pause(self.db, "report-b", "approval-v1", {"revision": 1})
        with self.assertRaises(ValueError):
            self.resume(task_id="report-b")
        self.assertEqual(self.task("report-b")["state"], "waiting")
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("commands"), 1)

    def test_dispatch_failure_does_not_accept_resume(self):
        self.waiting()
        self.db.execute("""
            CREATE TRIGGER reject_job BEFORE INSERT ON jobs
            BEGIN SELECT RAISE(ABORT, 'simulated dispatch storage failure'); END;
        """)
        self.db.commit()
        with self.assertRaises(Exception):
            self.resume()
        self.reopen()
        self.assertEqual(self.task()["state"], "waiting")
        self.assertEqual(self.count("commands"), 0)
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual(self.count("history"), 1)

    def test_cancelled_wait_cannot_resume(self):
        self.waiting()
        service.cancel(self.db, "report-a")
        self.reopen()
        with self.assertRaises(ValueError):
            self.resume()
        self.assertEqual(self.task()["state"], "cancelled")
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual(self.count("history"), 2)

    def race(self, left, right):
        barrier = threading.Barrier(2)

        def worker(action):
            db = service.open_db(str(self.path))
            try:
                barrier.wait(timeout=5)
                try:
                    return ("ok", action(db))
                except ValueError:
                    return ("conflict", None)
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, action) for action in (left, right)]
            return [f.result(timeout=10) for f in futures]

    def test_concurrent_duplicate_resume_has_one_job(self):
        self.waiting()
        action = lambda db: service.resume(db, "report-a", "approval-v1", True, "reply-a")
        results = self.race(action, action)
        self.assertEqual([r[0] for r in results], ["ok", "ok"])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(self.count("jobs"), 1)
        self.assertEqual(self.count("commands"), 1)
        self.assertEqual(self.count("history"), 2)

    def test_cancel_resume_race_has_one_winner(self):
        for index in range(12):
            task_id = "race-" + str(index)
            service.create(self.db, task_id)
            service.pause(self.db, task_id, "approval", {})
            results = self.race(
                lambda db: service.resume(db, task_id, "approval", True, "reply-" + task_id),
                lambda db: service.cancel(db, task_id),
            )
            self.assertEqual(sorted(r[0] for r in results), ["conflict", "ok"])
            state = self.task(task_id)["state"]
            count = self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            self.assertEqual(count, 1 if state == "ready" else 0)
            self.assertIn(state, ("ready", "cancelled"))
            history = self.db.execute(
                "SELECT action FROM history WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
            self.assertEqual([r[0] for r in history], [
                "pause", "resume" if state == "ready" else "cancel",
            ])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
