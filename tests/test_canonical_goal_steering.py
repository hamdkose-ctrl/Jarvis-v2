"""Typed production entry + real Core/durable Scheduler steering; providers fake."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import test_engine_modular  # noqa: F401
import test_brain_07_typed_canonical_e2e as fixture
import test_brain_03_observation_parity as observation
from test_brain_primary_understanding import action, envelope
from modules import (
    brain_entry, canonical_goal_control, canonical_plan_evidence, canonical_plan_revision,
    canonical_planning_queue, canonical_scheduler_dispatch, execution_record, goal_executor,
    goal_job_control, goal_state, goal_state_store, model_wait, task_agents, task_queue, task_results, untrusted_flow,
)


class BatchDomainOutcomeTests(unittest.TestCase):
    def test_real_note_then_dependent_task_uses_persisted_success(self):
        c = observation.ObservationParityTests()
        c.setUp()
        self.addCleanup(c.doCleanups)
        first = action(capability_id='notes.add', arguments={'text': 'süt'}, action_id='a1')
        first['argument_sources'] = {'text': 'süt'}
        second = action(capability_id='tasks.manage', arguments={'operation': 'add', 'text': 'alışveriş'},
                        action_id='a2', depends_on=['a1'])
        second['argument_sources'] = {'text': 'alışveriş'}
        _entry, _text, feedback, _prompt = c.model_turn('süt notunu ekle sonra alışveriş görevi ekle',
            raw=envelope(operation='action_batch', confidence='HIGH', actions=[first, second]))
        self.assertEqual(feedback.result_status, 'handled')
        self.assertEqual(c.ctx.profile.data['items'][0]['text'], 'süt')
        self.assertEqual(c.ctx.profile.data['tasks'][0]['text'], 'alışveriş')

    def test_failed_domain_save_leaves_no_ghost_note_or_task(self):
        for capability, collection in (('notes.add', 'items'), ('tasks.manage', 'tasks')):
            with self.subTest(capability=capability):
                c = observation.ObservationParityTests()
                c.setUp()
                try:
                    args = {'text': 'süt'}
                    if capability == 'tasks.manage':
                        args['operation'] = 'add'
                    before = list(c.ctx.profile.data.get(collection, []))
                    with patch.object(c.ctx.profile, 'save', side_effect=OSError('disk unavailable')):
                        with self.assertRaises(OSError):
                            c.model_turn('süt notunu veya görevini ekle', capability, args, sources={'text': 'süt'})
                    self.assertEqual(brain_entry.last_feedback().result_status, 'failed')
                    self.assertEqual(c.ctx.profile.data.get(collection, []), before)
                finally:
                    c.doCleanups()


class CanonicalSteeringTests(unittest.TestCase):
    def setUp(self):
        self.c = fixture.TypedCanonicalFlowTests()
        self.c.setUp()
        self.addCleanup(self.c.doCleanups)
        self.owner = self.c.owner
        self.profile = SimpleNamespace(slug=self.owner)

    def create(self, *names):
        with patch.object(task_queue, 'scheduler_active', return_value=False), \
             patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks(*(names or ('first',))))):
            return self.c.typed_turn()[3]

    def control(self, ident, operation, text='bu araştırmayı düzenle'):
        row = json.loads(self.c.envelope())
        row.update(operation=operation, target_goal_ids=[ident], goal=None)
        self.c.router_stub.return_value = json.dumps(row)
        return self.c.typed_turn(text)

    def execute_one(self, ident, *, worker=None):
        offers = [offer for offer in canonical_scheduler_dispatch.discover(self.owner, max_offers=8)
                  if offer.selection.job_id == ident]
        self.assertTrue(offers)
        def result(owner, task, deps):
            return task_results.seal('research', {'state': 'done', 'text': 'Verified source',
                'source': 'https://example.test/article', 'source_chars': 200})
        with patch.object(task_agents, 'worker', worker or result), \
             patch.object(untrusted_flow, 'observe', lambda *_: None):
            return canonical_scheduler_dispatch.execute_offer(self.profile, offers[0])

    def revise(self, ident, *names):
        self.control(ident, 'revise_goal', 'yalnız gerekli kaynakları araştır')
        self.assertIn(ident, canonical_planning_queue.discover(self.owner))
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks(*names))):
            return canonical_planning_queue.execute(self.profile, ident)

    def test_pause_resume_is_a_real_core_transition_without_new_execution(self):
        ident = self.create('first', 'second')
        _rid, reply, feedback, _job = self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
        self.assertEqual(feedback.result_status, 'handled')
        state, record = self.c.persisted(ident)
        self.assertEqual((state['state'], record['state']), ('paused', 'paused'))
        self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
        self.control(ident, 'resume_goal', 'bu araştırmayı sürdür')
        state, record = self.c.persisted(ident)
        self.assertEqual((state['state'], record['state']), ('running', 'running'))
        self.assertEqual(state['goal_plan']['plan_version'], 1)
        self.assertTrue(canonical_scheduler_dispatch.discover(self.owner))
        self.c.run_goal.assert_not_called()

    def test_queued_first_planner_can_pause_and_resume_without_a_second_goal(self):
        with patch.object(task_queue, 'scheduler_active', return_value=True):
            ident = self.c.typed_turn()[3]
        self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
        self.assertFalse(canonical_planning_queue.discover(self.owner))
        self.control(ident, 'resume_goal', 'bu araştırmayı sürdür')
        self.assertIn(ident, canonical_planning_queue.discover(self.owner))
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('first'))):
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        self.assertEqual(self.c.persisted(ident)[0]['goal_plan']['plan_version'], 1)

    def test_edit_before_first_plan_uses_same_goal_and_new_explicit_planning_generation(self):
        with patch.object(task_queue, 'scheduler_active', return_value=True):
            ident = self.c.typed_turn()[3]
        old_rid = self.c.persisted(ident)[1]['_planner_rid']
        self.control(ident, 'add_task', 'bu araştırmaya üçüncü kaynağı ekle')
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('first', 'third'))) as model:
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        state, record = self.c.persisted(ident)
        self.assertNotEqual(record['_planner_rid'], old_rid)
        self.assertIn('üçüncü kaynağı', model.call_args.args[0])
        self.assertEqual(state['goal_plan']['plan_version'], 1)

    def test_direct_resume_of_unplanned_canonical_goal_never_calls_legacy_model_loop(self):
        with patch.object(task_queue, 'scheduler_active', return_value=True):
            ident = self.c.typed_turn()[3]
        self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
        self.assertTrue(goal_executor.canonical_scheduler_owned(self.owner, ident))
        with patch.object(goal_executor, '_loop', side_effect=AssertionError('second execution authority')):
            goal_executor._run(self.c.ctx, 'devam', resume=True, job_id=ident)
        state, record = self.c.persisted(ident)
        self.assertEqual((state['state'], record['state']), ('pending', 'planning_queued'))

    def test_real_scheduler_queues_edit_at_checkpoint_reuses_result_and_delivers(self):
        ident = self.create('first')
        entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
        calls = []
        stop = fixture.RapidStop()
        def worker(owner, task, deps):
            calls.append(task['id'])
            if task['id'] == 'first':
                entered.set()
                self.assertTrue(release.wait(8))
            return task_results.seal('research', {'state': 'done', 'text': 'Verified source',
                'source': 'https://example.test/article', 'source_chars': 200})
        def model(prompt, **kwargs):
            value = json.loads(prompt)
            if 'previous_plan' in value:
                return json.dumps(fixture.research_tasks('first', 'third'))
            return json.dumps({'action': 'complete', 'goal': 0, 'evidence': value['required_evidence']})
        def notify(owner, job, message):
            self.assertEqual((owner, job), (self.owner, ident))
            delivered.set()
            return {'ui': 'delivered'}
        def complete(owner, job):
            from modules import canonical_goal_flow
            return canonical_goal_flow.complete_and_deliver(owner, job, notify)
        with patch.object(task_queue, '_THREAD', None), \
             patch.object(task_queue, '_CANONICAL_WORKERS', {}), \
             patch.object(task_queue, '_OWNER_TICKS', {}), \
             patch.object(task_queue, '_CANONICAL_RESUME_ATTEMPTED', set()), \
             patch.object(task_queue, 'tick', return_value=None), \
             patch.object(task_agents, 'worker', worker), \
             patch.object(untrusted_flow, 'observe', lambda *_: None), \
             patch.object(model_wait, 'ask', side_effect=model):
            try:
                task_queue.start(stop, allowed_owners=lambda: [self.owner],
                    canonical_profile_resolver=lambda owner: self.profile,
                    canonical_result_notify=complete)
                self.assertTrue(entered.wait(8))
                self.control(ident, 'revise_goal', 'araştırmaya üçüncü kaynağı ekle')
                release.set()
                self.assertTrue(delivered.wait(8), repr((calls, self.c.persisted(ident))))
            finally:
                release.set()
                stop.set()
                task_queue._THREAD.join(8)
                for thread in tuple(task_queue._CANONICAL_WORKERS.values()):
                    thread.join(8)
                    self.assertFalse(thread.is_alive())
        state, record = self.c.persisted(ident)
        self.assertEqual(state['state'], 'done')
        self.assertEqual(record['state'], 'done')
        self.assertEqual(state['goal_plan']['plan_version'], 2)
        self.assertEqual(calls, ['first', 'third'])

    def test_pause_inflight_finishes_checkpoint_without_replaying_or_losing_result(self):
        ident = self.create('first', 'second')
        entered, release = threading.Event(), threading.Event()
        calls = []
        def worker(owner, task, deps):
            calls.append(task['id'])
            entered.set()
            self.assertTrue(release.wait(8))
            return task_results.seal('research', {'state': 'done', 'text': 'Verified source',
                'source': 'https://example.test/article', 'source_chars': 200})
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.execute_one, ident, worker=worker)
            try:
                self.assertTrue(entered.wait(8))
                self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
                self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
                self.control(ident, 'resume_goal', 'bekletmekten vazgeçtim, devam et')
                self.assertIsNone(self.c.persisted(ident)[0]['blocker'])
                self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
            finally:
                release.set()
            self.assertTrue(future.result(timeout=8))
        canonical_goal_control.settle_pause(self.owner, ident)
        state, record = self.c.persisted(ident)
        self.assertEqual(state['state'], 'paused')
        self.assertEqual(record['steps'][0]['state'], 'done')
        self.assertEqual(calls, ['first'])
        self.control(ident, 'resume_goal', 'bu araştırmaya devam et')
        offers = canonical_scheduler_dispatch.discover(self.owner)
        self.assertEqual([offer.selection.node_id for offer in offers], ['second'])

    def test_revision_publishes_next_plan_and_reuses_only_verified_unchanged_node(self):
        ident = self.create('first', 'second')
        self.assertTrue(self.execute_one(ident))
        self.assertEqual(self.revise(ident, 'first', 'third'), 'planned')
        state, record = self.c.persisted(ident)
        self.assertEqual(state['goal_plan']['plan_version'], 2)
        self.assertEqual([step['state'] for step in record['steps']], ['done', 'queued'])
        self.assertEqual(record['steps'][0]['reused_from']['plan_version'], 1)
        self.assertEqual(len(record['goals']), 1)
        self.assertEqual(len(record['_plan_history']), 1)
        self.assertEqual([offer.selection.node_id for offer in canonical_scheduler_dispatch.discover(self.owner)], ['third'])
        self.assertTrue(self.execute_one(ident))
        self.assertEqual(len(canonical_plan_evidence.certify_projected_plan(self.owner, ident).output_digests), 2)

    def test_add_task_replans_same_goal_instead_of_leaving_intent_only(self):
        ident = self.create('first')
        self.control(ident, 'add_task', 'bu araştırmaya üçüncü kaynağı da ekle')
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('first', 'third'))):
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        state, record = self.c.persisted(ident)
        self.assertEqual(state['goal_plan']['plan_version'], 2)
        self.assertEqual(len(record['steps']), 2)
        self.assertEqual(len(record['goals']), 1)
        self.assertTrue(record['goal_intent']['additions'])

    def test_ordered_edits_reach_planner_and_semantic_completion(self):
        ident = self.create('first')
        changes = [('add_task', 'araştırmaya A kaynağını ekle'),
                   ('revise_goal', 'yalnız B kaynağını araştır'),
                   ('add_task', 'araştırmaya C kaynağını ekle')]
        for operation, text in changes:
            self.control(ident, operation, text)
        state, record = self.c.persisted(ident)
        history = goal_state.intent_history(state)
        self.assertEqual([(row['operation'], row['text']) for row in history],
                         [('add_task', changes[0][1]), ('revise', changes[1][1]), ('add_task', changes[2][1])])
        self.assertEqual(record['goal_intent_history'], history)
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('B', 'C'))) as model:
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        self.assertEqual(json.loads(model.call_args.args[0])['user_goal_changes'], history)
        self.assertTrue(self.execute_one(ident))
        self.assertTrue(self.execute_one(ident))
        from modules import canonical_goal_flow
        state, record = self.c.persisted(ident)
        with patch.object(model_wait, 'ask', return_value=json.dumps(
                {'action': 'complete', 'goal': 0, 'evidence': ['B', 'C']})) as model:
            canonical_goal_flow._semantic_proposal(self.owner, record, ('B', 'C'))
        self.assertEqual(json.loads(model.call_args.args[0])['user_goal_changes'], history)
        self.assertEqual([row['kind'] for row in state['evidence']].count('worker_result'), 2)

    def test_edits_before_first_plan_keep_their_order_and_require_core_evidence(self):
        with patch.object(task_queue, 'scheduler_active', return_value=True):
            ident = self.c.typed_turn()[3]
        self.control(ident, 'add_task', 'araştırmaya A kaynağını ekle')
        self.control(ident, 'revise_goal', 'yalnız B kaynağını araştır')
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('B'))) as model:
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        state, record = self.c.persisted(ident)
        self.assertIn('user_goal_changes', model.call_args.args[0])
        history = goal_state.intent_history(state)
        self.assertEqual([row['operation'] for row in history], ['add_task', 'revise'])
        self.assertEqual(record['goal_intent_history'], history)
        forged = copy.deepcopy(state)
        forged['evidence'][0]['intent_version'] += 1
        with self.assertRaises(ValueError):
            goal_state.intent_history(forged)

    def test_user_can_hold_and_resume_a_queued_plan_revision(self):
        ident = self.create('first')
        self.control(ident, 'revise_goal', 'araştırmaya yeni kaynak ekle')
        self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
        self.assertFalse(canonical_planning_queue.discover(self.owner))
        self.assertEqual(self.c.persisted(ident)[1]['state'], 'paused')
        self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
        self.assertEqual(self.c.persisted(ident)[1]['state'], 'paused')
        self.control(ident, 'resume_goal', 'bu araştırmayı sürdür')
        self.assertIn(ident, canonical_planning_queue.discover(self.owner))
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('second'))):
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')

    def test_resume_during_revision_does_not_unpause_the_old_plan_or_replan_twice(self):
        ident = self.create('first')
        self.control(ident, 'revise_goal', 'araştırmaya yeni kaynak ekle')
        before = self.c.persisted(ident)
        self.control(ident, 'resume_goal', 'bu araştırmaya devam et')
        self.assertEqual(self.c.persisted(ident), before)
        self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
        self.assertIn(ident, canonical_planning_queue.discover(self.owner))

    def test_pause_while_revision_model_runs_holds_the_new_plan_before_worker_admission(self):
        ident = self.create('first')
        self.control(ident, 'revise_goal', 'araştırmaya yeni kaynak ekle')
        entered, release = threading.Event(), threading.Event()
        def planner(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(8))
            return json.dumps(fixture.research_tasks('second'))
        with patch.object(model_wait, 'ask', side_effect=planner), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(canonical_planning_queue.execute, self.profile, ident)
            try:
                self.assertTrue(entered.wait(8))
                self.control(ident, 'pause_goal', 'bu araştırmayı beklet')
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=8), 'planned')
        self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
        state, record = self.c.persisted(ident)
        self.assertEqual((state['state'], record['state']), ('paused', 'paused'))
        self.assertEqual(state['goal_plan']['plan_version'], 2)
        self.control(ident, 'resume_goal', 'bu araştırmayı sürdür')
        self.assertTrue(canonical_scheduler_dispatch.discover(self.owner))

    def test_priority_changes_actual_offer_order_without_invalidating_plan(self):
        first = self.create('one')
        second = self.create('two')
        self.control(second, 'prioritize_goal', 'ikinci araştırmayı önce yap')
        offers = canonical_scheduler_dispatch.discover(self.owner, max_offers=1)
        self.assertEqual(offers[0].selection.job_id, second)
        self.assertEqual(self.c.persisted(second)[0]['goal_plan']['plan_version'], 1)
        self.assertTrue(self.execute_one(second))
        self.assertTrue(any(o.selection.job_id == first for o in canonical_scheduler_dispatch.discover(self.owner)))

    def test_old_offer_is_rejected_after_user_revision(self):
        ident = self.create('first')
        old = canonical_scheduler_dispatch.discover(self.owner)[0]
        self.assertEqual(self.revise(ident, 'second'), 'planned')
        with self.assertRaises(ValueError):
            canonical_scheduler_dispatch.execute_offer(self.profile, old)
        self.assertFalse([row for row in self.c.persisted(ident)[0]['evidence'] if row.get('kind') == 'worker_result'])

    def test_stale_snapshot_cannot_pause_or_mutate_a_newer_goal(self):
        ident = self.create('first')
        old = goal_executor.read_job(self.owner, ident)
        snapshot = {'canonical_version': old['_canonical_version'], 'execution_snapshot': old['_execution_snapshot']}
        self.control(ident, 'prioritize_goal', 'bu araştırmayı önce yap')
        before = self.c.persisted(ident)
        with self.assertRaises(ValueError):
            canonical_goal_control.control(self.owner, ident, 'pause', expected_snapshot=snapshot)
        self.assertEqual(self.c.persisted(ident), before)

    def test_core_accepted_edit_survives_initial_journal_projection_failure(self):
        ident = self.create('first')
        with patch.object(canonical_goal_control, '_write', side_effect=OSError('journal fault')):
            with self.assertRaises(OSError):
                self.control(ident, 'revise_goal', 'araştırmanın kapsamını değiştir')
        state, record = self.c.persisted(ident)
        self.assertEqual((state['state'], record['state']), ('paused', 'running'))
        self.assertIn(ident, canonical_planning_queue.discover(self.owner))
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('second'))):
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        self.assertEqual(self.c.persisted(ident)[0]['goal_plan']['plan_version'], 2)

    def test_unknown_started_step_cannot_reappear_under_a_new_node_id(self):
        ident = self.create('first')
        root = goal_executor._owner_root(self.owner)
        import release_guard
        with goal_job_control.locked(root, ident):
            record = execution_record.load(root, self.owner, ident)
            record['steps'][0].update(state='failed', started=True, attempts=1)
            record['outputs']['first'] = {'state': 'failed', 'text': 'unknown'}
            release_guard.atomic(execution_record.path_for(root, ident), execution_record.encode(record))
        self.assertEqual(self.revise(ident, 'renamed'), 'review')
        state, record = self.c.persisted(ident)
        self.assertEqual(state['goal_plan']['plan_version'], 1)
        self.assertEqual(record['state'], 'review')

    def test_journal_done_without_core_acceptance_is_still_unknown_and_cannot_replay(self):
        ident = self.create('first')
        root = goal_executor._owner_root(self.owner)
        import release_guard
        with goal_job_control.locked(root, ident):
            record = execution_record.load(root, self.owner, ident)
            record['steps'][0].update(state='done', started=True, attempts=1)
            record['outputs']['first'] = task_results.seal('research', {
                'state': 'done', 'text': 'Unaccepted worker claim',
                'source': 'https://example.test/article', 'source_chars': 200})
            release_guard.atomic(execution_record.path_for(root, ident), execution_record.encode(record))
        self.assertEqual(self.revise(ident, 'renamed'), 'review')
        self.assertFalse([row for row in self.c.persisted(ident)[0]['evidence'] if row.get('kind') == 'worker_result'])

    def test_scheduling_audit_labels_cannot_hide_a_semantic_edit(self):
        ident = self.create('first')
        from modules import core_state_reducer
        state = self.c.persisted(ident)[0]
        for proposal in (
            {'op': 'mutate_goal_intent', 'operation': 'revise', 'text': 'different task',
             'reason_code': 'USER_GOAL_PRIORITY'},
            {'op': 'set_blocker', 'blocker': {'code': 'different blocker'},
             'reason_code': 'USER_GOAL_PAUSE_REQUESTED'},
        ):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                core_state_reducer.apply(state, dict(proposal, expected_version=state['version']))

    def test_post_cas_journal_crash_recovers_only_projection_without_model_or_worker(self):
        ident = self.create('first')
        self.assertTrue(self.execute_one(ident))
        self.control(ident, 'revise_goal', 'araştırmanın kapsamını yeniden düzenle')
        import release_guard
        original = release_guard.atomic
        failed = []
        def fault(path, data):
            if str(path).endswith('.execution.json'):
                job = json.loads(data)['job']
                if job.get('_plan_history') and job.get('state') == 'running' and not failed:
                    failed.append(True)
                    raise OSError('injected journal projection failure')
            return original(path, data)
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('first'))), \
             patch.object(release_guard, 'atomic', fault):
            canonical_planning_queue.execute(self.profile, ident)
        state, record = self.c.persisted(ident)
        self.assertEqual(state['goal_plan']['plan_version'], 2)
        self.assertIn('_pending_plan_projection', record)
        with patch.object(model_wait, 'ask', side_effect=AssertionError('model replay')), \
             patch.object(task_agents, 'worker', side_effect=AssertionError('worker replay')):
            self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
        state, record = self.c.persisted(ident)
        self.assertEqual(record['state'], 'running')
        self.assertNotIn('_pending_plan_projection', record)
        self.assertTrue(canonical_plan_evidence.certify_projected_plan(self.owner, ident))

    def test_changed_domain_proof_is_not_reused_even_for_the_same_node(self):
        ident = self.create('first')
        self.assertTrue(self.execute_one(ident))
        self.control(ident, 'revise_goal', 'bu araştırmayı yeniden değerlendir')
        from modules import goal_tools
        with patch.object(model_wait, 'ask', return_value=json.dumps(fixture.research_tasks('first'))), \
             patch.object(goal_tools, 'verify', return_value=False):
            self.assertEqual(canonical_planning_queue.execute(self.profile, ident), 'planned')
        state, record = self.c.persisted(ident)
        self.assertEqual(record['steps'][0]['state'], 'queued')
        self.assertFalse(record['outputs'])
        self.assertFalse([row for row in state['evidence'] if row.get('kind') == 'worker_result'
                          and row['plan_version'] == 2])

    def test_provider_past_deadline_is_quarantined_while_claim_and_slot_stay_owned(self):
        ident = self.create('first')
        entered, release = threading.Event(), threading.Event()
        stop = fixture.RapidStop()
        def worker(owner, task, deps):
            entered.set()
            self.assertTrue(release.wait(8))
            return task_results.seal('research', {'state': 'done', 'text': 'Late source',
                'source': 'https://example.test/article', 'source_chars': 200})
        with patch.object(task_queue, '_THREAD', None), \
             patch.object(task_queue, '_CANONICAL_WORKERS', {}), \
             patch.object(task_queue, '_OWNER_TICKS', {}), \
             patch.object(task_queue, 'tick', return_value=None), \
             patch.object(task_agents, 'worker', worker), \
             patch.object(untrusted_flow, 'observe', lambda *_: None):
            try:
                task_queue.start(stop, allowed_owners=lambda: [self.owner],
                    canonical_profile_resolver=lambda owner: self.profile)
                self.assertTrue(entered.wait(8))
                workers = tuple(task_queue._CANONICAL_WORKERS.values())
                self.assertEqual(len(workers), 1)
                workers[0]._canonical_lifecycle['deadline']._deadline = 0
                task_queue._quarantine_expired_workers()
                _state, record = self.c.persisted(ident)
                self.assertTrue(record['outputs']['first']['quarantined'])
                self.assertEqual(record['outputs']['first']['reason_code'], 'CANONICAL_WORKER_DEADLINE_UNACCEPTED')
                self.assertTrue(workers[0].is_alive())
                self.assertEqual(len(task_queue._CANONICAL_WORKERS), 1)
                self.assertFalse(canonical_scheduler_dispatch.discover(self.owner))
            finally:
                release.set()
                stop.set()
                task_queue._THREAD.join(8)
                for thread in tuple(task_queue._CANONICAL_WORKERS.values()):
                    thread.join(8)
                    self.assertFalse(thread.is_alive())
        self.assertFalse(self.c.persisted(ident)[0]['evidence'])

    def test_parallel_priorities_do_not_hold_two_goal_locks(self):
        first, second = self.create('one'), self.create('two')
        reached = threading.Barrier(2, timeout=8)
        def priority(ident):
            reached.wait()
            return canonical_goal_control.control(self.owner, ident, 'prioritize')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(priority, first), pool.submit(priority, second)
            self.assertTrue(a.result(timeout=8))
            self.assertTrue(b.result(timeout=8))
        self.assertTrue(canonical_scheduler_dispatch.discover(self.owner))
