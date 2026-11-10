"""Real-file stale writes, including two independent processes."""
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import release_guard
from modules import execution_record, goal_job_control, goal_state_compat, goal_state_save_hook


def _competing_write(root, snapshot, gate, results):
    root = Path(root)
    gate.wait(20)
    try:
        with patch.object(release_guard, 'atomic', goal_state_save_hook._atomic):
            with goal_job_control.locked(root, snapshot['id']):
                goal_job_control.assert_fresh(root, snapshot)
                payload = goal_job_control.persistent(snapshot)
                payload['feedback'] = ['new execution observation']
                payload['_goal_version_fence'] = snapshot['_canonical_version']
                release_guard.atomic(root / (snapshot['id'] + '.json'), json.dumps(payload).encode())
        results.put('saved')
    except ValueError:
        results.put('stale')


class GoalJobControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'alice'
        self.root.mkdir()
        self.job = dict(id='a' * 16, owner='alice', request='original request',
                        state='interrupted', goals=[], steps=[], outputs={})
        self.patcher = patch.object(release_guard, 'atomic', goal_state_save_hook._atomic)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        release_guard.atomic(self.root / (self.job['id'] + '.json'), json.dumps(self.job).encode())
        self.path = self.root / (self.job['id'] + '.goalstate.json')

    def snapshot(self):
        job = execution_record.load(self.root, 'alice', self.job['id'])
        goal_job_control.capture(self.root, job)
        return job

    def test_same_lifecycle_execution_change_invalidates_snapshot(self):
        old = self.snapshot()
        changed = goal_job_control.persistent(old)
        changed['feedback'] = ['different']
        release_guard.atomic(self.root / (old['id'] + '.json'), json.dumps(changed).encode())
        with self.assertRaisesRegex(ValueError, 'yürütme'):
            goal_job_control.assert_fresh(self.root, old)

    def test_hook_rejects_stale_canonical_version_without_touching_execution(self):
        old = self.snapshot()
        goal_state_compat.apply_goal_intent(self.path, owner='alice', job_id=old['id'],
                                          expected_version=old['_canonical_version'],
                                          operation='revise', text='new instruction')
        record = execution_record.path_for(self.root, old['id'])
        before = record.read_bytes()
        payload = goal_job_control.persistent(old)
        payload['_goal_version_fence'] = old['_canonical_version']
        with self.assertRaises(ValueError):
            release_guard.atomic(self.root / (old['id'] + '.json'), json.dumps(payload).encode())
        self.assertEqual(record.read_bytes(), before)

    def test_two_processes_cannot_commit_the_same_offered_execution_snapshot(self):
        context = multiprocessing.get_context('spawn')
        gate, results = context.Event(), context.Queue()
        snapshot = self.snapshot()
        workers = [context.Process(target=_competing_write,
                                   args=(str(self.root), snapshot, gate, results)) for _ in range(2)]
        for worker in workers:
            worker.start()
        gate.set()
        for worker in workers:
            worker.join(30)
            if worker.is_alive():
                worker.terminate()
                worker.join()
                self.fail('Control worker did not finish')
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(sorted(results.get(timeout=5) for _ in workers), ['saved', 'stale'])
        results.close()
        results.join_thread()
