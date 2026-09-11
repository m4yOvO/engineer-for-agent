"""Publication entrypoint; upstream has authenticated the approved payload."""
from runtime_fixture import ContractRuntime, PublisherFake


class PublicationService:
    def __init__(self, runtime, publisher):
        self.runtime = runtime
        self.publisher = publisher

    def submit(self, command_id, document_id, approved_revision, body):
        payload = {"document_id": document_id,
                   "approved_revision": approved_revision, "body": body}
        workflow = self.runtime.accept(command_id, payload)
        return self.runtime.activity(
            workflow, "publish",
            lambda: self.publisher.create(workflow + ":publish", payload),
        )


def start_test_service():
    return PublicationService(ContractRuntime(), PublisherFake())
