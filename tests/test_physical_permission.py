"""Fiziksel eylem sınıfı: süreli izinle açılmaz, politika Engelle kesin rettir."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import llm, permission_classify as classify, permission_gate as gate, permission_policy as policy, requests_state


class PhysicalPermissionTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        self.enterContext(patch.object(policy, 'ROOT', Path(td.name) / 'policy'))
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, token)

    def test_registered_physical_class_always_asks_without_timed_grants(self):
        self.assertIn('physical', gate.CLASSES)
        for grants in (None, {}, {'physical': {'printer': 9999999999}, 'message_out': {'printer': 9999999999}}):
            result = gate.decide({'class': 'physical', 'target': 'printer', 'via': 'system'}, grants, now=1)
            self.assertEqual(result['decision'], 'ask')
            self.assertIn('Fiziksel', result['reason'])

    def test_allow_cannot_open_physical_but_deny_always_blocks(self):
        policy.set('alice', 'printer', 'physical', 'allow')
        self.assertEqual(policy.apply('alice', 'printer', 'physical', 'ask', 'physical')[0], 'ask')
        policy.set('alice', 'printer', 'physical', 'deny')
        for decision in ('allow', 'ask', 'deny'):
            result = policy.apply('alice', 'printer', 'physical', decision, 'physical')
            self.assertEqual(result[0], 'deny')
            self.assertIn('Politika: Engelle', result[1])

    def test_physical_words_and_explicit_contract_class(self):
        for name, target in [('Yazdır', ''), ('Start print', ''), ('İşi başlat', 'OctoPrint'),
                             ('Filament ısıt', ''), ('bilinmeyen işlem', '3D yazıcı')]:
            self.assertEqual(classify.classify_detail('system', name, target), ('physical', True))
        self.assertEqual(classify.classify_detail('system', 'bilinmeyen işlem', action_class='physical'), ('physical', True))
        self.assertEqual(classify.classify('system', 'sil', action_class='physical'), 'physical')

    def test_explicit_class_cannot_unlock_locked_or_physical_actions(self):
        self.assertEqual(classify.classify('system', 'öde', action_class='read'), 'money_credential')
        self.assertEqual(classify.classify('system', 'settings', action_class='read'), 'system_config')
        self.assertEqual(classify.classify('system', 'Yazdır', action_class='read'), 'physical')
        for value in ('invalid', [], False):
            self.assertEqual(classify.classify_detail('system', 'oku', action_class=value), ('system_config', False))

    def test_previous_classes_and_unknown_fallback_remain(self):
        self.assertEqual(gate.CLASSES - {'physical', 'external_write'}, {'read', 'local_reversible', 'local_destructive',
                         'message_out', 'publish', 'money_credential', 'system_config'})
        self.assertEqual(classify.classify_detail('system', 'belirsiz işlem'), ('system_config', False))


if __name__ == '__main__':
    unittest.main()
