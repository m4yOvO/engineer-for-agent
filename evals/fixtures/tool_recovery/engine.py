import json
import sqlite3


def resume(db_path, model, tools, fault=None):
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS outputs (text TEXT)")
    decision = model.plan()
    messages = []
    for call in decision["calls"]:
        result = tools.execute(call["operation_key"], call["arguments"])
        messages.append({"call_id": call["call_id"], "result": result})
    text = model.finish(messages)
    db.execute("INSERT INTO outputs VALUES (?)", (text,))
    db.commit()
    db.close()
    return text
