import hashlib
import json
import pathlib
import sys

PROJECT = pathlib.Path(__file__).resolve().parents[2] / 'fixtures' / 'item_adaptation' / 'check'
sys.path.insert(0, str(PROJECT))


def manifest():
    return {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(PROJECT.rglob('*')) if p.is_file()}


before = manifest()
from app import PublicationService
from runtime_fixture import ContractRuntime, PublisherFake


class CountingPublisher(PublisherFake):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def create(self, key, content):
        self.calls += 1
        return super().create(key, content)


class LoseActivityCompletion(ContractRuntime):
    def __init__(self):
        super().__init__()
        self.lose_completion = True

    def activity(self, workflow, name, execute):
        if self.lose_completion:
            self.lose_completion = False
            execute()
            raise TimeoutError('injected: activity completion not recorded')
        return super().activity(workflow, name, execute)


cases = []


def run_case(name, second_command='cmd-a', second_revision='rev-1', second_body='approved body',
             expected_effects=1, expect_conflict=False, lose_reply=False, lose_completion=False):
    runtime = LoseActivityCompletion() if lose_completion else ContractRuntime()
    publisher = CountingPublisher()
    publisher.lose_reply = lose_reply
    service = PublicationService(runtime, publisher)
    first_result = None
    first_error = None
    try:
        first_result = service.submit('cmd-a', 'doc-1', 'rev-1', 'approved body')
    except TimeoutError as error:
        first_error = str(error)
    intermediate = {'workflows': len(runtime.workflows), 'history_results': len(runtime.results),
                    'effects': len(publisher.effects), 'calls': publisher.calls}
    second_result = None
    second_error = None
    try:
        second_result = service.submit(second_command, 'doc-1', second_revision, second_body)
    except ValueError as error:
        second_error = str(error)
    conflict = second_error is not None
    passed = len(publisher.effects) == expected_effects and conflict == expect_conflict
    if not expect_conflict and expected_effects == 1:
        passed = passed and second_result == publisher.effects[0][2]
    cases.append({'name': name, 'meets_current_requirement': passed,
                  'expected_effects': expected_effects, 'expected_conflict': expect_conflict,
                  'first_result': first_result, 'first_error': first_error,
                  'after_first_call': intermediate,
                  'second_result': second_result, 'second_error': second_error,
                  'actual_effects': len(publisher.effects), 'publisher_calls': publisher.calls,
                  'downstream_keys': list(publisher.by_key),
                  'workflow_count': len(runtime.workflows), 'history_results': len(runtime.results)})


run_case('same command, same approved revision and body')
run_case('new command, same approved revision and body', second_command='cmd-b')
run_case('same command, changed body', second_body='changed body', expect_conflict=True)
run_case('new command, same approved revision but changed body', second_command='cmd-b',
         second_body='changed body', expect_conflict=True)
run_case('new command, new approved revision with same body', second_command='cmd-b',
         second_revision='rev-2', expected_effects=2)
run_case('publisher reply lost, same command retried', lose_reply=True)
run_case('publisher reply lost, new command retried', second_command='cmd-b', lose_reply=True)
run_case('successful publish before activity completion record, same command retried', lose_completion=True)

after = manifest()
result = {'python_version': sys.version.split()[0], 'project_manifest': before,
          'project_unchanged': before == after,
          'scenario_count': len(cases),
          'requirements_met': sum(case['meets_current_requirement'] for case in cases),
          'requirements_violated': sum(not case['meets_current_requirement'] for case in cases),
          'cases': cases,
          'limitations': ['in-memory contract doubles only', 'no process restart or real dependencies',
                          'no concurrent or load testing', 'no network or external publication']}
print(json.dumps(result, ensure_ascii=False, indent=2))
assert before == after, 'project changed during check'
