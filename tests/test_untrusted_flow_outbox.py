"""Etiketsiz dış belirteçlerin gerçek outbox yolunda onay sınırı."""
import json
from contextvars import ContextVar
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from modules import (goal_tools, llm, outbox, permission_audit, permission_grants,
                     permission_policy, requests_state, service_store, untrusted_flow)

CANARY = 'SESSION_CANARY_UNRECOGNIZED_XYZ'


class FlowOutboxTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root = Path(td.name)
        for module, attr, path in [(service_store, 'ROOT', 'outbox'), (permission_audit, 'DATA_DIR', '.'),
                                   (permission_grants, 'ROOT', 'grants'), (permission_policy, 'ROOT', 'policy')]:
            self.enterContext(patch.object(module, attr, root / path))
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, token)
        self.enterContext(patch.object(untrusted_flow, '_SEEN', ContextVar('test_flow', default=None), create=True))
        self.send = self.enterContext(patch.object(outbox.services, 'send', side_effect=lambda owner, payload, progress:
            {'scope': 'provider_accepted', 'remote_id': 'fake', 'service': payload['service'], 'destination': payload['destination']}))
        outbox.grant('alice', 'gmail', 'ahmet@example.org', 600)
        self.data = {'service': 'gmail', 'destination': 'ahmet@example.org', 'subject': 'Durum', 'text': 'Özet ' + CANARY}
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice', data={'contacts': {'Ahmet': 'ahmet@example.org'}}))
        self.identity = {'owner': 'alice', 'job_id': 'flow_job', 'task_id': 'send', 'request': "Ahmet'e mesaj gönder"}
        from modules import scheduler_resource_gate
        self.enterContext(patch.object(scheduler_resource_gate,'_ACCOUNT_CLAIM_ROOT',root/'providers'))
        self.enterContext(patch.object(outbox.services,'DATA_DIR',root/'connections'))

    def execute(self, data=None, sources=None):
        return goal_tools.execute(self.runtime, 'publish', data or self.data,
                                  sources or {'mail': {'state': 'done', 'text': 'Kaynak ' + CANARY}}, self.identity)

    def slots(self):
        with service_store.database('alice') as db:
            return db.execute('SELECT COUNT(*) FROM outbox_send_budget').fetchone()[0]

    def test_real_goal_path_requires_approval_even_with_recipient_grant(self):
        result = self.execute()
        self.assertEqual(result['state'], 'approval')
        self.send.assert_not_called()
        self.assertEqual(self.slots(), 0)
        self.assertEqual(result['preview']['destination'], 'ahmet@example.org')
        self.assertNotIn(CANARY, json.dumps(permission_audit.recent('alice')))

    def test_subject_is_guarded_and_labeled_source_value_is_detected(self):
        result = self.execute(dict(self.data, text='Normal özet', subject=CANARY),
                              {'mail': {'text': 'oturum_belirteci=' + CANARY}})
        self.assertEqual(result['state'], 'approval')
        self.send.assert_not_called()

    def test_same_source_without_shared_token_keeps_existing_send(self):
        self.assertEqual(self.execute(dict(self.data, text='Normal özet'))['state'], 'done')
        self.send.assert_called_once()
        self.assertEqual(self.slots(), 1)

    def test_policy_deny_still_wins_and_approval_does_not_consume_slot(self):
        permission_policy.set('alice', 'outbox', 'message_out', 'deny')
        result = self.execute()
        self.assertEqual(result['state'], 'blocked')
        self.send.assert_not_called()
        self.assertEqual(self.slots(), 0)

    def test_guard_failure_is_closed_even_with_explicit_approval(self):
        oid = outbox.prepare('alice', self.data, 'guard_failure:send')
        with patch.object(untrusted_flow, 'shared_tokens', side_effect=RuntimeError('guard failed')), \
                patch.object(outbox, '_record_failure') as record:
            result = outbox.dispatch('alice', oid, approve=True)
        self.assertEqual(result['state'], 'blocked')
        record.assert_called()
        self.send.assert_not_called()
        self.assertEqual(self.slots(), 0)

    def test_taint_survives_context_reset_but_exact_content_approval_can_send(self):
        result = self.execute()
        self.assertEqual(result['state'], 'approval')
        # Başka bir yürütücüde bellek bağlamı yok; değişmez kayıttaki onay gereği kalır.
        untrusted_flow.observe('alice', 'another_job', {})
        self.assertEqual(outbox.dispatch('alice', result['id'])['state'], 'approval')
        self.send.assert_not_called()
        self.assertEqual(outbox.dispatch('alice', result['id'], approve=True)['state'], 'done')
        self.send.assert_called_once()

    def test_other_owner_and_new_job_do_not_inherit_sources(self):
        self.execute()
        self.identity = dict(self.identity, job_id='different_job')
        self.assertEqual(self.execute(sources={'mail': {'text': 'Normal özet'}})['state'], 'done')
        token = llm._key_context.set('bob')
        try:
            self.assertFalse(untrusted_flow.requires_approval('bob', 'flow_job:send', self.data))
        finally:
            llm._key_context.reset(token)

    def test_omitting_dependency_after_seen_output_does_not_bypass_guard(self):
        untrusted_flow.observe('alice', 'flow_job', {'source': {'text': CANARY}})
        self.assertEqual(self.execute(sources={'unrelated': {'text': 'Normal içerik'}})['state'], 'approval')
        self.send.assert_not_called()

    def test_oversized_source_poison_is_closed_until_a_new_job(self):
        with self.assertRaises(ValueError):
            untrusted_flow.observe('alice', 'flow_job', 'x' * 4_000_001)
        with self.assertRaises(ValueError):
            self.execute(sources={'other': {'text': 'Normal'}})
        self.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
