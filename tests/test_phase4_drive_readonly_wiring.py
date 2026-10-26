import unittest
from unittest.mock import Mock, patch

from modules import account_tools, llm


class Phase4DriveReadonlyWiringTests(unittest.TestCase):
    def setUp(self):
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)

    def test_drive_list_uses_readonly_adapter_and_returns_receipt(self):
        drive = Mock()
        rows = [{'id': 'abc_123', 'name': 'Rapor', 'mime_type': 'text/plain'}]
        with patch('modules.drive_readonly.services', return_value=(drive, Mock(), Mock())) as services, \
             patch('modules.drive_readonly.list_files', return_value=rows) as listing, \
             patch.object(account_tools.privacy, 'blocked', return_value=None):
            result = account_tools.run('alice', {
                'service': 'drive', 'operation': 'list_files', 'query': 'rapor', 'limit': 5,
            })

        services.assert_called_once_with(interactive=False)
        listing.assert_called_once_with(drive, query='rapor', limit=5)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['snapshot']['items'], rows)


if __name__ == '__main__':
    unittest.main()
