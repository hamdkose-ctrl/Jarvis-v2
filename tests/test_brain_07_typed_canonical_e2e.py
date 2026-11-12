"""BRAIN-07: real typed Brain → Core publication → existing Scheduler → delivery.

No real model/provider/device is called. The Brain transport and provider
worker are the only mocked external boundaries; journals, Core CAS, Scheduler,
domain evidence, and first-party completion code remain live.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness
from modules import (
    brain_entry, canonical_goal_flow, canonical_plan_evidence,
    canonical_scheduler_dispatch, execution_record, goal_executor,
    goal_state_compat, goal_state_store, model_wait, requests_state, service_store,
    task_agents, task_queue, task_results, untrusted_flow,
)
from modules import brain_model_understanding as envelope


def research_tasks(*names):
    return {'tasks': [
        {'id': name, 'agent': 'research', 'depends': [],
         'input': {'url': 'https://example.test/article', 'question': 'compare'}}
        for name in names
    ]}


class RapidStop:
    def __init__(self):
        self.event = threading.Event()
    def wait(self, _timeout):
        return self.event.wait(.015)
    def is_set(self):
        return self.event.is_set()
    def set(self):
        self.event.set()


class TypedCanonicalFlowTests(_CanonicalAuthorityHarness):
    """Use real Brain prepare/handoff with mocked semantic provider payload."""

    def setUp(self):
        super().setUp()
        self.mocks = ExitStack()
        self.addCleanup(self.mocks.close)
        for target, value in (
            ('modules.llm.current_user', lambda: self.owner),
            ('modules.llm.provider', lambda: 'groq'),
            ('modules.llm.privacy.mode', lambda: 'normal'),
            ('modules.smart_router.selection', lambda *args, **kwargs: {'candidates': ['groq']}),
        ):
            self.mocks.enter_context(patch(target, value))

    def envelope(self):
        return json.dumps({
            'schema_version': envelope.SCHEMA_VERSION,
            'operation': 'create_goal', 'conversation_relation': 'NEW_REQUEST',
            'temporal_need': 'STATIC', 'target_goal_ids': [],
            'goal': {'kind': 'goal', 'title': 'Kaynakları karşılaştır'},
            'actions': [],
            'clarification': {'required': False, 'question': None, 'reason_code': None},
            'confidence': 'HIGH',
        })

    def typed_turn(self, request='İki kaynağı araştır ve karşılaştır.', rid=None):
        rid = rid or ('brain07-' + uuid.uuid4().hex[:12])
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            with patch('modules.smart_router.run', return_value=self.envelope()):
                entry = brain_entry.prepare(
                    self.ctx, owner=self.owner, request_id=rid,
                    text=request, source='yazı', model_understanding=True,
                )
                result, feedback, job_id = brain_entry.handoff(
                    self.ctx, entry, Mock(return_value='LEGACY_HANDLER'), request,
                )
        return rid, result, feedback, job_id

    def persisted(self, job_id):
        root = goal_executor._owner_root(self.owner)
        return (
            goal_state_store.load(root / (job_id + '.goalstate.json')),
            execution_record.load(root, self.owner, job_id),
        )

    def test_typed_user_request_publishes_matching_core_plan_and_queued_record(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first', 'second'))):
            rid, reply, fb, job_id = self.typed_turn()
        self.assertEqual(fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('arka plana', reply)
        self.assertEqual(len(job_id), 16)
        state, journal = self.persisted(job_id)
        self.assertEqual(state['authority'], 'canonical')
        self.assertEqual(state['version'], 1)
        self.assertEqual(state['audit'][-1]['reason_code'], 'CORE_GOAL_PLAN_ACCEPTED')
        self.assertEqual(state['goal_plan']['plan_version'], 1)
        self.assertEqual([row['id'] for row in state['goal_plan']['nodes']], ['first', 'second'])
        self.assertEqual([row['state'] for row in journal['steps']], ['queued', 'queued'])
        self.assertEqual(journal['request_id'], rid)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner)[0].selection.job_id, job_id)
        self.run_goal.assert_not_called()

    def test_duplicate_typed_request_cannot_publish_second_attempt(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))) as planner:
            rid, _, _, job_id = self.typed_turn()
            state_before, journal_before = self.persisted(job_id)
            _, answer, fb, duplicate = self.typed_turn(rid=rid)
        planner.assert_called_once()
        self.assertEqual(job_id, duplicate)
        self.assertEqual(fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('ikinci kez başlatılmadı', answer)
        self.assertEqual(self.persisted(job_id), (state_before, journal_before))

    def test_duplicate_with_unsupported_second_model_plan_never_enters_legacy(self):
        """A duplicate must win before a different, effectful planner reply.

        Regression for the old order: model validation returned None before
        checking the existing request, then goal_resolver fell back to
        goal_executor._run and allocated a second unrelated goal ID.
        """
        effectful = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Save report', 'filename': 'report.md'},
        }]}
        with patch.object(model_wait, 'ask', side_effect=[
            json.dumps(research_tasks('first')), json.dumps(effectful),
        ]) as planner:
            rid, _, first_fb, job_id = self.typed_turn()
            before = self.persisted(job_id)
            _, reply, second_fb, same_job = self.typed_turn(rid=rid)
        self.assertEqual(first_fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        planner.assert_called_once()
        self.assertEqual(same_job, job_id)
        self.assertEqual(second_fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('ikinci kez başlatılmadı', reply)
        self.assertEqual(before, self.persisted(job_id))
        self.run_goal.assert_not_called()
        root = goal_executor._owner_root(self.owner)
        self.assertEqual(len(tuple(root.glob('*.execution.json'))), 1)

    def test_request_id_collision_rejects_before_any_planner_call(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            rid, _, _, job_id = self.typed_turn()
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('model called for an existing request')):
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(
                    self.owner, rid, 'Different request under an existing ID',
                )
        self.assertEqual(self.persisted(job_id)[1]['request_id'], rid)

    def test_partial_publication_retry_fails_before_any_planner_call(self):
        rid = 'partial-publication-id'
        actual_atomic = canonical_goal_flow.release_guard.atomic

        def crash_before_record(path, content):
            if str(path).endswith('.execution.json'):
                raise OSError('simulated half-published journal')
            return actual_atomic(path, content)

        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))), \
                patch.object(canonical_goal_flow.release_guard, 'atomic',
                             side_effect=crash_before_record):
            with self.assertRaises(OSError):
                canonical_goal_flow.try_create(self.owner, rid, 'Read two sources')
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('model called after partial publication')):
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(self.owner, rid, 'Read two sources')

    def _completed_with_unknown_delivery(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]

        def research_worker(owner, task, dependencies):
            return task_results.seal('research', {
                'state': 'done', 'text': 'Source-backed comparison',
                'source': 'https://example.test/article', 'source_chars': 200,
            })

        with patch.object(task_agents, 'worker', research_worker), \
                patch.object(untrusted_flow, 'observe', lambda *_: None):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), offer,
            ))

        def uncertain_sink(owner, ident, content):
            state, record = self.persisted(ident)
            self.assertEqual(state['state'], 'done')
            self.assertEqual(record['_canonical_delivery'], 'reserved')
            self.assertEqual(record['_canonical_result_text'], content)
            self.assertEqual(record['_canonical_result_event_id'], 'canonical:' + ident)
            raise ConnectionError('UI status unknown after fanout')

        notified = Mock(side_effect=uncertain_sink)
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={'action': 'complete', 'goal': 0, 'evidence': ['first']}):
            self.assertFalse(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
        notified.assert_called_once()
        return job_id

    def test_reserved_result_stays_readable_without_model_worker_or_notification(self):
        job_id = self._completed_with_unknown_delivery()
        before = self.persisted(job_id)
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('read must not call a model')):
            result = canonical_goal_flow.read_result_command(
                self.owner, 'hedef sonucu ' + job_id,
            )
        self.assertIn('Source-backed comparison', result)
        self.assertIn(job_id, result)
        self.assertEqual(before, self.persisted(job_id))
        notify = Mock()
        self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, job_id, notify))
        notify.assert_not_called()

    def test_reserved_result_read_rejects_foreign_owner_and_tampered_output(self):
        job_id = self._completed_with_unknown_delivery()
        foreign = canonical_goal_flow.read_result_command(
            'another-owner', 'hedef sonucu ' + job_id,
        )
        self.assertNotIn('Source-backed comparison', foreign)
        self.assertIsNone(canonical_goal_flow.read_result_command(
            self.owner, 'araştırmanın sonucu nedir',
        ))
        root = goal_executor._owner_root(self.owner)
        altered = execution_record.load(root, self.owner, job_id)
        altered['outputs']['first']['text'] = 'Forged result should never be shown'
        canonical_goal_flow.release_guard.atomic(
            execution_record.path_for(root, job_id), execution_record.encode(altered),
        )
        with self.assertRaises(ValueError):
            canonical_goal_flow.read_completed_result(self.owner, job_id)
        response = canonical_goal_flow.read_result_command(
            self.owner, 'hedef sonucu ' + job_id,
        )
        self.assertNotIn('Forged result', response)

    def test_queued_result_query_never_claims_done_or_starts_model(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('pending query must not call model')):
            message = canonical_goal_flow.read_result_command(
                self.owner, 'hedef sonucu ' + job_id,
            )
        self.assertIn('henüz', message)
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')

    def test_effectful_plan_keeps_existing_legacy_permission_path(self):
        writer = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Save report', 'filename': 'report.md'},
        }]}
        with patch.object(model_wait, 'ask', return_value=json.dumps(writer)):
            _, _, fb, job_id = self.typed_turn('Bir raporu dosyaya kaydet.')
        self.assertEqual(fb.reason_code, 'GOAL_CREATE')
        self.assertIsNone(job_id)
        self.run_goal.assert_called_once()
        self.assertEqual(tuple((goal_executor.STORE / self.owner).glob('*.execution.json')), ())
        self.assertEqual(tuple((goal_executor.STORE / self.owner).glob('*.goalstate.json')), ())

    def test_crashed_partial_publication_is_not_admitted_or_retried(self):
        actual_atomic = canonical_goal_flow.release_guard.atomic
        def fail_record_write(path, data):
            if str(path).endswith('.execution.json'):
                raise OSError('simulated crash between canonical and journal writes')
            return actual_atomic(path, data)
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))), \
                patch.object(canonical_goal_flow.release_guard, 'atomic',
                             side_effect=fail_record_write):
            with self.assertRaises(OSError):
                self.typed_turn()
        root = goal_executor._owner_root(self.owner)
        self.assertEqual(tuple(root.glob('*.execution.json')), ())
        self.assertEqual(len(tuple(root.glob('*.goalstate.json'))), 1)
        self.assertEqual(tuple(canonical_scheduler_dispatch.discover(self.owner)), ())

    def test_core_completion_adapter_rejects_missing_projected_proof(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        path = goal_executor._owner_root(self.owner) / (job_id + '.goalstate.json')
        with self.assertRaises(goal_state_compat.ReconcilePolicyError):
            goal_state_compat.commit_verified_goal_completion(
                path, owner=self.owner, job_id=job_id, proof=None,
            )
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')

    def test_semantic_refusal_never_marks_completed_or_sends_result(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        with patch.object(canonical_plan_evidence, 'certify_projected_plan',
                          side_effect=canonical_plan_evidence.PlanEvidenceError('no complete proof')):
            notified = Mock()
            self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, job_id, notified))
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')
        notified.assert_not_called()

    def test_real_scheduler_verifies_and_delivers_once_to_pinned_owner(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        stop = RapidStop()
        messages = []
        completed = threading.Event()
        def research_worker(owner, task, dependencies):
            self.assertEqual(owner, self.owner)
            self.assertEqual(dependencies, {})
            return task_results.seal('research', {
                'state': 'done', 'text': 'Source-backed comparison',
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        def notify(owner, ident, text):
            messages.append((owner, ident, text))
            completed.set()
        def finished(owner, ident):
            canonical_goal_flow.complete_and_deliver(owner, ident, notify)
        try:
            with ExitStack() as patches:
                for obj, attribute, value in (
                    (service_store, 'ROOT', Path(self.temp.name) / 'missing_sqlite'),
                    (task_queue, '_THREAD', None),
                    (task_queue, '_OWNER_TICKS', {}),
                    (task_queue, '_CANONICAL_WORKERS', {}),
                    (task_queue, '_LAST_ADMITTED', {}),
                    (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                    (task_queue, '_DAILY_NOTIFY', None),
                    (task_agents, 'worker', research_worker),
                    (untrusted_flow, 'observe', lambda *_: None),
                ):
                    patches.enter_context(patch.object(obj, attribute, value))
                patches.enter_context(patch.object(
                    model_wait, 'ask', return_value=json.dumps({
                        'action': 'complete', 'goal': 0, 'evidence': ['first'],
                    }),
                ))
                task_queue.start(
                    stop, allowed_owners=lambda: {self.owner},
                    canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
                    canonical_result_notify=finished,
                )
                self.assertTrue(completed.wait(25), 'Real Scheduler did not publish verified result')
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0][0:2], (self.owner, job_id))
                self.assertIn('Source-backed comparison', messages[0][2])
                # notify() fires before the final durable delivery-marker
                # commit. Its callback event proves only sink invocation, not
                # that the Scheduler worker has finished its journal write.
                # Wait for durable state instead of racing the callback thread.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state, journal = self.persisted(job_id)
                    if journal.get('_canonical_delivery') == 'delivered':
                        break
                    completed.wait(.025)
                    time.sleep(.025)
                state, journal = self.persisted(job_id)
                self.assertEqual(state['state'], 'done')
                self.assertEqual(journal['_canonical_delivery'], 'delivered')
                self.assertEqual(journal['_canonical_result_event_id'], 'canonical:' + job_id)
                self.assertIn('Source-backed comparison', journal['_canonical_result_text'])
                self.assertIn('Source-backed comparison', canonical_goal_flow.read_completed_result(
                    self.owner, job_id,
                ))
                self.assertEqual(journal['goals'][0]['state'], 'done')
                self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, job_id, notify))
                self.assertEqual(len(messages), 1)
                self.run_goal.assert_not_called()
        finally:
            stop.set()
            if task_queue._THREAD is not None:
                task_queue._THREAD.join(10)
            for worker in tuple(task_queue._CANONICAL_WORKERS.values()):
                worker.join(10)


    def test_foreground_accepts_second_independent_goal_while_worker_is_running(self):
        entered = threading.Event()
        release = threading.Event()
        stop = RapidStop()
        def research_worker(owner, task, dependencies):
            entered.set()
            self.assertTrue(release.wait(20), 'Provider gate never released')
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified ' + task['id'],
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        with ExitStack() as patches:
            for obj, attribute, value in (
                (service_store, 'ROOT', Path(self.temp.name) / 'missing_sqlite'),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_LAST_ADMITTED', {}),
                (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (task_agents, 'worker', research_worker),
                (untrusted_flow, 'observe', lambda *_: None),
            ):
                patches.enter_context(patch.object(obj, attribute, value))
            patches.enter_context(patch.object(
                model_wait, 'ask', side_effect=[
                    json.dumps(research_tasks('first')),
                    json.dumps(research_tasks('second')),
                ],
            ))
            _, _, _, first = self.typed_turn('Birinci kaynağı araştır.')
            task_queue.start(
                stop, allowed_owners=lambda: {self.owner},
                canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
            )
            try:
                self.assertTrue(entered.wait(15), 'First canonical provider did not start')
                started = time.monotonic()
                _, _, feedback, second = self.typed_turn('İkinci bağımsız kaynağı araştır.')
                self.assertLess(time.monotonic() - started, 8)
                self.assertNotEqual(first, second)
                self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
                self.assertEqual(self.persisted(second)[0]['state'], 'pending')
                self.run_goal.assert_not_called()
            finally:
                release.set()
                stop.set()
                if task_queue._THREAD is not None:
                    task_queue._THREAD.join(10)
                for worker in tuple(task_queue._CANONICAL_WORKERS.values()):
                    worker.join(10)

    def test_unrelated_owner_cannot_observe_foreign_result(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('private'))):
            foreign, _ = canonical_goal_flow.try_create(
                'another-owner', 'other-request', 'Read a private source',
            )
        notify = Mock()
        self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, foreign, notify))
        notify.assert_not_called()
        self.assertEqual(
            execution_record.load(goal_executor._owner_root('another-owner'),
                                  'another-owner', foreign)['owner'],
            'another-owner',
        )


    def test_all_workers_done_still_requires_semantic_core_completion(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]
        def worker(owner, task, dependencies):
            return task_results.seal('research', {
                'state': 'done', 'text': 'An incomplete research answer',
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        with patch.object(task_agents, 'worker', worker), \
                patch.object(untrusted_flow, 'observe', lambda *_: None):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), offer,
            ))
        proof = canonical_plan_evidence.certify_projected_plan(self.owner, job_id)
        self.assertEqual(proof.job_id, job_id)
        notified = Mock()
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={'action': 'ask', 'question': 'Not enough evidence'}):
            self.assertFalse(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'pending')
        self.assertEqual(journal['state'], 'running')
        notified.assert_not_called()
