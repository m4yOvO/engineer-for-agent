"""Recover one accepted decision per database; the caller owns single execution."""

import json
import sqlite3


class RecoveryUnavailableError(RuntimeError):
    """An uncertain operation could not be checked; resume with lookup available."""


class ToolExecutionError(RuntimeError):
    """Execution failed and lookup confirmed no effect; a later resume may retry."""


class RecoveryStateError(RuntimeError):
    """Stored state cannot safely be resumed by this version."""


SCHEMA = """
BEGIN;
CREATE TABLE run (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    decision_id TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    final_text TEXT
);
CREATE TABLE operations (
    operation_key TEXT PRIMARY KEY,
    arguments_json TEXT NOT NULL,
    result_json TEXT,
    result_attempt_id INTEGER REFERENCES attempts(id)
);
CREATE TABLE calls (
    call_id TEXT PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES run(id),
    position INTEGER NOT NULL UNIQUE,
    operation_key TEXT NOT NULL REFERENCES operations(operation_key),
    result_ready INTEGER NOT NULL DEFAULT 0 CHECK (result_ready IN (0, 1))
);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY,
    call_id TEXT NOT NULL REFERENCES calls(call_id),
    operation_key TEXT NOT NULL REFERENCES operations(operation_key),
    kind TEXT NOT NULL CHECK (kind IN ('execute', 'lookup')),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    error TEXT
);
CREATE INDEX attempts_by_operation ON attempts(operation_key, kind);
CREATE TABLE messages (
    call_id TEXT PRIMARY KEY REFERENCES calls(call_id),
    result_json TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0, 1))
);
CREATE TABLE finish_attempts (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES run(id),
    messages_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at TEXT,
    error TEXT
);
PRAGMA user_version = 1;
COMMIT;
"""


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _open(db_path):
    db = sqlite3.connect(db_path)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA synchronous = FULL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if tables - {"outputs", "sqlite_sequence"}:
                raise RecoveryStateError("Unversioned recovery data; preserve it for inspection")
            if "outputs" in tables and db.execute("SELECT 1 FROM outputs LIMIT 1").fetchone():
                raise RecoveryStateError(
                    "Legacy outputs lack decision/call evidence; automatic recovery is unsafe"
                )
            db.executescript(SCHEMA)
        elif version != 1:
            raise RecoveryStateError(f"Unsupported recovery schema version {version}")
        return db
    except BaseException:
        db.close()
        raise


def _validated(decision):
    if not isinstance(decision, dict):
        raise ValueError("A decision must be an object")
    if not isinstance(decision.get("decision_id"), str) or not decision["decision_id"]:
        raise ValueError("decision_id must be a nonempty string")
    if not isinstance(decision.get("calls"), list):
        raise ValueError("calls must be a complete list")
    call_ids, operations = set(), {}
    for call in decision["calls"]:
        if not isinstance(call, dict) or "arguments" not in call:
            raise ValueError("Each call needs arguments")
        for key in ("call_id", "operation_key"):
            if not isinstance(call.get(key), str) or not call[key]:
                raise ValueError(f"{key} must be a nonempty string")
        if call["call_id"] in call_ids:
            raise ValueError(f"Duplicate call_id: {call['call_id']}")
        call_ids.add(call["call_id"])
        key, arguments = call["operation_key"], _encoded(call["arguments"])
        if key in operations and operations[key] != arguments:
            raise ValueError(f"Same operation_key, different arguments: {key}")
        operations[key] = arguments
    return _encoded(decision), operations


def _accept_decision(db, model, fault):
    row = db.execute("SELECT * FROM run WHERE id=1").fetchone()
    if row is not None:
        return row
    decision_json, operations = _validated(model.plan())
    decision = json.loads(decision_json)
    with db:
        db.execute("INSERT INTO run(id, decision_id, decision_json) VALUES (1,?,?)",
                   (decision["decision_id"], decision_json))
        for key, arguments in operations.items():
            db.execute("INSERT INTO operations(operation_key, arguments_json) VALUES (?,?)",
                       (key, arguments))
        for position, call in enumerate(decision["calls"]):
            db.execute("INSERT INTO calls(call_id, run_id, position, operation_key) VALUES (?,1,?,?)",
                       (call["call_id"], position, call["operation_key"]))
    if fault is not None:
        fault("decision_saved", None)
    return db.execute("SELECT * FROM run WHERE id=1").fetchone()


def _start_attempt(db, call, kind):
    with db:
        return db.execute(
            "INSERT INTO attempts(call_id, operation_key, kind, status) VALUES (?,?,?,'pending')",
            (call["call_id"], call["operation_key"], kind),
        ).lastrowid


def _end_attempt(db, attempt_id, status, error=None):
    db.execute(
        "UPDATE attempts SET status=?, error=?, "
        "ended_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?",
        (status, None if error is None else f"{type(error).__name__}: {error}", attempt_id),
    )


def _save_result(db, key, attempt_id, result):
    # The supplied adapter echoes the operation and arguments in its result.
    # This also catches a crash before a content rejection was stored locally.
    if isinstance(result, dict) and {"operation_key", "value"} <= result.keys():
        arguments = db.execute("SELECT arguments_json FROM operations WHERE operation_key=?",
                               (key,)).fetchone()[0]
        if result["operation_key"] != key or _encoded(result["value"]) != arguments:
            error = ValueError(f"Result conflicts with accepted operation content: {key}")
            with db:
                _end_attempt(db, attempt_id, "rejected", error)
            raise error
    value = _encoded(result)
    with db:
        db.execute("UPDATE operations SET result_json=?, result_attempt_id=? WHERE operation_key=?",
                   (value, attempt_id, key))
        _end_attempt(db, attempt_id, "completed")
    return value


def _lookup(db, tools, call):
    attempt_id = _start_attempt(db, call, "lookup")
    try:
        result = tools.lookup(call["operation_key"])
    except Exception as error:
        with db:
            _end_attempt(db, attempt_id, "unavailable", error)
        raise RecoveryUnavailableError(
            f"Cannot verify operation {call['operation_key']!r}; state retained, no tool resend"
        ) from error
    if result is None:
        with db:
            _end_attempt(db, attempt_id, "not_executed")
        return None
    return _save_result(db, call["operation_key"], attempt_id, result)


def _operation_result(db, tools, call):
    operation = db.execute("SELECT * FROM operations WHERE operation_key=?",
                           (call["operation_key"],)).fetchone()
    if operation["result_json"] is not None:
        return operation["result_json"]
    rejection = db.execute(
        "SELECT error FROM attempts WHERE operation_key=? AND status='rejected' LIMIT 1",
        (call["operation_key"],),
    ).fetchone()
    if rejection is not None:
        raise ValueError(rejection["error"])
    prior_execute = db.execute(
        "SELECT 1 FROM attempts WHERE operation_key=? AND kind='execute' LIMIT 1",
        (call["operation_key"],),
    ).fetchone()
    if prior_execute is not None:
        result = _lookup(db, tools, call)
        if result is not None:
            return result
    attempt_id = _start_attempt(db, call, "execute")
    try:
        result = tools.execute(call["operation_key"], json.loads(operation["arguments_json"]))
    except ValueError as error:
        # The supplied adapter rejects conflicting content with ValueError.
        # Its existing result belongs to different arguments and cannot be reused.
        with db:
            _end_attempt(db, attempt_id, "rejected", error)
        raise
    except Exception as error:
        with db:
            _end_attempt(db, attempt_id, "unknown", error)
        recovered = _lookup(db, tools, call)
        if recovered is not None:
            return recovered
        raise ToolExecutionError(
            f"Operation {call['operation_key']!r} did not execute; a later resume may retry"
        ) from error
    return _save_result(db, call["operation_key"], attempt_id, result)


def resume(db_path, model, tools, fault=None):
    """Finish/resume a local run, preserving unknown effects for authoritative lookup.

    Each db_path identifies one run. Calls are independent, executed in decision
    order, and paired by call_id. Only the caller may provide single-writer access.
    Hook exceptions propagate after their named facts have been committed.
    """
    db = _open(db_path)
    try:
        run = _accept_decision(db, model, fault)
        if run["final_text"] is not None:
            return run["final_text"]
        calls = db.execute("SELECT * FROM calls ORDER BY position").fetchall()
        for call in calls:
            result_json = _operation_result(db, tools, call)
            if not call["result_ready"]:
                with db:
                    db.execute("UPDATE calls SET result_ready=1 WHERE call_id=?", (call["call_id"],))
                if fault is not None:
                    fault("result_saved", call["call_id"])
            if db.execute("SELECT 1 FROM messages WHERE call_id=?", (call["call_id"],)).fetchone() is None:
                with db:
                    db.execute("INSERT INTO messages(call_id, result_json) VALUES (?,?)",
                               (call["call_id"], result_json))
                if fault is not None:
                    fault("message_saved", call["call_id"])
        messages = [
            {"call_id": row["call_id"], "result": json.loads(row["result_json"])}
            for row in db.execute(
                "SELECT messages.call_id, messages.result_json FROM messages "
                "JOIN calls USING(call_id) ORDER BY calls.position"
            )
        ]
        if len(messages) != len(calls):
            raise RecoveryStateError("Incomplete message projection")
        with db:
            finish_id = db.execute(
                "INSERT INTO finish_attempts(run_id, messages_json, status) VALUES (1,?,'pending')",
                (_encoded(messages),),
            ).lastrowid
        try:
            text = model.finish(messages)
            if not isinstance(text, str):
                raise TypeError("model.finish must return final text")
        except Exception as error:
            with db:
                db.execute("UPDATE finish_attempts SET status='unknown', error=?, "
                           "ended_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?",
                           (f"{type(error).__name__}: {error}", finish_id))
            raise
        with db:
            db.execute("UPDATE run SET final_text=? WHERE id=1", (text,))
            db.execute("UPDATE messages SET consumed=1")
            db.execute("UPDATE finish_attempts SET status='completed', "
                       "ended_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?", (finish_id,))
        return text
    finally:
        db.close()
