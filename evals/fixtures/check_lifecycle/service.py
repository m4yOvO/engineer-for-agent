import json
import time
from pathlib import Path


class SqliteStore:
    def __init__(self, path):
        self.path = path


class TaskService:
    def __init__(self, store, max_duration):
        self.store = store
        self.max_duration = max_duration

    def create(self, task_id, payload):
        self.store[task_id] = {
            "state": "active", "payload": payload,
            "accepted_at": time.time(), "deadline": time.time() + self.max_duration,
        }

    def pause(self, task_id, snapshot_writer):
        task = self.store[task_id]
        task["state"] = "waiting"
        snapshot_writer(task)
        task["slot_released"] = True

    def resume(self, task_id, payload):
        task = self.store[task_id]
        task["input"] = payload
        task["state"] = "active"
        task["deadline"] = time.time() + self.max_duration

    def cancel(self, task_id):
        self.store[task_id]["state"] = "cancelled"


def start_project(config_path=None):
    config = json.loads(Path(config_path or Path(__file__).with_name("config.json")).read_text())
    configured_store = SqliteStore(config["database"])
    return TaskService({}, config["max_duration_seconds"])
