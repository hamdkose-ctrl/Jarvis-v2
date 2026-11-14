"""Sor/İzin ver/Engelle politikası: depo ve üç yürütme yolunda uygulanması."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import (outbox, service_store, publish_services as services, llm, requests_state,
                     permission_policy, permission_grants, permission_audit, permission_gate, permission_classify,
                     browser_agent)
from tests.test_desktop_agent import FakeUI, action
from modules import desktop_agent as agent


class PolicyStoreTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        self.root = Path(td.name) / 'policy'
        self.enterContext(patch.object(permission_policy, 'ROOT', self.root))
        self.token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, self.token)

    def test_default_is_ask_and_values_round_trip(self):
        self.assertEqual(permission_policy.get('alice', 'browser', 'publish'), 'ask')
        permission_policy.set('alice', 'browser', 'publish', 'deny')
        self.assertEqual(permission_policy.get('alice', 'browser', 'publish'), 'deny')
        permission_policy.set('alice', 'browser', 'publish', 'ask')
        self.assertEqual(permission_policy.get('alice', 'browser', 'publish'), 'ask')

    def test_locked_classes_and_bad_values_rejected(self):
        for cls in ('money_credential', 'system_config'):
            with self.assertRaises(ValueError):
                permission_policy.set('alice', 'desktop', cls, 'allow')
            self.assertEqual(permission_policy.get('alice', 'desktop', cls), 'ask')
        with self.assertRaises(ValueError):
            permission_policy.set('alice', 'desktop', 'publish', 'maybe')
        with self.assertRaises(ValueError):
            permission_policy.set('alice', 'De sk', 'publish', 'deny')

    def test_corrupt_file_means_ask(self):
        self.root.mkdir(parents=True)
        (self.root / 'alice.json').write_text('{bozuk', encoding='utf-8')
        self.assertEqual(permission_policy.get('alice', 'outbox', 'message_out'), 'ask')
        (self.root / 'alice.json').write_text('{"outbox:message_out":"evet"}', encoding='utf-8')
        self.assertEqual(permission_policy.get('alice', 'outbox', 'message_out'), 'ask')

    def test_apply_rules(self):
        permission_policy.set('alice', 'outbox', 'message_out', 'deny')
        permission_policy.set('alice', 'desktop', 'local_destructive', 'allow')
        permission_policy.set('alice', 'browser', 'publish', 'allow')
        a = permission_policy.apply
        self.assertEqual(a('alice', 'outbox', 'message_out', 'allow', 'x')[0], 'deny')
        self.assertEqual(a('alice', 'desktop', 'local_destructive', 'ask', 'x')[0], 'allow')
        self.assertEqual(a('alice', 'browser', 'publish', 'ask', 'x')[0], 'ask')  # yayın onayı değişmez
        self.assertEqual(a('alice', 'desktop', 'read', 'allow', 'x'), ('allow', 'x'))

    def test_users_are_separate(self):
        permission_policy.set('alice', 'outbox', 'message_out', 'deny')
        token = llm._key_context.set('bob')
        try:
            self.assertEqual(permission_policy.get('bob', 'outbox', 'message_out'), 'ask')
        finally:
            llm._key_context.reset(token)


class PolicyEnforcementTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root = Path(td.name)
        self.enterContext(patch.object(service_store, 'ROOT', root / 'outbox'))
        self.enterContext(patch.object(permission_grants, 'ROOT', root / 'grants'))
        self.enterContext(patch.object(permission_policy, 'ROOT', root / 'policy'))
        self.enterContext(patch.object(permission_audit, 'DATA_DIR', root))
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        req = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, req)
        self.send = self.enterContext(patch.object(services, 'send', return_value={'remote_id': 'f', 'scope': 'provider_accepted'}))
        from modules import scheduler_resource_gate
        self.enterContext(patch.object(scheduler_resource_gate,'_ACCOUNT_CLAIM_ROOT',root/'providers'))
        self.enterContext(patch.object(outbox.services,'DATA_DIR',root/'connections'))

    def prepare(self, n):
        payload = {'service': 'gmail', 'destination': 'ahmet@example.org', 'subject': 'S', 'text': 'Merhaba %d' % n}
        return outbox.prepare('alice', payload, 'policy-%d' % n)

    def slots(self):
        with service_store.database('alice') as db:
            return db.execute('SELECT COUNT(*) FROM outbox_send_budget').fetchone()[0]

    def test_outbox_deny_beats_grant_and_explicit_approval(self):
        permission_grants.grant_message('alice', 'ahmet@example.org', 600)
        permission_policy.set('alice', 'outbox', 'message_out', 'deny')
        for approve in (False, True):
            result = outbox.dispatch('alice', self.prepare(approve + 1), approve=approve)
            self.assertEqual(result['state'], 'blocked')
        self.send.assert_not_called()
        self.assertEqual(self.slots(), 0)

    def test_outbox_allow_does_not_replace_recipient_permission(self):
        permission_policy.set('alice', 'outbox', 'message_out', 'allow')
        self.assertEqual(outbox.dispatch('alice', self.prepare(3))['state'], 'approval')
        self.send.assert_not_called()

    def test_outbox_policy_failure_is_closed(self):
        with patch.object(permission_policy, 'get', side_effect=RuntimeError('PRIVATE')), \
                patch.object(outbox, '_record_failure'):
            result = outbox.dispatch('alice', self.prepare(4), approve=True)
        self.assertEqual(result['state'], 'blocked')
        self.assertNotIn('PRIVATE', result['text'])
        self.send.assert_not_called()

    def test_browser_deny_raises_and_policy_failure_is_closed(self):
        permission_policy.set('alice', 'browser', 'local_reversible', 'deny')
        page = type('P', (), {'url': 'https://example.org/'})()
        with patch.object(permission_classify, 'classify_detail', return_value=('local_reversible', True)), \
                patch.object(permission_audit, 'record'):
            with self.assertRaises(ValueError):
                browser_agent._permission_decision('alice', page, {'op': 'click', 'selector': 'a'})
            with patch.object(permission_policy, 'get', side_effect=RuntimeError('x')), \
                    patch.object(browser_agent, '_record_failure'):
                with self.assertRaises(ValueError):
                    browser_agent._permission_decision('alice', page, {'op': 'click', 'selector': 'a'})

    def test_desktop_deny_blocks_before_send(self):
        permission_policy.set('alice', 'desktop', 'local_reversible', 'deny')
        ui = FakeUI()
        job = {'owner': 'alice', 'target': 'Hesap Makinesi', 'goal': '12 ile 7 topla', 'status': 'running',
               'history': [], 'hwnd': None, 'approval': None, 'pending_effect': None}
        with tempfile.TemporaryDirectory() as td, \
                patch.object(agent, 'STORE', Path(td) / 'jobs'), \
                patch.object(agent.privacy, 'blocked', return_value=None), \
                patch.object(agent.time, 'sleep'), \
                patch.object(permission_audit, 'record'), \
                patch.object(permission_classify, 'classify_detail', return_value=('local_reversible', True)), \
                patch.object(agent, '_plan', side_effect=[action()]):
            agent.run(job, ui=ui, current=lambda: 'alice')
        self.assertEqual(ui.calls, [])
        self.assertEqual(job['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
