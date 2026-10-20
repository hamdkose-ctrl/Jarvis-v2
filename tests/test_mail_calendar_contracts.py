"""Mail/takvim sözleşmeleri mevcut davranışı değiştirmeden keşfedilir."""
import json
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import google_api, llm, requests_state, tool_contract
from modules import tool_mail, tool_calendar


class MailCalendarContractsTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.enterContext(patch.object(google_api, 'DATA_DIR', self.root))
        self.enterContext(patch.object(google_api, 'TOKEN', self.root / 'token.json'))
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, token)

    def test_contracts_validate_load_and_describe_as_json(self):
        loaded = tool_contract.load_all()
        for module in (tool_mail, tool_calendar):
            with self.subTest(tool=module.CONTRACT['id']):
                self.assertEqual(tool_contract.validate(module.CONTRACT), [])
                self.assertIn(module.CONTRACT['id'], loaded)
                view = tool_contract.describe(module.CONTRACT)
                json.dumps(view)
                self.assertEqual(view['area'], 'iletisim')
                self.assertTrue(all(a['class'] == 'read' for a in view['actions']))
                self.assertTrue(all({'id', 'name', 'desc', 'class', 'params'} <= set(a) for a in view['actions']))
                for action in view['actions']:
                    entry = getattr(google_api, action['id'])
                    self.assertTrue(callable(entry))
                    self.assertTrue(set(action['params']) <= set(inspect.signature(entry).parameters))

    def test_status_only_observes_current_users_record_without_network_or_migration(self):
        path = self.root / 'google_users' / 'alice' / 'token.json'
        with patch.object(google_api, '_service', side_effect=AssertionError('Canlı servis yasak')), \
                patch.object(google_api, 'token_path', side_effect=AssertionError('Taşıma yasak')), \
                patch.object(llm, 'ask', side_effect=AssertionError('Model yasak')):
            self.assertEqual(tool_mail.status()['state'], 'not_connected')
            self.assertFalse((self.root / 'google_users').exists())
            path.parent.mkdir(parents=True)
            path.write_text('fixture', encoding='utf-8')
            for module in (tool_mail, tool_calendar):
                self.assertEqual(module.status()['state'], 'ready')
                self.assertNotIn('fixture', json.dumps(module.status()))
            token = llm._key_context.set('bob')
            try:
                self.assertEqual(tool_mail.status()['state'], 'not_connected')
                self.assertEqual(tool_calendar.status()['state'], 'not_connected')
                self.assertFalse((self.root / 'google_users' / 'bob').exists())
            finally:
                llm._key_context.reset(token)

    def test_readonly_tools_have_no_separate_job_to_cancel(self):
        with patch.object(requests_state, 'cancel') as cancel:
            for module in (tool_mail, tool_calendar):
                self.assertEqual(module.cancel(), {'cancelled': False, 'detail': 'Bu araç ayrı bir arka plan işi başlatmaz.'})
            cancel.assert_not_called()

    def test_symlink_record_is_error_and_missing_owner_is_not_connected(self):
        path = self.root / 'google_users' / 'alice'
        path.parent.mkdir()
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'token.json').write_text('fixture', encoding='utf-8')
        path.symlink_to(outside, target_is_directory=True)
        for module in (tool_mail, tool_calendar):
            with patch.object(module, '_record_failure') as record:
                self.assertEqual(module.status()['state'], 'error')
                record.assert_called_once()
        token = llm._key_context.set(None)
        try:
            self.assertEqual(tool_mail.status()['state'], 'not_connected')
        finally:
            llm._key_context.reset(token)


if __name__ == '__main__':
    unittest.main()
