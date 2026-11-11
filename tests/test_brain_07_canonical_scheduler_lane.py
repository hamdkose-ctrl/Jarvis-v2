"""BRAIN-07 Scheduler readiness offer tests; no real worker or second loop.

Real canonical CAS, exact ExecutionRecord bytes and predecessor-proof
projection are used; external providers and desktop remain untouched.
"""
from __future__ import annotations

import copy
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import release_guard
from modules import (
    canonical_output_projection, canonical_plan_evidence, canonical_scheduler_dispatch,
    canonical_scheduler_lane, core_state_reducer, execution_record,
    goal_executor, goal_state, goal_state_store, goal_tools,
    runtime_worker_result, task_agents, task_results, untrusted_flow,
    worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test/article', 'question': 'compare'}


def node(name, depends=(), cap='task.research'):
    return {
        'id': name, 'depends_on': list(depends), 'capability_id': cap,
        'input': dict(DATA), 'expected_output': 'verified result',
        'acceptance': 'source-backed proof',
    }


class SchedulerOfferTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name)
        self.owner_root = self.store / OWNER
        self.owner_root.mkdir()
        self.path = self.owner_root / (JOB + '.goalstate.json')
        self.record_path = execution_record.path_for(self.owner_root, JOB)
        self.nodes = [node('left'), node('right'), node('child', ('left',))]
        state = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Read two sources',
            authority='canonical',
        )
        state = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'plan': {'plan_version': 1, 'nodes': self.nodes},
            'expected_version': state['version'], 'reason_code': 'TEST_PLAN',
        })
        goal_state_store.create(self.path, state)
        job = {
            'id': JOB, 'owner': OWNER, 'request': 'Read two sources',
            'state': 'running', 'goals': [],
            'steps': [
                {
                    'id': row['id'], 'tool': 'research',
                    'input': copy.deepcopy(DATA),
                    'depends': list(row['depends_on']), 'state': 'queued',
                }
                for row in self.nodes
            ],
            'outputs': {},
        }
        release_guard.atomic(self.record_path, execution_record.encode(job))
        patch_store = patch.object(goal_executor, 'STORE', self.store)
        patch_store.start()
        self.addCleanup(patch_store.stop)

    def offers(self):
        return canonical_scheduler_lane.ready_offers(OWNER, JOB)

    def accept(self, step, *, state='done'):
        output = {
            'state': state, 'text': 'evidence ' + step,
            'verification': {'test': step},
        }
        identity = {
            'version': 1, 'owner': OWNER, 'job_id': JOB, 'task_id': step,
            'attempt': 1, 'request': 'Read two sources',
        }
        enriched, expected = runtime_worker_result.prepare(
            identity, 'research', dict(DATA),
        )
        wrapped = worker_result_hook.wrap_output(output, enriched)
        runtime_worker_result.accept_and_commit(wrapped, expected)
        return output

    def test_initial_independent_roots_only_and_strict_limit(self):
        self.assertEqual(
            [offer.selection.node_id for offer in self.offers()],
            ['left', 'right'],
        )
        self.assertEqual(len(canonical_scheduler_lane.ready_offers(
            OWNER, JOB, limit=1,
        )), 1)
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.ready_offers(OWNER, JOB, limit=0)

    def test_offer_rechecks_exact_record_snapshot(self):
        original = self.offers()[0]
        self.assertEqual(canonical_scheduler_lane.revalidate_offer(original), original)
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['feedback'] = ['new task plan or operator input']
        release_guard.atomic(self.record_path, execution_record.encode(job))
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.revalidate_offer(original)

    def test_accepted_parent_without_projected_output_cannot_wake_child(self):
        result = self.accept('left')
        self.assertEqual([v.selection.node_id for v in self.offers()], ['right'])
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', result)
        with patch.object(goal_tools, 'verify', return_value=True) as verified:
            ready = self.offers()
            self.assertEqual(
                [offer.selection.node_id for offer in ready],
                ['right', 'child'],
            )
            canonical_scheduler_lane.revalidate_offer(ready[-1])
            verified.assert_called()

    def test_user_intent_edit_invalidates_previous_offer(self):
        before = self.offers()[0]
        old = goal_state_store.load(self.path)
        new = core_state_reducer.apply(old, {
            'op': 'mutate_goal_intent', 'operation': 'revise',
            'text': 'Change the research goal', 'priority': None,
            'expected_version': old['version'], 'reason_code': 'USER_CORRECTION',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=new,
        )
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.revalidate_offer(before)

    def test_mismatched_published_step_rejected_without_worker(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0]['input']['url'] = 'https://foreign.test'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            self.offers()

    def test_completed_step_or_started_step_is_never_offered(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0]['state'] = 'running'
        job['steps'][0]['attempts'] = 1
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.assertEqual([v.selection.node_id for v in self.offers()], ['right'])

    def test_failed_result_is_not_automatically_retried(self):
        self.accept('left', state='failed')
        self.assertEqual([v.selection.node_id for v in self.offers()], ['right'])

    def test_missing_or_foreign_execution_record_fails_closed(self):
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.ready_offers('bob', JOB)
        self.record_path.unlink()
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            self.offers()

    def test_node_from_old_plan_cannot_be_reoffered(self):
        offer = self.offers()[0]
        old = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(old, {
            'op': 'set_goal_plan', 'reason_code': 'USER_REPLAN',
            'plan': {'plan_version': 2, 'nodes': self.nodes},
            'expected_version': old['version'],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=updated,
        )
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.revalidate_offer(offer)

    def test_real_worker_dispatch_projects_two_roots_then_dependent_child(self):
        from types import SimpleNamespace

        # Make the child depend on BOTH roots, using the real Core plan CAS.
        state = goal_state_store.load(self.path)
        nodes = [node('left'), node('right'), node('child', ('left', 'right'))]
        changed = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_DAG',
            'expected_version': state['version'],
            'plan': {'plan_version': 2, 'nodes': nodes},
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=state['version'], next_state=changed,
        )
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][-1]['depends'] = ['left', 'right']
        release_guard.atomic(self.record_path, execution_record.encode(job))

        barrier = threading.Barrier(2, timeout=8)
        observed = []
        errors = []
        def safe_worker(owner, task, deps):
            self.assertEqual(owner, OWNER)
            self.assertEqual(task['agent'], 'research')
            if task['id'] in ('left', 'right'):
                barrier.wait()
            else:
                self.assertEqual(set(deps), {'left', 'right'})
            observed.append(task['id'])
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified ' + task['id'],
                'source': DATA['url'], 'source_chars': 200,
            })

        runtime = SimpleNamespace(slug=OWNER)
        # The first reservation modifies the journal digest, so re-select
        # second root from durable disk rather than replaying an old offer.
        def dispatch(offer):
            try:
                canonical_scheduler_dispatch.execute_offer(runtime, offer)
            except Exception as exc:
                errors.append(exc)

        with patch.object(task_agents, 'worker', side_effect=safe_worker), \
             patch.object(untrusted_flow, 'observe'):
            left = self.offers()[0]
            first = threading.Thread(target=dispatch, args=(left,))
            first.start()
            try:
                for _ in range(300):
                    recorded = execution_record.load(self.owner_root, OWNER, JOB)
                    if recorded['steps'][0]['state'] == 'running':
                        break
                    threading.Event().wait(.01)
                second = next(o for o in self.offers()
                              if o.selection.node_id == 'right')
                other = threading.Thread(target=dispatch, args=(second,))
                other.start()
                other.join(12)
                first.join(12)
                self.assertFalse(other.is_alive())
                self.assertFalse(first.is_alive())
                self.assertFalse(errors, repr(errors))
                self.assertIn('left', observed)
                self.assertIn('right', observed)
                children = self.offers()
                self.assertEqual([o.selection.node_id for o in children], ['child'])
                self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                    runtime, children[0],
                ))
                saved = execution_record.load(self.owner_root, OWNER, JOB)
                self.assertEqual(set(saved['outputs']), {'left', 'right', 'child'})
                self.assertTrue(all(step['state'] == 'done' for step in saved['steps']))
            finally:
                barrier.abort()
                first.join(2)

    def test_foreign_profile_never_claims_node(self):
        from types import SimpleNamespace
        offer = self.offers()[0]
        before = self.record_path.read_bytes()
        with self.assertRaises(PermissionError):
            canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug='bob'), offer,
            )
        self.assertEqual(before, self.record_path.read_bytes())

    def test_duplicate_wake_cannot_start_same_canonical_attempt(self):
        from types import SimpleNamespace
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []
        errors = []

        def worker(owner, task, deps):
            calls.append(task['id'])
            started.set()
            self.assertTrue(release.wait(5))
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified once',
                'source': DATA['url'], 'source_chars': 200,
            })

        offer = self.offers()[0]
        def first_run():
            try:
                canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=OWNER), offer,
                )
            except Exception as exc:
                errors.append(exc)

        with patch.object(task_agents, 'worker', side_effect=worker), \
             patch.object(untrusted_flow, 'observe'):
            thread = threading.Thread(target=first_run)
            thread.start()
            try:
                self.assertTrue(started.wait(8))
                with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
                    canonical_scheduler_dispatch.execute_offer(
                        SimpleNamespace(slug=OWNER), offer,
                    )
            finally:
                release.set()
                thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors, repr(errors))
        self.assertEqual(calls, ['left'])

    def test_cancellation_rejects_old_worker_result_without_journal_write(self):
        from types import SimpleNamespace
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        errors = []

        def worker(owner, task, deps):
            started.set()
            self.assertTrue(release.wait(5))
            return task_results.seal('research', {
                'state': 'done', 'text': 'Late result',
                'source': DATA['url'], 'source_chars': 200,
            })

        offer = self.offers()[0]
        def run():
            try:
                canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=OWNER), offer,
                )
            except Exception as exc:
                errors.append(exc)

        with patch.object(task_agents, 'worker', side_effect=worker), \
             patch.object(untrusted_flow, 'observe'):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(8))
                state = goal_state_store.load(self.path)
                cancelled = core_state_reducer.apply(state, {
                    'op': 'set_state', 'state': 'cancelled',
                    'reason_code': 'TEST_USER_CANCEL',
                    'expected_version': state['version'],
                })
                goal_state_store.compare_and_swap(
                    self.path, expected_version=state['version'],
                    next_state=cancelled,
                )
                record_before = self.record_path.read_bytes()
            finally:
                release.set()
                thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors, 'Cancelled worker may not succeed')
        self.assertEqual(record_before, self.record_path.read_bytes())
        saved = goal_state_store.load(self.path)
        self.assertEqual(saved['state'], 'cancelled')
        self.assertFalse(any(row.get('kind') == 'worker_result'
                             for row in saved['evidence']))

    def test_scheduler_stop_during_running_research_rejects_late_core_cas(self):
        """Cooperative shutdown does not accept a stale provider success."""
        from types import SimpleNamespace

        entered = threading.Event()
        release = threading.Event()
        stop = threading.Event()
        self.addCleanup(release.set)
        failures = []

        def worker(owner, task, deps):
            self.assertEqual(owner, OWNER)
            entered.set()
            self.assertTrue(release.wait(5))
            return task_results.seal('research', {
                'state': 'done', 'text': 'Arrived after scheduler stopped',
                'source': DATA['url'], 'source_chars': 200,
            })

        offer = self.offers()[0]

        def run():
            try:
                canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=OWNER), offer, stop_event=stop,
                )
            except Exception as exc:
                failures.append(exc)

        with patch.object(task_agents, 'worker', side_effect=worker), \\
             patch.object(untrusted_flow, 'observe'):
            thread = threading.Thread(target=run, name='stop-fence-test')
            thread.start()
            try:
                self.assertTrue(entered.wait(8))
                stop.set()
            finally:
                release.set()
                thread.join(8)

        self.assertFalse(thread.is_alive())
        self.assertTrue(failures, 'A late worker must not report success.')
        self.assertTrue(any('Scheduler stopped' in str(exc) for exc in failures))
        saved = goal_state_store.load(self.path)
        self.assertEqual(saved['state'], 'pending')
        self.assertFalse(any(
            row.get('kind') == 'worker_result' for row in saved['evidence']
        ))
        journal = execution_record.load(self.owner_root, OWNER, JOB)
        self.assertEqual(journal['steps'][0]['state'], 'failed')
        self.assertEqual(journal['outputs']['left']['state'], 'failed')
        self.assertEqual([o.selection.node_id for o in self.offers()], ['right'])

    def test_scheduler_stop_before_claim_leaves_exact_record_unchanged(self):
        from types import SimpleNamespace
        stop = threading.Event()
        stop.set()
        initial = self.record_path.read_bytes()
        result = canonical_scheduler_dispatch.execute_offer(
            SimpleNamespace(slug=OWNER), self.offers()[0],
            stop_event=stop,
        )
        self.assertFalse(result)
        self.assertEqual(self.record_path.read_bytes(), initial)

    def test_scheduler_stop_scope_is_thread_local_and_cleared_on_error(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(RuntimeError, 'Scheduler stopped'):
            with runtime_worker_result.scheduler_stop_scope(stop):
                self.fail('A stopped Scheduler may not enter a worker.')
        # An unrelated standalone legacy/read-only worker has no Scheduler
        # stop token; the failed scope does not permanently contaminate it.
        runtime_worker_result.require_scheduler_active()

    def test_discovery_requires_published_running_records(self):
        found = canonical_scheduler_dispatch.discover(OWNER)
        self.assertEqual([o.selection.node_id for o in found], ['left', 'right'])
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['state'] = 'cancelled'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.assertEqual(canonical_scheduler_dispatch.discover(OWNER), ())

    def test_actual_engine_scheduler_runs_disk_backed_dag_without_sqlite_queue(self):
        """End-to-end: one Scheduler loop, two overlapping roots, verified child.

        Uses the real specialist and Core/ExecutionRecord persistence paths;
        only external research transport and the wall-clock tick are synthetic.
        """
        from types import SimpleNamespace
        from modules import llm, outbox, privacy, service_store, source_watch, task_queue
        from modules.voice_core import VoiceCatalog, VoiceCoordinator, VoiceSpec, SpeechRequest

        state = goal_state_store.load(self.path)
        nodes = [node('left'), node('right'), node('child', ('left', 'right'))]
        updated = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_SCHEDULER_DAG',
            'expected_version': state['version'],
            'plan': {'plan_version': 2, 'nodes': nodes},
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=state['version'], next_state=updated,
        )
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][-1]['depends'] = ['left', 'right']
        release_guard.atomic(self.record_path, execution_record.encode(job))

        sqlite = self.store / 'sqlite'
        sqlite.mkdir()
        # Alice deliberately has NO queue SQLite; Bob's source-watch DB
        # proves the existing scheduler poll continues while Alice works.
        (sqlite / 'bob.sqlite3').touch()
        barrier = threading.Barrier(2, timeout=9)
        finished = threading.Event()
        root_entered = threading.Event()
        poll_while_busy = threading.Event()
        voice_played = threading.Event()
        observed = []
        lock = threading.Lock()

        class FastStop:
            def __init__(self):
                self.event = threading.Event()
            def wait(self, _):
                return self.event.wait(.01)
            def is_set(self):
                return self.event.is_set()
            def set(self):
                self.event.set()

        stop = FastStop()
        self.addCleanup(stop.set)

        def worker(owner, task, deps):
            self.assertEqual(owner, OWNER)
            self.assertEqual(llm._key_context.get(), OWNER)
            if task['id'] in ('left', 'right'):
                root_entered.set()
                barrier.wait()
                self.assertTrue(
                    voice_played.wait(7), 'Voice playback blocked by canonical worker',
                )
                # Prove the central Scheduler polls Bob DURING both active
                # Alice workers, not after their results have been accepted.
                self.assertTrue(
                    poll_while_busy.wait(7), 'Owner source poll blocked by worker',
                )
            else:
                self.assertEqual(set(deps), {'left', 'right'})
                finished.set()
            with lock:
                observed.append(task['id'])
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified ' + task['id'],
                'source': DATA['url'], 'source_chars': 200,
            })

        def poll(owner, notify):
            if root_entered.is_set():
                poll_while_busy.set()

        with ExitStack() as stack:
            # Synthetic playback verifies VoiceCoordinator can still speak
            # while the actual Scheduler workers are blocked in their provider.
            # This is NOT a claim of real audible Windows device acceptance.
            def play(audio, cancel, on_start):
                on_start()
                voice_played.set()

            coordinator = VoiceCoordinator(
                VoiceCatalog((VoiceSpec('tr_erkek', 'Test voice', 'piper', 'test.onnx'),)),
                lambda spec, text, cancel: b'audio',
                play,
                lambda receipt: None,
            )
            stack.callback(coordinator.close)
            for module, attribute, value in (
                (service_store, 'ROOT', sqlite),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_LAST_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (task_queue, 'tick', lambda *_: None),
                (outbox, 'has_pending', lambda *_: False),
                (privacy, 'blocked', lambda *_: None),
                (source_watch, 'poll', poll),
                (untrusted_flow, 'observe', lambda *_: None),
                (task_agents, 'worker', worker),
            ):
                stack.enter_context(patch.object(module, attribute, value))
            task_queue.start(
                stop,
                allowed_owners=lambda: {OWNER, 'bob'},
                canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
            )
            try:
                self.assertTrue(root_entered.wait(8), 'No canonical worker started')
                self.assertTrue(coordinator.submit(SpeechRequest(
                    owner=OWNER, request_id='speak-while-running',
                    voice_id='tr_erkek', text='Arka planda devam ediyorum',
                )))
                self.assertTrue(voice_played.wait(5), 'Voice playback did not start')
                self.assertTrue(finished.wait(15), 'Dependent node was not dispatched')
                self.assertTrue(poll_while_busy.is_set(), 'Scheduler poll blocked on worker')
                for _ in range(200):
                    saved = execution_record.load(self.owner_root, OWNER, JOB)
                    if saved['steps'][-1]['state'] == 'done':
                        break
                    threading.Event().wait(.01)
                saved = execution_record.load(self.owner_root, OWNER, JOB)
                self.assertEqual(set(saved['outputs']), {'left', 'right', 'child'})
                self.assertTrue(all(s['state'] == 'done' for s in saved['steps']))
                self.assertEqual(set(observed), {'left', 'right', 'child'})
            finally:
                stop.set()
                barrier.abort()
                task_queue._THREAD.join(8)
                for thread in tuple(task_queue._CANONICAL_WORKERS.values()):
                    thread.join(8)
                self.assertFalse(any(
                    thread.is_alive() for thread in task_queue._CANONICAL_WORKERS.values()
                ), 'Canonical worker leaked after scheduler shutdown')


    def test_discovery_rotates_past_eight_unusable_journals(self):
        # Sorted-first-eight scans starved this valid newer canonical goal
        # forever if eight old journals were corrupt or terminal.
        for number in range(1, 10):
            path = self.owner_root / f'{number:016x}.execution.json'
            path.write_text('invalid legacy record', encoding='utf-8')
        with patch.object(canonical_scheduler_dispatch, '_SCAN_CURSOR', {}):
            self.assertEqual(canonical_scheduler_dispatch.discover(OWNER), ())
            second = canonical_scheduler_dispatch.discover(OWNER)
        self.assertEqual(
            [offer.selection.node_id for offer in second],
            ['left', 'right'],
        )

    def test_two_independent_goals_same_owner_overlap_on_real_scheduler(self):
        """Read-only canonical goals run concurrently without legacy _ACTIVE.

        One existing Scheduler and two separate on-disk GoalState/records;
        only the external research provider transport is synthetic.
        """
        from types import SimpleNamespace
        from modules import service_store, task_queue

        first = goal_state_store.load(self.path)
        one_node = [node('left')]
        updated = core_state_reducer.apply(first, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_INDEPENDENT_GOAL',
            'expected_version': first['version'],
            'plan': {'plan_version': 2, 'nodes': one_node},
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=first['version'], next_state=updated,
        )
        first_record = execution_record.load(self.owner_root, OWNER, JOB)
        first_record['steps'] = first_record['steps'][:1]
        release_guard.atomic(self.record_path, execution_record.encode(first_record))

        second_id = 'fedcba9876543210'
        second_node = node('other')
        second_state = goal_state.new(
            owner=OWNER, job_id=second_id, goal='Read a different source',
            authority='canonical',
        )
        second_state = core_state_reducer.apply(second_state, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_INDEPENDENT_GOAL',
            'expected_version': second_state['version'],
            'plan': {'plan_version': 1, 'nodes': [second_node]},
        })
        goal_state_store.create(
            self.owner_root / (second_id + '.goalstate.json'), second_state,
        )
        second_record = {
            'id': second_id, 'owner': OWNER,
            'request': 'Read a different source', 'state': 'running',
            'goals': [], 'outputs': {},
            'steps': [{
                'id': 'other', 'tool': 'research', 'input': dict(DATA),
                'depends': [], 'state': 'queued',
            }],
        }
        release_guard.atomic(
            execution_record.path_for(self.owner_root, second_id),
            execution_record.encode(second_record),
        )

        class RapidStop:
            def __init__(self):
                self.event = threading.Event()
            def wait(self, _):
                return self.event.wait(.015)
            def is_set(self):
                return self.event.is_set()
            def set(self):
                self.event.set()

        stop = RapidStop()
        barrier = threading.Barrier(2, timeout=12)
        observed = []
        lock = threading.Lock()

        def research_worker(owner, task, deps):
            self.assertEqual(owner, OWNER)
            self.assertEqual(deps, {})
            barrier.wait()
            with lock:
                observed.append(task['id'])
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified ' + task['id'],
                'source': DATA['url'], 'source_chars': 200,
            })

        with ExitStack() as stack:
            for module, attribute, value in (
                (service_store, 'ROOT', self.store / 'missing-sqlite'),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_LAST_ADMITTED', {}),
                (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (task_agents, 'worker', research_worker),
                (untrusted_flow, 'observe', lambda *_: None),
            ):
                stack.enter_context(patch.object(module, attribute, value))
            task_queue.start(
                stop,
                allowed_owners=lambda: {OWNER},
                canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
            )
            try:
                for _ in range(700):
                    one = execution_record.load(self.owner_root, OWNER, JOB)
                    two = execution_record.load(self.owner_root, OWNER, second_id)
                    if ('left' in one['outputs'] and 'other' in two['outputs']):
                        break
                    threading.Event().wait(.02)
                self.assertEqual(set(observed), {'left', 'other'})
                self.assertEqual(one['steps'][0]['state'], 'done')
                self.assertEqual(two['steps'][0]['state'], 'done')
                self.assertEqual(
                    {row['step_id'] for row in
                     goal_state_store.load(self.path)['evidence']
                     if row.get('kind') == 'worker_result'},
                    {'left'},
                )
                self.assertEqual(
                    {row['step_id'] for row in goal_state_store.load(
                        self.owner_root / (second_id + '.goalstate.json')
                    )['evidence'] if row.get('kind') == 'worker_result'},
                    {'other'},
                )
            finally:
                stop.set()
                barrier.abort()
                task_queue._THREAD.join(10)
                for thread in tuple(task_queue._CANONICAL_WORKERS.values()):
                    thread.join(10)
                self.assertFalse(any(
                    thread.is_alive()
                    for thread in task_queue._CANONICAL_WORKERS.values()
                ), 'Canonical goal worker leaked after stop')

    def test_registered_canonical_owner_gets_fair_next_slot(self):
        """An unserved fourth owner must beat a repeatedly runnable first owner.

        Workers and the tick clock are synthetic; actual Scheduler thread
        admission and owner ordering are exercised without provider calls.
        """
        from types import SimpleNamespace
        from modules import service_store, task_queue

        class RapidStop:
            def __init__(self):
                self.event = threading.Event()

            def wait(self, _seconds):
                return self.event.wait(.015)

            def is_set(self):
                return self.event.is_set()

            def set(self):
                self.event.set()

        stop = RapidStop()
        release_first = threading.Event()
        first_finished = threading.Event()
        fourth_polled = threading.Event()
        fourth_admitted = threading.Event()
        started = []
        lock = threading.Lock()
        first_owner_runs = [0]

        def resolver(owner):
            if owner == 'donna':
                fourth_polled.set()
            return SimpleNamespace(slug=owner)

        def discover(owner, **_):
            return (SimpleNamespace(
                selection=SimpleNamespace(
                    owner=owner, job_id='0000000000000001', node_id='only',
                ),
                attempt=1,
            ),)

        def execute(profile, offer, *, stop_event=None):
            owner = offer.selection.owner
            self.assertEqual(profile.slug, owner)
            with lock:
                started.append(owner)
                if owner == 'alice':
                    first_owner_runs[0] += 1
                    run = first_owner_runs[0]
                else:
                    run = 0
            if owner == 'alice' and run == 1:
                release_first.wait(10)
                first_finished.set()
                return True
            if owner == 'donna':
                fourth_admitted.set()
            stop.event.wait(10)
            return True

        with ExitStack() as stack:
            for module, name, replacement in (
                (service_store, 'ROOT', self.store / 'missing-sqlite'),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_LAST_ADMITTED', {}),
                (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (canonical_scheduler_dispatch, 'discover', discover),
                (canonical_scheduler_dispatch, 'execute_offer', execute),
            ):
                stack.enter_context(patch.object(module, name, replacement))
            task_queue.start(
                stop,
                allowed_owners=lambda: {'alice', 'bob', 'charlie', 'donna'},
                canonical_profile_resolver=resolver,
            )
            try:
                self.assertTrue(fourth_polled.wait(10), 'Fourth owner not polled')
                # Three blocked workers filled the global pool on first poll.
                self.assertFalse(fourth_admitted.is_set())
                release_first.set()
                self.assertTrue(first_finished.wait(10), 'First slot not released')
                self.assertTrue(
                    fourth_admitted.wait(10),
                    'Repeated first owner starved an unserved owner',
                )
                with lock:
                    self.assertIn('donna', started)
            finally:
                stop.set()
                release_first.set()
                task_queue._THREAD.join(10)
                for worker in tuple(task_queue._CANONICAL_WORKERS.values()):
                    worker.join(10)
                self.assertFalse(any(
                    worker.is_alive()
                    for worker in task_queue._CANONICAL_WORKERS.values()
                ), 'Canonical worker remained after scheduler shutdown')


    def plan_only_roots(self, *names):
        current = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(current, {
            'op': 'set_goal_plan', 'expected_version': current['version'],
            'reason_code': 'TEST_CERTIFICATION',
            'plan': {'plan_version': 2, 'nodes': [node(name) for name in names]},
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=current['version'], next_state=updated,
        )
        journal = execution_record.load(self.owner_root, OWNER, JOB)
        journal['steps'] = [
            next(row for row in journal['steps'] if row['id'] == name)
            for name in names
        ]
        release_guard.atomic(
            self.record_path, execution_record.encode(journal),
        )

    def test_full_plan_proof_requires_every_projected_accepted_root(self):
        self.plan_only_roots('left', 'right')
        with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
            canonical_plan_evidence.certify_projected_plan(OWNER, JOB)
        result_left = self.accept('left')
        with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
            canonical_plan_evidence.certify_projected_plan(OWNER, JOB)
        canonical_output_projection.project_accepted(
            OWNER, JOB, 'left', result_left,
        )
        with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
            canonical_plan_evidence.certify_projected_plan(OWNER, JOB)

        result_right = self.accept('right')
        canonical_output_projection.project_accepted(
            OWNER, JOB, 'right', result_right,
        )
        with patch.object(goal_tools, 'verify', return_value=True) as verified:
            proof = canonical_plan_evidence.certify_projected_plan(OWNER, JOB)
        self.assertEqual(proof.owner, OWNER)
        self.assertEqual(proof.job_id, JOB)
        self.assertEqual(proof.plan_version, 2)
        self.assertEqual(
            {ident for ident, digest in proof.output_digests},
            {'left', 'right'},
        )
        self.assertEqual(verified.call_count, 2)
        # A completed DAG is not permission to declare a user's goal done.
        self.assertEqual(goal_state_store.load(self.path)['state'], 'pending')
        self.assertEqual(
            execution_record.load(self.owner_root, OWNER, JOB)['state'],
            'running',
        )

    def test_full_plan_proof_rejects_tampered_projected_bytes(self):
        self.plan_only_roots('left')
        clean = self.accept('left')
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', clean)
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['outputs']['left']['text'] = 'Modified after accepted Core CAS'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        with patch.object(goal_tools, 'verify', return_value=True) as verified:
            with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
                canonical_plan_evidence.certify_projected_plan(OWNER, JOB)
            verified.assert_not_called()

    def test_full_plan_proof_rejects_domain_verifier_failure(self):
        self.plan_only_roots('left')
        clean = self.accept('left')
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', clean)
        with patch.object(goal_tools, 'verify', return_value=False):
            with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
                canonical_plan_evidence.certify_projected_plan(OWNER, JOB)

    def test_full_plan_proof_rejects_user_intent_change_after_projection(self):
        self.plan_only_roots('left')
        clean = self.accept('left')
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', clean)
        current = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(current, {
            'op': 'mutate_goal_intent', 'operation': 'revise',
            'text': 'New user request', 'priority': None,
            'expected_version': current['version'], 'reason_code': 'USER_REVISE',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=current['version'], next_state=updated,
        )
        with patch.object(goal_tools, 'verify', return_value=True):
            with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
                canonical_plan_evidence.certify_projected_plan(OWNER, JOB)

    def test_full_plan_proof_rechecks_cas_after_slow_domain_verification(self):
        self.plan_only_roots('left')
        clean = self.accept('left')
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', clean)

        def change_during_verify(output, owner):
            self.assertEqual(owner, OWNER)
            old = goal_state_store.load(self.path)
            changed = core_state_reducer.apply(old, {
                'op': 'mutate_goal_intent', 'operation': 'prioritize',
                'priority': 3, 'text': None,
                'expected_version': old['version'], 'reason_code': 'USER_PRIORITY',
            })
            goal_state_store.compare_and_swap(
                self.path, expected_version=old['version'],
                next_state=changed,
            )
            return True

        with patch.object(goal_tools, 'verify', side_effect=change_during_verify):
            with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
                canonical_plan_evidence.certify_projected_plan(OWNER, JOB)

    def test_full_plan_proof_rejects_foreign_owner(self):
        self.plan_only_roots('left')
        with self.assertRaises(canonical_plan_evidence.PlanEvidenceError):
            canonical_plan_evidence.certify_projected_plan('bob', JOB)


if __name__ == '__main__':
    unittest.main()
