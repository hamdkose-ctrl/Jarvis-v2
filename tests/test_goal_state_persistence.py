import json
import tempfile
import unittest
from pathlib import Path


class GoalStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state_compat, goal_state_store
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
        self.store.compare_and_swap(
            path, expected_version=current['version'], next_state=next_state,
        )
        with self.assertRaises(self.store.PersistedStateConflict):
            self.store.compare_and_swap(
                path, expected_version=current['version'], next_state=next_state,
            )

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

    def test_terminal_canonical_state_is_not_reopened_by_legacy_projection(self):
        path = self.root / 'state.json'
        terminal = self.compat.sync(self.job('done'), path)
        reopened = self.compat.sync(self.job('paused'), path)
        self.assertEqual(terminal['state'], 'done')
        self.assertEqual(reopened, terminal)


if __name__ == '__main__':
    unittest.main()
