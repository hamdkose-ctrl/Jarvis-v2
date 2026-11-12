"""BRAIN-07 Scheduler readiness offer tests; no real worker or second loop.

Real canonical CAS, exact ExecutionRecord bytes and predecessor-proof
projection are used; external providers and desktop remain untouched.
"""
from __future__ import annotations

import copy
import sys
import tempfile
import threading
import traceback
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import release_guard
from modules import (
    canonical_output_projection, canonical_plan_evidence, canonical_restart_audit,
    canonical_scheduler_dispatch,
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

    def test_scheduler_discovery_reads_both_snapshots_inside_existing_job_lock(self):
        """Deterministic regression: a Windows reader may not race os.replace."""
        from modules import goal_job_control
        expected = str((self.owner_root / (JOB + '.control')).absolute())
        read_state = goal_state_store.load
        read_record = execution_record.load
        observed = []

        def checked_state(path):
            self.assertIn(expected, getattr(goal_job_control._LOCAL, 'held', set()),
                          'Scheduler opened GoalState outside the shared OS job lock')
            observed.append('Core')
            return read_state(path)

        def checked_record(root, owner, job_id):
            self.assertIn(expected, getattr(goal_job_control._LOCAL, 'held', set()),
                          'Scheduler opened ExecutionRecord outside the shared OS job lock')
            observed.append('ExecutionRecord')
            return read_record(root, owner, job_id)

        with patch.object(goal_state_store, 'load', side_effect=checked_state), \
             patch.object(execution_record, 'load', side_effect=checked_record):
            offers = self.offers()
        self.assertEqual(observed[:2], ['Core', 'ExecutionRecord'])
        self.assertEqual([o.selection.node_id for o in offers], ['left', 'right'])

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

    def test_completion_recovery_never_wakes_unknown_or_unprojected_attempt(self):
        # No evidence means no completion callback, even on a fresh Scheduler.
        self.assertEqual(canonical_scheduler_dispatch.recoverable_completions(
            OWNER,
        ), ())
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.assertEqual(canonical_restart_audit.inspect(OWNER, JOB).nodes[0].status,
                         'started_unknown')
        self.assertEqual(canonical_scheduler_dispatch.recoverable_completions(
            OWNER,
        ), ())
        # Core accepted evidence without an intact projected output is not
        # proof of safe global completion, even if another node is queued.
        self.accept('left')
        self.assertEqual(canonical_restart_audit.inspect(OWNER, JOB).nodes[0].status,
                         'accepted_unprojected')
        self.assertEqual(canonical_scheduler_dispatch.recoverable_completions(
            OWNER,
        ), ())

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

    def test_altered_execution_request_never_admits_a_worker_or_restart_proof(self):
        from types import SimpleNamespace

        previously_offered = self.offers()[0]
        record = execution_record.load(self.owner_root, OWNER, JOB)
        record['request'] = 'Change the task without changing the Core goal'
        release_guard.atomic(self.record_path, execution_record.encode(record))
        before = self.path.read_bytes(), self.record_path.read_bytes()

        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            self.offers()
        self.assertEqual(canonical_scheduler_dispatch.discover(OWNER), ())
        with self.assertRaises(canonical_restart_audit.RestartAuditError):
            canonical_restart_audit.inspect(OWNER, JOB)

        # A previously offered candidate cannot cross the claim boundary.
        with patch('modules.specialist_orchestrator.execute_step') as worker:
            with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
                canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=OWNER), previously_offered,
                )
            worker.assert_not_called()

        status = goal_executor.status_summary(record)
        self.assertIn('kanıtı şu anda doğrulanamıyor', status)
        self.assertNotIn('Core kabulü ve kayıtlı çıktı eşleşiyor', status)
        self.assertEqual(before, (self.path.read_bytes(), self.record_path.read_bytes()))

    def test_outer_request_whitespace_remains_compatible_with_canonical_goal(self):
        # GoalState.new normalizes leading/trailing spaces, not internal text.
        record = execution_record.load(self.owner_root, OWNER, JOB)
        record['request'] = '  Read two sources  '
        release_guard.atomic(self.record_path, execution_record.encode(record))
        self.assertEqual([offer.selection.node_id for offer in self.offers()],
                         ['left', 'right'])
        self.assertEqual(canonical_restart_audit.inspect(OWNER, JOB).nodes[0].status,
                         'queued_unstarted')

    def test_identity_preflight_failure_after_claim_is_recorded_without_retry(self):
        from types import SimpleNamespace

        offer = self.offers()[0]
        with patch.object(goal_executor, '_identity',
                          side_effect=ValueError('identity preflight refused')), \
             patch('modules.specialist_orchestrator.execute_step') as worker:
            with self.assertRaisesRegex(ValueError, 'identity preflight refused'):
                canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=OWNER), offer,
                )
            worker.assert_not_called()
        journal = execution_record.load(self.owner_root, OWNER, JOB)
        self.assertEqual(journal['steps'][0]['state'], 'failed')
        self.assertTrue(journal['steps'][0]['started'])
        self.assertEqual(journal['steps'][0]['attempts'], 1)
        self.assertEqual(journal['outputs']['left']['state'], 'failed')
        self.assertEqual(canonical_restart_audit.inspect(OWNER, JOB).nodes[0].status,
                         'failed_unaccepted')
        self.assertEqual([item.selection.node_id for item in self.offers()],
                         ['right'])

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
                # Preserve the exact Windows failure location on the next PC run.
                errors.append(''.join(traceback.format_exception(exc)))

        from modules import goal_job_control
        with patch.object(task_agents, 'worker', side_effect=safe_worker), \
             patch.object(untrusted_flow, 'observe'):
            left = self.offers()[0]
            first = threading.Thread(target=dispatch, args=(left,))
            first.start()
            try:
                for _ in range(300):
                    # Match the production per-job lock: an unlocked Windows
                    # read can keep a handle open across atomic os.replace.
                    # Never hold this lock while waiting on the worker barrier.
                    with goal_job_control.locked(self.owner_root, JOB):
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

        with patch.object(task_agents, 'worker', side_effect=worker), \
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

    def test_canonical_worker_deadline_token_distinguishes_stop_and_expiry(self):
        now = [10.0]
        parent = threading.Event()
        deadline = runtime_worker_result.CanonicalWorkerDeadline(
            parent, 2, clock=lambda: now[0],
        )
        self.assertFalse(deadline.is_set())
        self.assertIsNone(deadline.stop_reason())
        with runtime_worker_result.scheduler_stop_scope(deadline):
            runtime_worker_result.require_scheduler_active()
            now[0] = 12.0
            self.assertEqual(deadline.stop_reason(), 'worker_deadline')
            with self.assertRaises(
                runtime_worker_result.CanonicalWorkerDeadlineExceeded,
            ):
                runtime_worker_result.require_scheduler_active()
        # Scope resets on failure; no global kill switch leaks to foreground.
        runtime_worker_result.require_scheduler_active()
        parent.set()
        self.assertEqual(deadline.stop_reason(), 'scheduler_stopped')
        with self.assertRaisesRegex(RuntimeError, 'Scheduler stopped'):
            with runtime_worker_result.scheduler_stop_scope(deadline):
                self.fail('A stopped Scheduler may not start another worker.')
        with self.assertRaises(ValueError):
            runtime_worker_result.CanonicalWorkerDeadline(parent, 0)
        with self.assertRaises(ValueError):
            runtime_worker_result.CanonicalWorkerDeadline(parent, float('nan'))
        with self.assertRaises(ValueError):
            runtime_worker_result.CanonicalWorkerDeadline(object(), 10)

    def test_scheduler_deadline_propagates_to_request_checkpoints_and_resets(self):
        from modules import requests_state
        clock = [50.0]
        stopped = threading.Event()
        deadline = runtime_worker_result.CanonicalWorkerDeadline(
            stopped, 2, clock=lambda: clock[0],
        )
        # No current request ID is required by the background worker;
        # the request checkpoints must still enforce the Scheduler token.
        with runtime_worker_result.scheduler_stop_scope(deadline):
            requests_state.check()
            clock[0] = 52.0
            with self.assertRaises(
                runtime_worker_result.CanonicalWorkerDeadlineExceeded,
            ):
                requests_state.check()
            # A model/provider worker inherits this same ContextVar even
            # when its body is run under a copied thread context.
            import contextvars
            ctx = contextvars.copy_context()
            with self.assertRaises(
                runtime_worker_result.CanonicalWorkerDeadlineExceeded,
            ):
                ctx.run(requests_state.check)
        # An unrelated foreground request is not affected by a finished
        # Scheduler attempt, and a newly started attempt keeps its own token.
        requests_state.check()
        stopped.set()
        with self.assertRaisesRegex(RuntimeError, 'Scheduler stopped'):
            with runtime_worker_result.scheduler_stop_scope(deadline):
                requests_state.check()
        requests_state.check()

    def test_deadline_elapsed_during_prepare_never_invokes_provider(self):
        now = [10.0]
        stop = threading.Event()
        deadline = runtime_worker_result.CanonicalWorkerDeadline(
            stop, 3, clock=lambda: now[0],
        )
        with patch.object(goal_tools, 'execute') as provider:
            with runtime_worker_result.scheduler_stop_scope(deadline):
                # The initial Scheduler check passed; slow preparation then
                # exhausted the deadline. This is the last pre-provider gate.
                now[0] = 14.0
                with self.assertRaises(
                    runtime_worker_result.CanonicalWorkerDeadlineExceeded,
                ):
                    worker_result_hook.execute(
                        None, 'research', dict(DATA), {}, {'owner': OWNER},
                    )
            provider.assert_not_called()

    def test_real_scheduler_worker_deadline_fences_late_core_cas_no_replay(self):
        """A provider returning after a deadline never becomes Core success.

        This executes the actual canonical dispatcher, specialist, lease,
        WorkerResult acceptance and ExecutionRecord path. Only the network
        provider is synthetic and the worker deadline clock is controlled.
        """
        from types import SimpleNamespace

        entered = threading.Event()
        release = threading.Event()
        parent = threading.Event()
        now = [100.0]
        deadline = runtime_worker_result.CanonicalWorkerDeadline(
            parent, 10, clock=lambda: now[0],
        )
        self.addCleanup(release.set)
        errors = []

        def worker(owner, task, dependencies):
            self.assertEqual(owner, OWNER)
            self.assertEqual(task['id'], 'left')
            self.assertEqual(dependencies, {})
            entered.set()
            self.assertTrue(release.wait(6), 'Provider was never released')
            return task_results.seal('research', {
                'state': 'done', 'text': 'Late source was read',
                'source': DATA['url'], 'source_chars': 200,
            })

        offer = self.offers()[0]

        def invoke():
            try:
                canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=OWNER), offer, stop_event=deadline,
                )
            except Exception as exc:
                errors.append(exc)

        with patch.object(task_agents, 'worker', side_effect=worker), \
             patch.object(untrusted_flow, 'observe'):
            thread = threading.Thread(target=invoke, name='deadline-fence-test')
            thread.start()
            try:
                self.assertTrue(entered.wait(8), 'Canonical read did not start')
                # Timeout cannot imply that an in-flight read never reached
                # its provider. We only fence a late accepted result.
                now[0] = 111.0
                self.assertEqual(deadline.stop_reason(), 'worker_deadline')
                self.assertTrue(thread.is_alive())
            finally:
                release.set()
                thread.join(8)

        self.assertFalse(thread.is_alive(), 'Worker thread leaked')
        self.assertTrue(any(isinstance(
            exc, runtime_worker_result.CanonicalWorkerDeadlineExceeded,
        ) for exc in errors), repr(errors))
        canonical = goal_state_store.load(self.path)
        self.assertEqual(canonical['state'], 'pending')
        self.assertFalse(any(
            row.get('kind') == 'worker_result'
            for row in canonical['evidence']
        ))
        journal = execution_record.load(self.owner_root, OWNER, JOB)
        self.assertEqual(journal['steps'][0]['state'], 'failed')
        self.assertEqual(
            journal['outputs']['left']['reason_code'],
            'CANONICAL_WORKER_DEADLINE_UNACCEPTED',
        )
        self.assertIn('never retry automatically',
                      journal['outputs']['left']['text'])
        self.assertEqual(
            canonical_restart_audit.inspect(OWNER, JOB).nodes[0].status,
            'failed_unaccepted',
        )
        self.assertEqual(
            [item.selection.node_id for item in self.offers()], ['right'],
        )

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

    def test_live_canonical_cancel_fences_next_provider_step_before_worker_result(self):
        from modules import requests_state
        offer = self.offers()[0]
        before = self.path.read_bytes()
        with runtime_worker_result.scheduler_stop_scope(None, selection=offer.selection):
            requests_state.check()
            current = goal_state_store.load(self.path)
            cancelled = core_state_reducer.apply(current, {
                'op': 'set_state', 'state': 'cancelled',
                'reason_code': 'TEST_OWNER_CANCEL',
                'expected_version': current['version'],
            })
            goal_state_store.compare_and_swap(
                self.path, expected_version=current['version'], next_state=cancelled,
            )
            with self.assertRaises(runtime_worker_result.CanonicalWorkerRevoked):
                requests_state.check()
        self.assertNotEqual(before, self.path.read_bytes())
        self.assertEqual(goal_state_store.load(self.path)['state'], 'cancelled')
        runtime_worker_result.require_scheduler_active()

    def test_live_canonical_plan_edit_fences_next_provider_step(self):
        from modules import requests_state
        offer = self.offers()[0]
        with runtime_worker_result.scheduler_stop_scope(None, selection=offer.selection):
            current = goal_state_store.load(self.path)
            updated = core_state_reducer.apply(current, {
                'op': 'set_goal_plan', 'reason_code': 'TEST_OWNER_REPLAN',
                'expected_version': current['version'],
                'plan': {'plan_version': 2, 'nodes': self.nodes},
            })
            goal_state_store.compare_and_swap(
                self.path, expected_version=current['version'], next_state=updated,
            )
            with self.assertRaises(runtime_worker_result.CanonicalWorkerRevoked):
                requests_state.check()
        self.assertFalse(any(row.get('kind') == 'worker_result'
                             for row in goal_state_store.load(self.path)['evidence']))

    def test_independent_accepted_root_does_not_revoke_other_running_root(self):
        from modules import requests_state
        second = self.offers()[1]
        with runtime_worker_result.scheduler_stop_scope(None, selection=second.selection):
            self.accept('left')
            # Only a verified WorkerResult CAS is a permissible version advance;
            # this does not rebase a user edit, terminal state or changed plan.
            requests_state.check()
            runtime_worker_result.require_scheduler_active()

    def test_canonical_scope_cannot_accept_untyped_or_forged_selection(self):
        with self.assertRaises(ValueError):
            with runtime_worker_result.scheduler_stop_scope(None, selection={'owner': OWNER}):
                self.fail('Untrusted scheduler selection admitted')
        runtime_worker_result.require_scheduler_active()

    def test_goal_status_uses_existing_read_only_canonical_restart_proof(self):
        before = self.path.read_bytes(), self.record_path.read_bytes()
        job = execution_record.load(self.owner_root, OWNER, JOB)
        result = goal_executor.status_summary(job)
        self.assertIn('Canonical DAG kanıtı: 0/3', result)
        self.assertIn('Henüz başlamamış: 3 adım', result)
        self.assertEqual(before, (self.path.read_bytes(), self.record_path.read_bytes()))

    def test_goal_status_command_routes_through_existing_goal_handler(self):
        from types import SimpleNamespace
        from modules import brain_entry

        job = execution_record.load(self.owner_root, OWNER, JOB)
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        with patch.object(brain_entry, 'allow_legacy_goal_control', return_value=True), \
             patch.object(goal_executor, 'latest', return_value=job):
            answer = goal_executor.handle(runtime, 'hedef durumu')
        self.assertIn('Canonical DAG kanıtı: 0/3', answer)
        self.assertIn('Henüz başlamamış: 3 adım.', answer)

    def test_goal_status_started_unknown_never_suggests_auto_retry(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        status = goal_executor.status_summary(
            execution_record.load(self.owner_root, OWNER, JOB),
        )
        self.assertIn('Başlatılmış, sonuç kanıtı henüz yok: 1', status)
        self.assertIn('hâlâ çalışıyor olabilir', status)
        self.assertIn('otomatik tekrar yapılmaz', status)

    def test_goal_status_core_accepted_unprojected_is_not_goal_done(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.accept('left')
        status = goal_executor.status_summary(
            execution_record.load(self.owner_root, OWNER, JOB),
        )
        self.assertIn('Core kabulü var, kayıtlı çıktı eksik: 1', status)
        self.assertNotIn('Canonical DAG kanıtı: 1/3', status)
        self.assertEqual(goal_state_store.load(self.path)['state'], 'pending')

    def test_goal_status_accepted_projected_then_tampered_fails_closed(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        output = self.accept('left')
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', output)
        status = goal_executor.status_summary(
            execution_record.load(self.owner_root, OWNER, JOB),
        )
        self.assertIn('Canonical DAG kanıtı: 1/3', status)
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['outputs']['left']['text'] = 'altered after acceptance'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        status = goal_executor.status_summary(
            execution_record.load(self.owner_root, OWNER, JOB),
        )
        self.assertIn('Canonical DAG kanıtı şu anda doğrulanamıyor', status)
        self.assertNotIn('Canonical DAG kanıtı: 1/3', status)

    def test_goal_status_legacy_without_canonical_plan_unchanged(self):
        # The legacy status surface must not require a canonical sidecar or
        # invent a plan for existing user jobs.
        self.path.unlink()
        job = execution_record.load(self.owner_root, OWNER, JOB)
        status = goal_executor.status_summary(job)
        self.assertIn('Durum: çalışıyor', status)
        self.assertNotIn('Canonical DAG kanıtı', status)

    def test_restart_audit_queued_nodes_are_not_evidence_or_replayed(self):
        before_state = self.path.read_bytes()
        before_record = self.record_path.read_bytes()
        result = canonical_restart_audit.inspect(OWNER, JOB)
        self.assertEqual(
            [(n.node_id, n.status) for n in result.nodes],
            [('left', 'queued_unstarted'), ('right', 'queued_unstarted'),
             ('child', 'queued_unstarted')],
        )
        self.assertEqual(self.path.read_bytes(), before_state)
        self.assertEqual(self.record_path.read_bytes(), before_record)

    def test_restart_audit_started_without_core_success_is_unknown(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        before = self.record_path.read_bytes()
        result = canonical_restart_audit.inspect(OWNER, JOB)
        self.assertEqual(result.nodes[0].status, 'started_unknown')
        self.assertEqual(self.record_path.read_bytes(), before)
        self.assertEqual(
            [offer.selection.node_id for offer in self.offers()], ['right'],
        )

    def test_restart_audit_acceptance_without_projection_is_not_completion(self):
        self.accept('left')
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        before = self.path.read_bytes(), self.record_path.read_bytes()
        result = canonical_restart_audit.inspect(OWNER, JOB)
        self.assertEqual(result.nodes[0].status, 'accepted_unprojected')
        self.assertEqual(before, (self.path.read_bytes(), self.record_path.read_bytes()))
        self.assertEqual(goal_state_store.load(self.path)['state'], 'pending')

    def test_restart_audit_accepted_projection_requires_exact_core_hash(self):
        clean = self.accept('left')
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', clean)
        result = canonical_restart_audit.inspect(OWNER, JOB)
        self.assertEqual(result.nodes[0].status, 'accepted_projected')
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['outputs']['left']['text'] = 'changed after acceptance'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        with self.assertRaises(canonical_restart_audit.RestartAuditError):
            canonical_restart_audit.inspect(OWNER, JOB)

    def test_restart_audit_explicit_first_attempt_failure_never_retries(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='failed', started=True, attempts=1)
        job['outputs']['left'] = {
            'state': 'failed', 'text': 'unknown upstream receipt',
        }
        release_guard.atomic(self.record_path, execution_record.encode(job))
        result = canonical_restart_audit.inspect(OWNER, JOB)
        self.assertEqual(result.nodes[0].status, 'failed_unaccepted')
        self.assertEqual(
            [offer.selection.node_id for offer in self.offers()], ['right'],
        )

    def test_restart_audit_core_failed_attempt_requires_reconciliation(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0].update(state='running', started=True, attempts=1)
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.accept('left', state='failed')
        result = canonical_restart_audit.inspect(OWNER, JOB)
        self.assertEqual(result.nodes[0].status, 'failed_accepted')

    def test_restart_audit_rejects_foreign_and_terminal_states(self):
        with self.assertRaises(canonical_restart_audit.RestartAuditError):
            canonical_restart_audit.inspect('bob', JOB)
        current = goal_state_store.load(self.path)
        closed = core_state_reducer.apply(current, {
            'op': 'set_state', 'state': 'cancelled',
            'reason_code': 'TEST_CANCEL',
            'expected_version': current['version'],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=current['version'], next_state=closed,
        )
        with self.assertRaises(canonical_restart_audit.RestartAuditError):
            canonical_restart_audit.inspect(OWNER, JOB)

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
                # The provider signal may arrive before its Core CAS and
                # durable projection. Give busy Windows CI enough time for
                # both roots to finish, but still require the actual child
                # worker to start; don't replace this with a mocked result.
                child_started = finished.wait(30)
                if not child_started:
                    journal = execution_record.load(self.owner_root, OWNER, JOB)
                    canonical = goal_state_store.load(self.path)
                    # On a real Windows runner, an accepted Core result with a
                    # still-running ExecutionRecord does not identify whether
                    # projection is delayed, deadlocked or already failed.
                    # Preserve worker stacks at the failure point rather than
                    # guessing or extending the timing limit again.
                    frames = sys._current_frames()
                    worker_stacks = {
                        thread.name: ''.join(traceback.format_stack(
                            frames[thread.ident], limit=14,
                        ))[-3800:]
                        for thread in threading.enumerate()
                        if thread.name.startswith('jarvis-canonical-')
                        and thread.ident in frames
                    }
                    self.fail(
                        'Dependent node was not dispatched; durable steps='
                        + repr([(step['id'], step['state'],
                                 step.get('attempts', 0))
                                for step in journal['steps']])
                        + '; output states='
                        + repr({key: value.get('state')
                                for key, value in journal['outputs'].items()})
                        + '; accepted WorkerResult nodes='
                        + repr([(row.get('step_id'), row.get('status'))
                                for row in canonical['evidence']
                                if isinstance(row, dict)
                                and row.get('kind') == 'worker_result'])
                        + '; canonical worker stacks=' + repr(worker_stacks)
                    )
                self.assertTrue(poll_while_busy.is_set(), 'Scheduler poll blocked on worker')
                # The worker sets "finished" before its Core CAS and durable
                # output projection. On a busy Windows runner those stages may
                # outlive a two-second sleep; prove the final disk state
                # instead of treating provider completion as acceptance.
                for _ in range(300):
                    saved = execution_record.load(self.owner_root, OWNER, JOB)
                    if (all(step['state'] == 'done' for step in saved['steps'])
                            and set(saved['outputs']) == {'left', 'right', 'child'}):
                        break
                    threading.Event().wait(.05)
                saved = execution_record.load(self.owner_root, OWNER, JOB)
                if set(saved['outputs']) != {'left', 'right', 'child'}:
                    frames = sys._current_frames()
                    worker_stacks = {
                        thread.name: ''.join(traceback.format_stack(
                            frames[thread.ident], limit=16,
                        ))[-3800:]
                        for thread in threading.enumerate()
                        if thread.name.startswith('jarvis-canonical-')
                        and thread.ident in frames
                    }
                    current = goal_state_store.load(self.path)
                    self.fail(
                        'Accepted child was not durably projected: steps='
                        + repr([(x['id'], x.get('state'), x.get('attempts'))
                                for x in saved['steps']])
                        + '; outputs=' + repr(sorted(saved['outputs']))
                        + '; accepted Core rows=' + repr([
                            (x.get('step_id'), x.get('status'))
                            for x in current.get('evidence', [])
                            if isinstance(x, dict) and x.get('kind') == 'worker_result'])
                        + '; worker stacks=' + repr(worker_stacks)
                    )
                self.assertTrue(
                    all(step['state'] == 'done' for step in saved['steps']),
                    "Canonical worker projection not durable: "
                    + repr([(step['id'], step['state']) for step in saved['steps']])
                    + '; output states/reasons='
                    + repr({key: (value.get('state'), value.get('reason_code'), value.get('text'))
                            for key, value in saved['outputs'].items()})
                    + '; completed worker calls=' + repr(list(observed))
                    + '; accepted Core evidence='
                    + repr([(row.get('step_id'), row.get('status'))
                            for row in goal_state_store.load(self.path)['evidence']
                            if isinstance(row, dict) and row.get('kind') == 'worker_result']),
                )
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
                # Two overlapping provider returns are not durable Core
                # acceptance. Give the loaded Windows runner a bounded
                # interval for both real Scheduler dispatches and projections.
                # Do not silently pass just because both workers were entered.
                for _ in range(600):
                    one = execution_record.load(self.owner_root, OWNER, JOB)
                    two = execution_record.load(self.owner_root, OWNER, second_id)
                    if (one['steps'][0]['state'] == 'done'
                            and two['steps'][0]['state'] == 'done'
                            and 'left' in one['outputs']
                            and 'other' in two['outputs']):
                        break
                    threading.Event().wait(.05)
                self.assertEqual(set(observed), {'left', 'other'})
                self.assertEqual(
                    one['steps'][0]['state'], 'done',
                    'First goal has no durable worker projection: '
                    + repr((one['steps'], list(one['outputs']))),
                )
                self.assertEqual(
                    two['steps'][0]['state'], 'done',
                    'Second goal has no durable worker projection: '
                    + repr((two['steps'], list(two['outputs']))),
                )
                self.assertIn('left', one['outputs'])
                self.assertIn('other', two['outputs'])
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

    def test_canonical_workers_pin_owner_and_profile_before_delayed_thread_start(self):
        """Late OS thread scheduling must not adopt the next owner's identity.

        The real Scheduler creates worker thread targets for two owners, but
        test starts those targets only after both owner/profile loop locals
        have moved on. No external worker, device or provider is invoked.
        """
        from types import SimpleNamespace
        from modules import llm, service_store, task_queue

        started = threading.Event()
        stop_event = threading.Event()
        targets = []
        seen = []
        original_thread = threading.Thread

        class DeferredCanonicalThread:
            def __init__(self, *, target, name, **kwargs):
                self.target = target
                self.name = name
                self.done = False
            def start(self):
                targets.append(self)
                if len(targets) >= 2:
                    started.set()
            def is_alive(self):
                return not self.done
            def join(self, timeout=None):
                return

        def thread_factory(*args, **kwargs):
            if kwargs.get('name', '').startswith('jarvis-canonical-'):
                return DeferredCanonicalThread(**kwargs)
            return original_thread(*args, **kwargs)

        def discover(owner, **_):
            return (SimpleNamespace(
                selection=SimpleNamespace(
                    owner=owner, job_id='0000000000000001', node_id='only',
                ),
                attempt=1,
            ),)

        def execute(profile, offer, *, stop_event=None):
            seen.append((
                profile.slug,
                offer.selection.owner,
                llm._key_context.get(),
            ))
            self.assertEqual(profile.slug, offer.selection.owner)
            self.assertEqual(llm._key_context.get(), offer.selection.owner)
            return True

        class RapidStop:
            def wait(self, _):
                return stop_event.wait(.01)
            def is_set(self):
                return stop_event.is_set()

        with ExitStack() as stack:
            for module, name, replacement in (
                (service_store, 'ROOT', self.store / 'no-queue'),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (task_queue.threading, 'Thread', thread_factory),
                (canonical_scheduler_dispatch, 'discover', discover),
                (canonical_scheduler_dispatch, 'execute_offer', execute),
            ):
                stack.enter_context(patch.object(module, name, replacement))
            task_queue.start(
                RapidStop(),
                allowed_owners=lambda: {'alice', 'bob'},
                canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
            )
            try:
                self.assertTrue(started.wait(5), 'Both owner threads were not prepared')
                self.assertEqual(len(targets), 2)
                # Both closures execute after the scheduler has iterated the
                # other owner, deterministically reproducing late binding.
                for thread in targets:
                    thread.target()
                    thread.done = True
                self.assertEqual(
                    seen,
                    [('alice', 'alice', 'alice'),
                     ('bob', 'bob', 'bob')],
                )
            finally:
                stop_event.set()
                task_queue._THREAD.join(5)
                self.assertFalse(task_queue._THREAD.is_alive())

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
            self.assertIsInstance(
                stop_event, runtime_worker_result.CanonicalWorkerDeadline,
            )
            self.assertFalse(stop_event.is_set())
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
