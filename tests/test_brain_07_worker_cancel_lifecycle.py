"""Cross-process durable terminal lifecycle check for BRAIN-07 workers."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import core_state_reducer, goal_executor, goal_state, goal_state_store, requests_state, specialist_orchestrator

OWNER = 'alice'
JOB = '0123456789abcdef'


class ExternalGoalCancellationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for attr, value in (('STORE', self.root), ('_ACTIVE', set()), ('_CANCEL_REQUESTED', set())):
            token = patch.object(goal_executor, attr, value)
            token.start()
            self.addCleanup(token.stop)
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        self.job = {'owner': OWNER, 'id': JOB, 'state': 'running', '_canonical_version': 1}
        parent = self.root / OWNER
        parent.mkdir()
        self.path = parent / (JOB + '.goalstate.json')
        initial = goal_state.new(owner=OWNER, job_id=JOB, goal='read public page', authority='canonical')
        active = core_state_reducer.apply(initial, {
            'op': 'set_state', 'state': 'running', 'reason_code': 'TEST_RUNNING',
            'expected_version': 0,
        })
        goal_state_store.create(self.path, active)

    def terminal(self, status):
        current = goal_state_store.load(self.path)
        changed = core_state_reducer.apply(current, {
            'op': 'set_state', 'state': status, 'reason_code': 'TEST_EXTERNAL_TERMINAL',
            'expected_version': current['version'],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=current['version'], next_state=changed,
        )

    def test_running_goal_is_allowed(self):
        goal_executor._ensure(self.runtime, self.job)

    def test_external_cancel_blocks_stale_worker_without_local_flag(self):
        self.terminal('cancelled')
        self.assertFalse(goal_executor._CANCEL_REQUESTED)
        with self.assertRaises(requests_state.Cancelled):
            goal_executor._ensure(self.runtime, self.job)
        with patch.object(specialist_orchestrator, 'execute_step') as worker:
            with self.assertRaises(requests_state.Cancelled):
                goal_executor._record(
                    self.runtime, self.job, {'id': 's1', 'tool': 'research'},
                )
            worker.assert_not_called()

    def test_external_completion_blocks_stale_worker(self):
        self.terminal('done')
        with self.assertRaises(requests_state.Cancelled):
            goal_executor._ensure(self.runtime, self.job)

    def test_missing_required_canonical_sidecar_fails_closed(self):
        self.path.unlink()
        with self.assertRaises(requests_state.Cancelled):
            goal_executor._ensure(self.runtime, self.job)

    def test_legacy_job_without_sidecar_remains_compatible(self):
        self.path.unlink()
        self.job.pop('_canonical_version')
        goal_executor._ensure(self.runtime, self.job)

    def test_corrupt_canonical_state_cannot_be_accepted(self):
        self.path.write_bytes(b'corrupt')
        with self.assertRaises(goal_state_store.PersistedStateCorruption):
            goal_executor._ensure(self.runtime, self.job)

    def test_other_job_cancel_does_not_stop_active_job(self):
        other_id = 'fedcba9876543210'
        other = goal_state.new(owner=OWNER, job_id=other_id, goal='other goal', authority='canonical')
        path = self.path.parent / (other_id + '.goalstate.json')
        goal_state_store.create(path, other)
        changed = core_state_reducer.apply(other, {
            'op': 'set_state', 'state': 'cancelled', 'reason_code': 'TEST_OTHER',
            'expected_version': 0,
        })
        goal_state_store.compare_and_swap(path, expected_version=0, next_state=changed)
        goal_executor._ensure(self.runtime, self.job)


if __name__ == '__main__':
    unittest.main()
