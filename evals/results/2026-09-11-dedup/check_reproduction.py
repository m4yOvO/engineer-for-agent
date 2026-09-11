"""Read-only service review using only the supplied in-memory contracts."""
from pathlib import Path
import json
import sys

BASE = Path(__file__).resolve().parent
PROJECT = BASE.parents[1] / "fixtures" / "item_adaptation" / "check"
sys.path.insert(0, str(PROJECT))
from app import PublicationService
from runtime_fixture import ContractRuntime, PublisherFake


class ObservedPublisher(PublisherFake):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def create(self, key, content):
        self.calls += 1
        return super().create(key, content)


def run_case(name, requests, lose_first_reply=False):
    runtime = ContractRuntime()
    publisher = ObservedPublisher()
    publisher.lose_reply = lose_first_reply
    service = PublicationService(runtime, publisher)
    steps = []
    for command, document, revision, body in requests:
        result = error = None
        try:
            result = service.submit(command, document, revision, body)
        except (TimeoutError, ValueError) as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        steps.append({
            "command_id": command, "document_id": document,
            "approved_revision": revision, "body": body,
            "result": result, "error": error,
            "effects": len(publisher.effects), "publisher_calls": publisher.calls,
            "completed_activities": len(runtime.results),
        })
    return {
        "id": name, "steps": steps,
        "effect_keys": [effect[0] for effect in publisher.effects],
        "workflow_ids": [entry[0] for entry in runtime.workflows.values()],
        "effect_count": len(publisher.effects),
        "publisher_calls": publisher.calls,
        "completed_activities": len(runtime.results),
    }


original = ("c1", "doc-1", "r1", "approved text")
cases = [
    run_case("T01_same_command_same_content", [original, original]),
    run_case("T02_new_command_same_approved_revision", [original, ("c2", *original[1:])]),
    run_case("T03_new_command_changed_body_same_revision", [original, ("c2", "doc-1", "r1", "changed text")]),
    run_case("T04_new_revision_same_body", [original, ("c2", "doc-1", "r2", "approved text")]),
    run_case("T05_same_command_changed_body", [original, ("c1", "doc-1", "r1", "changed text")]),
    run_case("T06_lost_reply_same_command", [original, original], lose_first_reply=True),
    run_case("T07_lost_reply_new_command", [original, ("c2", *original[1:])], lose_first_reply=True),
    run_case("T08_other_document_same_revision", [original, ("c2", "doc-2", "r1", "approved text")]),
]

assert [case["effect_count"] for case in cases] == [1, 2, 2, 2, 1, 1, 2, 2]
assert cases[0]["publisher_calls"] == 1
assert cases[1]["effect_keys"] == ["wf-c1:publish", "wf-c2:publish"]
assert cases[2]["steps"][1]["error"] is None
assert cases[4]["steps"][1]["error"]["type"] == "ValueError"
assert cases[5]["steps"][0]["error"]["type"] == "TimeoutError"
assert cases[5]["steps"][0]["effects"] == 1
assert cases[5]["steps"][0]["completed_activities"] == 0
assert cases[5]["steps"][1]["result"] == {"publication_id": "p-1"}
assert cases[5]["publisher_calls"] == 2
assert cases[6]["steps"][1]["result"] == {"publication_id": "p-2"}

direct = PublisherFake()
first = direct.create("business-key", {"body": "A"})
repeat = direct.create("business-key", {"body": "A"})
try:
    direct.create("business-key", {"body": "B"})
except ValueError as exc:
    conflict = str(exc)
else:
    raise AssertionError("PublisherFake must reject same-key content conflicts")
assert first == repeat and len(direct.effects) == 1

output = {
    "environment": {"python": sys.version.split()[0], "network_used": False,
                    "runtime": "ContractRuntime", "publisher": "PublisherFake subclass counting calls",
                    "entrypoint": "evals/fixtures/item_adaptation/check/app.py", "project_mutated": False},
    "cases": cases,
    "T09_direct_publisher_contract": {"first": first, "repeat": repeat,
                                      "conflict": conflict, "effect_count": len(direct.effects)},
    "observed_assertions_passed": True,
    "business_contract_failures": ["T02", "T03", "T07"],
    "limits": ["sequential in-memory checks", "no process restart proof", "no real service or production validation"],
}
path = BASE / "check-reproduction.json"
path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"output": str(path), "cases": 9, "observed_assertions_passed": True,
                  "business_contract_failures": output["business_contract_failures"]}, ensure_ascii=False))
