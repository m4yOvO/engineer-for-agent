def record_submission(records, operation_id, response):
    records[operation_id] = {
        "state": "succeeded" if response["status"] == "accepted" else response["status"],
        "version": response["version"], "history": [response.copy()],
    }


def reconcile(records, lookup):
    for operation_id, record in records.items():
        if record["state"] == "unknown":
            record["state"] = lookup(operation_id)["status"]


def apply_notification(records, operation_id, event):
    record = records[operation_id]
    record["state"] = event["status"]
    record["version"] = event["version"]
    record["history"].append(event.copy())


def subscribe(events, floor, after, principal, allowed):
    if principal not in allowed:
        raise PermissionError("access denied")

    def pending_events():
        for event in events:
            if event["sequence"] > after:
                yield event.copy()

    return pending_events()
