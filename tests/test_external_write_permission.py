"""Dış hesap yazıları: açık hedef, her seferinde onay ve ayrı effect riski."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import llm, permission_classify as classify, permission_gate as gate
from modules import permission_grants, permission_policy as policy


class ExternalWritePermissionTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root = Path(td.name)
        self.enterContext(patch.object(policy, 'ROOT', root / 'policy'))
        self.enterContext(patch.object(permission_grants, 'ROOT', root / 'grants'))
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)

    def test_registered_external_write_always_asks_without_standing_grant(self):
        self.assertIn('external_write', gate.CLASSES)
        action = {'class': 'external_write',
                  'target': 'google:primary:event-17', 'via': 'outbox'}
        for grants in (None, {},
                       {'external_write': {'google:primary:event-17': 9999999999}},
                       {'message_out': {'google:primary:event-17': 9999999999}}):
            with self.subTest(grants=grants):
                result = gate.decide(action, grants, now=1)
                self.assertEqual(result['decision'], 'ask')
                self.assertEqual(result['class'], 'external_write')
                self.assertIn('dış hesap', result['reason'].casefold())

    def test_external_write_requires_a_concrete_target(self):
        result = gate.decide({'class': 'external_write', 'target': '   ', 'via': 'outbox'})
        self.assertEqual(result['decision'], 'ask')
        self.assertIn('hedef', result['reason'].casefold())

    def test_explicit_external_delete_keeps_permission_class(self):
        self.assertEqual(
            classify.classify_detail('outbox', 'Etkinliği sil',
                                     'google:primary:event-17', action_class='external_write'),
            ('external_write', True),
        )
        self.assertEqual(
            classify.classify_detail('outbox', 'Etkinliği güncelle',
                                     'outlook:work:event-9', action_class='external_write'),
            ('external_write', True),
        )

    def test_money_and_system_safety_still_override_explicit_external_write(self):
        self.assertEqual(
            classify.classify('outbox', 'Şifre değiştir', action_class='external_write'),
            'money_credential',
        )
        self.assertEqual(
            classify.classify('system', 'Registry ayarını değiştir', action_class='external_write'),
            'system_config',
        )

    def test_policy_allow_does_not_open_external_write_but_deny_blocks(self):
        policy.set('alice', 'outbox', 'external_write', 'allow')
        self.assertEqual(
            policy.apply('alice', 'outbox', 'external_write', 'ask', 'Dış hesap yazısı.')[0],
            'ask',
        )
        policy.set('alice', 'outbox', 'external_write', 'deny')
        for decision in ('allow', 'ask', 'deny'):
            with self.subTest(decision=decision):
                result = policy.apply('alice', 'outbox', 'external_write', decision, 'x')
                self.assertEqual(result[0], 'deny')
                self.assertIn('Politika: Engelle', result[1])

    def test_grant_store_has_no_external_write_slot(self):
        self.assertEqual(set(permission_grants.load('alice')), {'message_out', 'apps_never'})


if __name__ == '__main__':
    unittest.main()
