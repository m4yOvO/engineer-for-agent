import json
import sqlite3


def open_db(path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, state TEXT NOT NULL,
            wait_id TEXT, snapshot TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, message_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commands(
            message_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, wait_id TEXT NOT NULL,
            input TEXT NOT NULL, result TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL
        );
    """)
    return db


def create(db, task_id):
    with db:
        db.execute("INSERT INTO tasks(id,state) VALUES (?, 'active')", (task_id,))


def pause(db, task_id, wait_id, snapshot, inject_failure=False):
    with db:
        db.execute("UPDATE tasks SET state='waiting', wait_id=? WHERE id=?", (wait_id, task_id))
    if inject_failure:
        raise RuntimeError("snapshot persistence interrupted")
    with db:
        db.execute("UPDATE tasks SET snapshot=? WHERE id=?", (json.dumps(snapshot), task_id))
        db.execute("INSERT INTO history(task_id,action) VALUES (?, 'pause')", (task_id,))


def resume(db, task_id, wait_id, value, message_id):
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if task is None or task["state"] != "waiting":
        raise ValueError("not waiting")
    result = {"task_id": task_id, "state": "ready"}
    with db:
        db.execute("UPDATE tasks SET state='ready' WHERE id=?", (task_id,))
        db.execute("INSERT INTO jobs(task_id,message_id) VALUES (?,?)", (task_id, message_id))
        db.execute("INSERT INTO history(task_id,action) VALUES (?, 'resume')", (task_id,))
    return result


def cancel(db, task_id):
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if task is None or task["state"] != "waiting":
        raise ValueError("not waiting")
    with db:
        db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (task_id,))
        db.execute("INSERT INTO history(task_id,action) VALUES (?, 'cancel')", (task_id,))
