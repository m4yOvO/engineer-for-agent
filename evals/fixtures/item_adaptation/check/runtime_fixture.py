"""Local simulation of supplied platform and downstream contracts."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class ContractRuntime:
    def __init__(self):
        self.workflows = {}
        self.results = {}

    def accept(self, command_id, payload):
        signature = digest(payload)
        old = self.workflows.get(command_id)
        if old is not None:
            if old[1] != signature:
                raise ValueError("command content conflict")
            return old[0]
        workflow = "wf-" + command_id
        self.workflows[command_id] = (workflow, signature)
        return workflow

    def activity(self, workflow, name, execute):
        key = (workflow, name)
        if key not in self.results:
            self.results[key] = execute()
        return self.results[key]


class PublisherFake:
    def __init__(self):
        self.by_key = {}
        self.effects = []
        self.lose_reply = False

    def create(self, idempotency_key, content):
        signature = digest(content)
        if idempotency_key in self.by_key:
            old_signature, result = self.by_key[idempotency_key]
            if signature != old_signature:
                raise ValueError("publisher content conflict")
            return result
        result = {"publication_id": "p-" + str(len(self.effects) + 1)}
        self.by_key[idempotency_key] = (signature, result)
        self.effects.append((idempotency_key, content, result))
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError("response lost after creation")
        return result
