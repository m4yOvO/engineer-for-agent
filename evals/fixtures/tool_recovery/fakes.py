"""Deterministic local contracts; this is not a production provider."""
import json
import sqlite3


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Model:
    def __init__(self, path, calls):
        self.path = str(path)
        self.calls = calls
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT, payload TEXT)")

    def plan(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO calls VALUES ('plan', NULL)")
        return {"decision_id": "decision-a", "calls": self.calls}

    def finish(self, messages):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO calls VALUES ('finish', ?)", (encoded(messages),))
        return encoded(messages)

    def history(self):
        with sqlite3.connect(self.path) as db:
            return [(kind, json.loads(payload) if payload else None)
                    for kind, payload in db.execute("SELECT kind,payload FROM calls ORDER BY rowid")]


class Tools:
    def __init__(self, path, lose_once=None, lookup_unavailable=False):
        self.path = str(path)
        self.lose_once = lose_once
        self.lookup_unavailable = lookup_unavailable
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, args TEXT, result TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS requests (kind TEXT, key TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS lost (key TEXT PRIMARY KEY)")

    def execute(self, operation_key, arguments):
        value = encoded(arguments)
        lose = False
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO requests VALUES ('execute', ?)", (operation_key,))
            row = db.execute("SELECT args,result FROM effects WHERE key=?", (operation_key,)).fetchone()
            if row:
                if row[0] != value:
                    raise ValueError("same operation, different content")
                result = json.loads(row[1])
            else:
                result = {"operation_key": operation_key, "value": arguments}
                db.execute("INSERT INTO effects VALUES (?,?,?)", (operation_key, value, encoded(result)))
            if self.lose_once == operation_key:
                lose = db.execute("INSERT OR IGNORE INTO lost VALUES (?)", (operation_key,)).rowcount == 1
        if lose:
            raise TimeoutError("response lost after effect")
        return result

    def lookup(self, operation_key):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO requests VALUES ('lookup', ?)", (operation_key,))
            row = db.execute("SELECT result FROM effects WHERE key=?", (operation_key,)).fetchone()
        if self.lookup_unavailable:
            raise ConnectionError("query unavailable")
        return json.loads(row[0]) if row else None

    def history(self):
        with sqlite3.connect(self.path) as db:
            return list(db.execute("SELECT kind,key FROM requests ORDER BY rowid"))

    def effects(self):
        with sqlite3.connect(self.path) as db:
            return dict(db.execute("SELECT key,result FROM effects"))
