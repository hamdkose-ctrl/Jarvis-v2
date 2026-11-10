import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import browser_agent, goal_executor, goal_state_store, llm, outbox, service_store


class ApprovalCancelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        for module, attribute, sub in ((goal_executor, 'STORE', 'goals'),
                                       (browser_agent, 'STORE', 'browser'),
                                       (service_store, 'ROOT', 'service')):
            p = patch.object(module, attribute, base / sub)
            p.start()
            self.addCleanup(p.stop)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)

    def seed(self, tool, token):
        job = {'id': 'a' * 16, 'owner': 'alice', 'request': 'goal', 'state': 'approval',
               'goals': [], 'steps': [{'id': 's1', 'tool': tool, 'state': 'approval'}],
               'waiting': 's1', 'outputs': {'s1': {'id': token, 'state': 'approval'}}}
        goal_executor._save(job, move_pointer=True)
        row = goal_executor.read_job('alice', job['id'])
        snapshot = {'canonical_version': row['_canonical_version'],
                    'execution_snapshot': row['_execution_snapshot']}
        return job['id'], snapshot

    def test_browser_matching_approval_cancels(self):
        ident, snapshot = self.seed('browser', 'token-a')
        pending = browser_agent._root('alice') / 'pending.json'
        pending.write_text(json.dumps({'id': 'token-a'}), encoding='utf-8')
        goal_executor.cancel_job('alice', ident, expected_snapshot=snapshot)
        self.assertFalse(pending.exists())
        self.assertEqual(goal_executor.read_job('alice', ident)['state'], 'cancelled')
        self.assertEqual(goal_state_store.load(goal_executor.STORE / 'alice' / (ident + '.goalstate.json'))['state'], 'cancelled')

    def test_other_goal_browser_pending_is_preserved(self):
        ident, snapshot = self.seed('browser', 'token-a')
        pending = browser_agent._root('alice') / 'pending.json'
        pending.write_text(json.dumps({'id': 'token-b'}), encoding='utf-8')
        before = pending.read_bytes()
        with self.assertRaisesRegex(ValueError, 'eşleşmiyor'):
            goal_executor.cancel_job('alice', ident, expected_snapshot=snapshot)
        self.assertEqual(pending.read_bytes(), before)
        self.assertEqual(goal_executor.read_job('alice', ident)['state'], 'approval')

    def test_outbox_approval_cancels_matching_local_record(self):
        payload = {'service': 'gmail', 'destination': 'friend@example.com', 'subject': 'Hello', 'text': 'Body'}
        oid = outbox.prepare('alice', payload, 'approval-cancel')
        ident, snapshot = self.seed('publish', oid)
        goal_executor.cancel_job('alice', ident, expected_snapshot=snapshot)
        self.assertEqual(outbox.get('alice', oid)['state'], 'cancelled')
        self.assertEqual(goal_executor.read_job('alice', ident)['state'], 'cancelled')

    def test_partial_local_cancel_is_reported(self):
        ident, snapshot = self.seed('browser', 'token-a')
        pending = browser_agent._root('alice') / 'pending.json'
        pending.write_text(json.dumps({'id': 'token-a'}), encoding='utf-8')
        with patch.object(goal_executor, '_save', side_effect=OSError('disk')):
            with self.assertRaisesRegex(ValueError, 'yerel işlem iptal edildi'):
                goal_executor.cancel_job('alice', ident, expected_snapshot=snapshot)
        self.assertFalse(pending.exists())
        self.assertEqual(goal_executor.read_job('alice', ident)['state'], 'approval')
