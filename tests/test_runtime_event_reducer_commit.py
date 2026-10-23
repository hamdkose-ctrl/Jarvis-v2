import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RuntimeEventReducerCommitTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state, goal_state_store, runtime_event
        self.goal_state = goal_state
        self.store = goal_state_store
        self.runtime_event = runtime_event
        from modules import runtime_event_commit
        self.committer = runtime_event_commit

    def event(self, **changes):
        row = {
            'schema': 'runtime_event.v1',
            'event_id': 'evt-1',
            'source_event_key': 'watch:mail',
            'source_generation': 2,
            'subject_version': 7,
            'occurred_at': 100.0,
            'kind': 'mail_changed',
            'payload': {'message_id': 'm1'},
        }
        row.update(changes)
        return row

    def subscription(self, **changes):
        row = {
            'source_event_key': 'watch:mail',
            'source_generation': 2,
            'subject_version': 7,
            'resume_token': 'resume-1',
            'fresh_after': 50.0,
        }
        row.update(changes)
        return row

    def state_path(self, root: Path):
        path = root / 'job-1.goalstate.json'
        state = self.goal_state.new(
            owner='alice', job_id='job-1', goal='mail değişimini işle', execution_mode='durable'
        )
        self.store.create(path, state)
        return path

    def test_fresh_event_commits_evidence_via_reducer_and_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.state_path(Path(tmp))
            seen = set()
            result = self.committer.commit(
                path, self.event(), self.subscription(), seen, expected_job_version=0,
            )
            state = self.store.load(path)
            self.assertEqual(result['version'], 1)
            self.assertEqual(state['state'], 'pending')
            self.assertEqual(state['version'], 1)
            self.assertEqual(state['audit'][-1]['op'], 'append_evidence')
            self.assertEqual(state['audit'][-1]['reason_code'], 'RUNTIME_EVENT_ACCEPTED')
            self.assertEqual(state['evidence'][0]['kind'], 'runtime_event')
            self.assertEqual(state['evidence'][0]['event_id'], 'evt-1')
            self.assertEqual(seen, {'evt-1'})

    def test_duplicate_event_evidence_is_idempotent_and_heals_seen_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.state_path(Path(tmp))
            first_seen = set()
            self.committer.commit(path, self.event(), self.subscription(), first_seen, expected_job_version=0)
            restarted_seen = set()
            result = self.committer.commit(
                path, self.event(), self.subscription(), restarted_seen, expected_job_version=0,
            )
            state = self.store.load(path)
            self.assertEqual(result['version'], 1)
            self.assertEqual(state['version'], 1)
            self.assertEqual(len(state['evidence']), 1)
            self.assertEqual(restarted_seen, {'evt-1'})

    def test_stale_foreign_or_wrong_job_version_never_mutates_goalstate_or_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.state_path(Path(tmp))
            cases = [
                (self.event(source_generation=1), self.subscription(), 0),
                (self.event(source_event_key='watch:other'), self.subscription(), 0),
                (self.event(), self.subscription(), 1),
            ]
            for event, subscription, expected_version in cases:
                with self.subTest(event=event, expected_version=expected_version):
                    seen = set()
                    with self.assertRaises(ValueError):
                        self.committer.commit(
                            path, event, subscription, seen,
                            expected_job_version=expected_version,
                        )
                    state = self.store.load(path)
                    self.assertEqual(state['version'], 0)
                    self.assertEqual(state['evidence'], [])
                    self.assertEqual(seen, set())

    def test_seen_persistence_failure_after_cas_is_recoverable_without_duplicate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.state_path(root)
            seen_path = root / 'seen.json'
            seen = self.runtime_event.PersistentSeen(seen_path)
            with patch.object(seen, 'add', side_effect=OSError('disk failure')):
                with self.assertRaisesRegex(OSError, 'disk failure'):
                    self.committer.commit(
                        path, self.event(), self.subscription(), seen,
                        expected_job_version=0,
                    )
            state = self.store.load(path)
            self.assertEqual(state['version'], 1)
            self.assertEqual(len(state['evidence']), 1)
            restarted = self.runtime_event.PersistentSeen(seen_path)
            self.assertNotIn('evt-1', restarted)
            healed = self.committer.commit(
                path, self.event(), self.subscription(), restarted,
                expected_job_version=0,
            )
            self.assertEqual(healed['version'], 1)
            self.assertIn('evt-1', restarted)
            self.assertEqual(len(self.store.load(path)['evidence']), 1)

    def test_same_event_id_with_different_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.state_path(Path(tmp))
            self.committer.commit(path, self.event(), self.subscription(), set(), expected_job_version=0)
            altered = self.event(payload={'message_id': 'm2'})
            with self.assertRaises(ValueError):
                self.committer.commit(path, altered, self.subscription(), set(), expected_job_version=0)
            state = self.store.load(path)
            self.assertEqual(state['version'], 1)
            self.assertEqual(state['evidence'][0]['payload'], {'message_id': 'm1'})


if __name__ == '__main__':
    unittest.main()
