import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class GoalStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_executor, goal_state_compat, goal_state_store
        self.goal_executor = goal_executor
        self.compat = goal_state_compat
        self.store = goal_state_store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def job(self, state='running'):
        return {
            'id': '0123456789abcdef',
            'owner': 'alice',
            'request': 'Raporu hazırla',
            'created': 1,
            'state': state,
            'goals': [],
            'steps': [],
            'outputs': {},
        }

    def test_compare_and_swap_rejects_stale_persisted_version(self):
        path = self.root / 'state.json'
        current = self.compat.project(self.job())
        self.store.create(path, current)
        next_state = self.compat.advance(current, self.job('paused'))
        self.store.compare_and_swap(path, expected_version=0, next_state=next_state)
        with self.assertRaises(self.store.PersistedStateConflict):
            self.store.compare_and_swap(path, expected_version=0, next_state=next_state)

    def test_legacy_projection_is_idempotent_for_same_state(self):
        path = self.root / 'state.json'
        first = self.compat.sync(self.job(), path)
        second = self.compat.sync(self.job(), path)
        self.assertEqual(first['state'], 'running')
        self.assertEqual(second['version'], first['version'])
        self.assertEqual(second, first)

    def test_legacy_waiting_state_and_blocker_are_reduced_and_persisted(self):
        path = self.root / 'state.json'
        self.compat.sync(self.job(), path)
        job = self.job('approval')
        job['blocker'] = 'Kullanıcı onayı gerekli.'
        state = self.compat.sync(job, path)
        self.assertEqual(state['state'], 'waiting')
        self.assertEqual(state['blocker']['code'], 'LEGACY_APPROVAL')
        on_disk = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(on_disk, state)

    def test_goal_executor_save_writes_canonical_shadow_before_legacy_record(self):
        with patch.object(self.goal_executor, 'STORE', self.root):
            job = self.job()
            self.goal_executor._save(job)
            canonical = self.root / 'alice' / '0123456789abcdef.goalstate.json'
            legacy = self.root / 'alice' / '0123456789abcdef.json'
            self.assertTrue(canonical.exists())
            self.assertTrue(legacy.exists())
            state = json.loads(canonical.read_text(encoding='utf-8'))
            self.assertEqual(state['state'], 'running')
            self.assertEqual(state['job_id'], job['id'])


if __name__ == '__main__':
    unittest.main()
