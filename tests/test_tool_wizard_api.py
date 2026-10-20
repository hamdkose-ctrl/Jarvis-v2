import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import capability_hub, llm, permission_policy, service_store, tool_contract, tool_map, tool_wizard


class WizardApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        for module, directory in ((tool_wizard, 'wizard'), (service_store, 'db'), (permission_policy, 'policy')):
            p = patch.object(module, 'ROOT', Path(self.tmp.name) / directory)
            p.start()
            self.addCleanup(p.stop)
        body = b'# Data\n| [Weather](https://example.com/weather) | weather data |'
        with patch.object(capability_hub.public_sources, 'fetch', return_value={'body': body}):
            result = tool_wizard.discover('alice', 'weather')
        self.ident = result['candidates'][0]['id']

    def add(self, confirmed=False):
        return tool_wizard.add_api('alice', self.ident, 'https://example.com/weather', {'city': 'string'}, confirmed=confirmed)

    def test_approval_then_contract_loaded_in_harita_for_owner_only(self):
        preview = self.add()
        self.assertEqual(preview['state'], 'approval')
        self.assertEqual(tool_wizard.contracts('alice'), {})
        result = self.add(True)
        self.assertEqual(result['state'], 'done')
        ident = result['id']
        loaded = tool_contract.load_all()
        self.assertIn(ident, loaded)
        self.assertEqual(tool_contract.validate(loaded[ident]), [])
        description = tool_contract.describe(loaded[ident])
        self.assertEqual({a['class'] for a in description['actions']}, {'read'})
        json.dumps(description)
        self.assertIn(ident, {t['id'] for t in tool_map.snapshot('alice')['tools']})
        token = llm._key_context.set('bob')
        try:
            self.assertNotIn(ident, tool_contract.load_all())
            self.assertEqual(tool_wizard.execute('bob', ident, {'city': 'Ankara'})['state'], 'blocked')
            self.assertEqual(loaded[ident]['status']()['state'], 'error')
        finally:
            llm._key_context.reset(token)

    def test_execution_gate_policy_and_invalid_parameters(self):
        ident = self.add(True)['id']
        response = {'data': {'ok': True}}
        with patch.object(capability_hub, 'read', return_value=response) as read:
            self.assertEqual(tool_wizard.execute('alice', ident, {'city': 'Ankara'})['data'], response)
            read.assert_called_once_with('alice', self.ident, {'city': 'Ankara'})
            read.reset_mock()
            permission_policy.set('alice', ident, 'read', 'deny')
            self.assertEqual(tool_wizard.execute('alice', ident, {}, approve=True)['state'], 'blocked')
            read.assert_not_called()
        permission_policy.set('alice', ident, 'read', 'ask')
        with patch.object(permission_policy, 'apply', side_effect=OSError('fake')), patch.object(capability_hub, 'read') as read:
            self.assertEqual(tool_wizard.execute('alice', ident, {})['state'], 'blocked')
            read.assert_not_called()
        with patch.object(capability_hub.public_sources, 'fetch') as fetch:
            self.assertEqual(tool_wizard.execute('alice', ident, {'unknown': 'x'})['state'], 'blocked')
            fetch.assert_not_called()

    def test_locked_and_private_endpoints_cannot_be_registered(self):
        with self.assertRaises(ValueError):
            self.add('yes')
        for endpoint in ('http://localhost', 'https://127.0.0.1', 'https://example.com/delete'):
            with self.assertRaises(ValueError):
                tool_wizard.add_api('alice', self.ident, endpoint, {}, confirmed=True)
        with self.assertRaises(ValueError):
            tool_wizard.add_api('alice', self.ident, 'https://example.com', {'token': 'string'}, confirmed=True)
        self.assertEqual(tool_wizard.contracts('alice'), {})

    def test_corrupt_registry_fails_closed_and_loader_rejects_duplicate(self):
        ident = self.add(True)['id']
        path = tool_wizard.ROOT / 'alice.json'
        original = path.read_bytes()
        path.write_text('broken')
        with patch.object(capability_hub, 'read') as read:
            self.assertEqual(tool_wizard.execute('alice', ident, {})['state'], 'blocked')
            self.assertNotIn(ident, tool_contract.load_all())
            read.assert_not_called()
        path.write_bytes(original)
        contract = tool_wizard.contracts('alice')[ident]
        duplicate = {**contract, 'id': 'mail'}
        with patch.object(tool_wizard, 'contracts', return_value={'mail': duplicate}):
            self.assertNotIn('mail', tool_contract.load_all())


if __name__ == '__main__':
    unittest.main()
