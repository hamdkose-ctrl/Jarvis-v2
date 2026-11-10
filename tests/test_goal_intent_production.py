import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import brain_context, goal_executor, goal_state_store


class GoalIntentProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(goal_executor, 'STORE', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job = {'id': 'a' * 16, 'owner': 'alice', 'request': 'original',
                    'state': 'interrupted', 'goals': [], 'steps': [], 'outputs': {}}
        goal_executor._save(self.job)
        self.path = Path(self.temp.name) / 'alice' / (self.job['id'] + '.goalstate.json')

    def snapshot(self):
        row = goal_executor.read_job('alice', self.job['id'])
        return dict(brain_context._goal_card('alice', row).provenance)

    def test_add_and_revise_commit_canonical_and_project(self):
        goal_executor.append_goal_task('alice', self.job['id'], 'new result', expected_snapshot=self.snapshot())
        before = goal_state_store.load(self.path)
        goal_executor.revise_job('alice', self.job['id'], 'revised', expected_snapshot=self.snapshot())
        state = goal_state_store.load(self.path)
        self.assertGreater(state['version'], before['version'])
        self.assertEqual(state['goal_intent']['additions'], ['new result'])
        self.assertEqual(state['goal_intent']['revision'], 'revised')
        self.assertEqual([g['text'] for g in goal_executor.read_job('alice', self.job['id'])['goals']], ['original', 'new result'])

    def test_same_state_execution_change_rejects_offered_card(self):
        snapshot = self.snapshot()
        job = goal_executor.read_job('alice', self.job['id'])
        job['feedback'] = ['changed']
        goal_executor._save(job)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            goal_executor.revise_job('alice', self.job['id'], 'revised', expected_snapshot=snapshot)
        self.assertEqual(self.path.read_bytes(), before)

    def test_question_add_and_prioritize_preserve_pending_control(self):
        job = goal_executor.read_job('alice', self.job['id'])
        job.update(state='question', question='Which source?', waiting='s1')
        goal_executor._save(job)
        goal_executor.append_goal_task('alice', self.job['id'], 'new result', expected_snapshot=self.snapshot())
        goal_executor.prioritize_job('alice', self.job['id'], expected_snapshot=self.snapshot())
        goal_executor.revise_job('alice', self.job['id'], 'revised', expected_snapshot=self.snapshot())
        updated = goal_executor.read_job('alice', self.job['id'])
        self.assertEqual((updated['state'], updated['question'], updated['waiting']),
                         ('question', 'Which source?', 's1'))
        self.assertEqual([g['text'] for g in updated['goals']], ['original', 'new result'])
        intent = goal_state_store.load(self.path)['goal_intent']
        self.assertEqual(intent['additions'], ['new result'])
        self.assertEqual(intent['revision'], 'revised')
        self.assertGreater(intent['priority'], 0)

    def test_approval_and_review_allow_add_but_refuse_revise(self):
        for state in ('approval', 'review'):
            with self.subTest(state=state):
                job = goal_executor.read_job('alice', self.job['id'])
                job['state'] = state
                if state == 'approval':
                    job.update(waiting='s1', steps=[{'id': 's1', 'state': 'approval', 'tool': 'browser'}],
                               outputs={'s1': {'state': 'approval', 'id': 'token'}})
                goal_executor._save(job)
                goal_executor.append_goal_task('alice', self.job['id'], state, expected_snapshot=self.snapshot())
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    goal_executor.revise_job('alice', self.job['id'], 'revise', expected_snapshot=self.snapshot())
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(goal_executor.read_job('alice', self.job['id'])['state'], state)

    def test_stale_canonical_version_rejects_offered_card(self):
        from modules import goal_state_compat
        snapshot = self.snapshot()
        goal_state_compat.apply_goal_intent(
            self.path, owner='alice', job_id=self.job['id'],
            expected_version=snapshot['canonical_version'], operation='revise', text='other')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            goal_executor.append_goal_task('alice', self.job['id'], 'stale', expected_snapshot=snapshot)
        self.assertEqual(self.path.read_bytes(), before)

    def test_running_cancel_fences_old_execution_writer(self):
        row = goal_executor.read_job('alice', self.job['id'])
        row['state'] = 'running'
        goal_executor._save(row)
        old = goal_executor.read_job('alice', self.job['id'])
        with patch('modules.service_store.identity', return_value='alice'):
            goal_executor.cancel_job('alice', self.job['id'], expected_snapshot=self.snapshot())
        old['feedback'] = ['late worker']
        with self.assertRaises(ValueError):
            goal_executor._save(old)
        self.assertEqual(goal_executor.read_job('alice', self.job['id'])['state'], 'cancelled')
        self.assertEqual(goal_state_store.load(self.path)['state'], 'cancelled')

    def test_projection_failure_rebuilds_from_canonical(self):
        snapshot = self.snapshot()
        with patch.object(goal_executor, '_save', side_effect=OSError('failure')):
            with self.assertRaisesRegex(ValueError, 'niyeti kaydedildi'):
                goal_executor.append_goal_task('alice', self.job['id'], 'new result', expected_snapshot=snapshot)
        self.assertEqual(goal_state_store.load(self.path)['goal_intent']['additions'], ['new result'])
        self.assertEqual([g['text'] for g in goal_executor.read_job('alice', self.job['id'])['goals']], ['original', 'new result'])


if __name__ == '__main__':
    unittest.main()
