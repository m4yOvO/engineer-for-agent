"""Isolated, read-only probes for the two named review targets."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def load(name, folder):
    spec = importlib.util.spec_from_file_location(name, ROOT / folder / "service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lc = load("lifecycle_review", "check_lifecycle")
ob = load("observers_review", "check_observers")
evidence = {}

# Separate interpreters prove that the actual startup path does not recover
# a task previously accepted through that same path.
bootstrap = (
    "import importlib.util,json; "
    f"s=importlib.util.spec_from_file_location('project',{str(ROOT / 'check_lifecycle' / 'service.py')!r}); "
    "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
    "service=m.start_project(); "
)
first = subprocess.run(
    [sys.executable, "-B", "-c", bootstrap + "service.create('task-a',{}); print(json.dumps(list(service.store)))"],
    check=True, capture_output=True, text=True,
)
second = subprocess.run(
    [sys.executable, "-B", "-c", bootstrap + "print(json.dumps(list(service.store)))"],
    check=True, capture_output=True, text=True,
)
evidence["L1_restart"] = {"before_exit": json.loads(first.stdout), "new_process": json.loads(second.stdout)}
assert evidence["L1_restart"] == {"before_exit": ["task-a"], "new_process": []}

with patch.object(lc.time, "time", return_value=1000):
    service = lc.start_project()
    service.create("task-a", {})
def failed_snapshot(task):
    raise RuntimeError("injected snapshot failure")
try:
    service.pause("task-a", failed_snapshot)
except RuntimeError as exc:
    evidence["L2_snapshot_failure"] = {"exception": str(exc), "task": copy.deepcopy(service.store["task-a"])}
assert evidence["L2_snapshot_failure"]["task"]["state"] == "waiting"
assert "slot_released" not in evidence["L2_snapshot_failure"]["task"]

with patch.object(lc.time, "time", return_value=1010):
    service = lc.start_project()
    service.create("task-a", {})
    saved = []
    def resume_during_pause(task):
        saved.append(copy.deepcopy(task))
        service.resume("task-a", {"reply": "during-save"})
    service.pause("task-a", resume_during_pause)
evidence["L2_late_release"] = {"saved": saved, "current": copy.deepcopy(service.store["task-a"])}
assert evidence["L2_late_release"]["current"]["state"] == "active"
assert evidence["L2_late_release"]["current"]["slot_released"] is True

with patch.object(lc.time, "time", return_value=1000):
    service = lc.start_project()
    service.create("task-a", {})
    service.pause("task-a", lambda task: None)
    service.cancel("task-a")
    before = copy.deepcopy(service.store["task-a"])
    service.resume("task-a", {"reply": "first"})
    once = copy.deepcopy(service.store["task-a"])
    service.resume("task-a", {"reply": "second"})
    evidence["L3_cancel_and_duplicate_resume"] = {"cancelled": before, "once": once, "twice": copy.deepcopy(service.store["task-a"])}
assert once["state"] == "active"
assert evidence["L3_cancel_and_duplicate_resume"]["twice"]["input"]["reply"] == "second"

with patch.object(lc.time, "time", return_value=1000):
    service = lc.start_project()
    service.create("task-a", {})
    initial = copy.deepcopy(service.store["task-a"])
with patch.object(lc.time, "time", return_value=1110):
    service.pause("task-a", lambda task: None)
    service.resume("task-a", {})
    extended = copy.deepcopy(service.store["task-a"])
with patch.object(lc.time, "time", return_value=1300):
    service.resume("task-a", {})
    expired_resume = copy.deepcopy(service.store["task-a"])
evidence["L4_deadline"] = {"initial": initial, "at_1110": extended, "at_1300": expired_resume}
assert initial["deadline"] == 1120
assert extended["deadline"] == 1230
assert expired_resume["deadline"] == 1420 and expired_resume["state"] == "active"

records = {}
ob.record_submission(records, "op-a", {"status": "accepted", "version": 1})
evidence["O1_accepted"] = copy.deepcopy(records)
assert records["op-a"]["state"] == "succeeded"

calls = []
def withdrawn_lookup(operation_id):
    calls.append(operation_id)
    return {"status": "withdrawn", "version": 3}
ob.reconcile(records, withdrawn_lookup)
evidence["O2_reconcile_success"] = {"lookup_calls": calls.copy(), "records": copy.deepcopy(records)}
assert not calls and records["op-a"]["state"] == "succeeded"

records = {}
ob.record_submission(records, "op-a", {"status": "unknown", "version": 1})
ob.reconcile(records, withdrawn_lookup)
evidence["O3_reconcile_history"] = copy.deepcopy(records)
assert records["op-a"] == {"state": "withdrawn", "version": 1, "history": [{"status": "unknown", "version": 1}]}
ob.apply_notification(records, "op-a", {"status": "withdrawn", "version": 4})
before = copy.deepcopy(records)
ob.record_submission(records, "op-a", {"status": "accepted", "version": 5})
evidence["O3_resubmission_history"] = {"before": before, "after": copy.deepcopy(records)}
assert len(records["op-a"]["history"]) == 1

records = {}
ob.record_submission(records, "op-a", {"status": "succeeded", "version": 2})
ob.apply_notification(records, "op-a", {"status": "withdrawn", "version": 3})
newest = copy.deepcopy(records)
ob.apply_notification(records, "op-a", {"status": "succeeded", "version": 2})
stale = copy.deepcopy(records)
ob.apply_notification(records, "op-a", {"status": "succeeded", "version": 2})
evidence["O4_notification_order"] = {"newest": newest, "after_stale": stale, "after_duplicate": copy.deepcopy(records)}
assert stale["op-a"]["state"] == "succeeded" and stale["op-a"]["version"] == 2
assert len(records["op-a"]["history"]) == 4

events = [{"sequence": 10, "value": "ten"}, {"sequence": 11, "value": "eleven"}]
allowed = {"alice"}
expired = list(ob.subscribe(events, floor=10, after=5, principal="alice", allowed=allowed))
boundary = list(ob.subscribe(events, floor=10, after=9, principal="alice", allowed=allowed))
evidence["O5_floor"] = {"expired_after_5": expired, "valid_after_9": boundary}
assert expired == boundary == events

stream = ob.subscribe(events, floor=10, after=9, principal="alice", allowed=allowed)
first = next(stream)
allowed.remove("alice")
after_revocation = next(stream)
try:
    ob.subscribe(events, floor=10, after=9, principal="alice", allowed=allowed)
except PermissionError as exc:
    denied = str(exc)
else:
    raise AssertionError("new unauthorized subscription was allowed")
evidence["O6_revocation"] = {"before": first, "after": after_revocation, "new_subscription": denied}
assert after_revocation["sequence"] == 11

# Positive evidence remains bounded to the in-memory code path.
allowed.add("alice")
output = list(ob.subscribe(events, floor=10, after=10, principal="alice", allowed=allowed))
output[0]["value"] = "consumer edit"
assert events[1]["value"] == "eleven"
evidence["positive_cursor_and_shallow_copy"] = {"output_sequences": [x["sequence"] for x in output], "source_unchanged_for_scalar_edit": True}

print(json.dumps(evidence, ensure_ascii=False, indent=2))
