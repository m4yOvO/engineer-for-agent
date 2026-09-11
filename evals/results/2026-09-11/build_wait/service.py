import json
import sqlite3
from contextlib import contextmanager


def _identifier(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")


def _json(value):
    """Encode JSON values deterministically, preserving array order and types."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("expected a JSON value") from error
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ValueError("expected a JSON value")
    return encoded


@contextmanager
def _transaction(db):
    """Own one commit boundary; serialize decisions across SQLite connections."""
    if db.in_transaction:
        raise ValueError("operation requires a connection without a pending transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


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
    _identifier(task_id, "task_id")
    with _transaction(db):
        db.execute("INSERT INTO tasks(id,state) VALUES (?, 'active')", (task_id,))


def pause(db, task_id, wait_id, snapshot, inject_failure=False):
    _identifier(task_id, "task_id")
    _identifier(wait_id, "wait_id")
    saved_snapshot = _json(snapshot)
    with _transaction(db):
        changed = db.execute(
            "UPDATE tasks SET state='waiting', wait_id=? WHERE id=? AND state='active'",
            (wait_id, task_id),
        )
        if changed.rowcount != 1:
            raise ValueError("not active")
        if inject_failure:
            raise RuntimeError("snapshot persistence interrupted")
        db.execute("UPDATE tasks SET snapshot=? WHERE id=?", (saved_snapshot, task_id))
        db.execute("INSERT INTO history(task_id,action) VALUES (?, 'pause')", (task_id,))


def resume(db, task_id, wait_id, value, message_id):
    _identifier(task_id, "task_id")
    _identifier(wait_id, "wait_id")
    _identifier(message_id, "message_id")
    saved_input = _json(value)
    result = {"task_id": task_id, "state": "ready"}
    with _transaction(db):
        command = db.execute(
            "SELECT * FROM commands WHERE message_id=?", (message_id,)
        ).fetchone()
        if command is not None:
            if (command["task_id"] != task_id or command["wait_id"] != wait_id
                    or _json(json.loads(command["input"])) != saved_input):
                raise ValueError("message_id already used for a different command")
            return json.loads(command["result"])
        changed = db.execute(
            "UPDATE tasks SET state='ready' WHERE id=? AND state='waiting' AND wait_id=?",
            (task_id, wait_id),
        )
        if changed.rowcount != 1:
            raise ValueError("not waiting for this wait_id")
        db.execute(
            "INSERT INTO commands(message_id,task_id,wait_id,input,result) VALUES (?,?,?,?,?)",
            (message_id, task_id, wait_id, saved_input, _json(result)),
        )
        db.execute("INSERT INTO jobs(task_id,message_id) VALUES (?,?)", (task_id, message_id))
        db.execute("INSERT INTO history(task_id,action) VALUES (?, 'resume')", (task_id,))
    return result


def cancel(db, task_id):
    _identifier(task_id, "task_id")
    with _transaction(db):
        changed = db.execute(
            "UPDATE tasks SET state='cancelled' WHERE id=? AND state='waiting'", (task_id,)
        )
        if changed.rowcount != 1:
            raise ValueError("not waiting")
        db.execute("INSERT INTO history(task_id,action) VALUES (?, 'cancel')", (task_id,))
