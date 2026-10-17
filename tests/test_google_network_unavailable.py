import unittest
from unittest.mock import patch

from modules import acceptance_checks, account_tools, google_api, llm


class ServerNotFoundError(Exception):
    pass


class GoogleNetworkUnavailableTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset,token)

    def test_server_not_found_is_transient_network(self):
        exc=ServerNotFoundError('Unable to find the server at www.googleapis.com')
        self.assertTrue(account_tools._network_unavailable(exc))

    def test_gmail_network_failure_is_unavailable_not_exception(self):
        exc=ServerNotFoundError('Unable to find the server at www.googleapis.com')
        with patch.object(account_tools.privacy,'blocked',return_value=None),patch.object(google_api,'_service',side_effect=exc):
            result=account_tools.run('alice',{'service':'gmail','operation':'list_unread','limit':5})
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(result['service'],'gmail')
        self.assertIn('ağ/DNS',result['text'])
        self.assertNotIn('ServerNotFoundError',result['text'])

    def test_gmail_acceptance_marks_network_unavailable_as_pending(self):
        result={'state':'unavailable','text':'Gmail şu anda Google sunucularına ağ/DNS üzerinden ulaşamıyor.'}
        with patch.object(account_tools,'run',return_value=result):
            state,detail=acceptance_checks._gmail_attachment('alice')
        self.assertEqual(state,'pending')
        self.assertIn('bağlantı/izin',detail)

    def test_non_network_error_still_propagates(self):
        with patch.object(account_tools.privacy,'blocked',return_value=None),patch.object(google_api,'_service',side_effect=ValueError('bozuk yanıt')):
            with self.assertRaisesRegex(ValueError,'bozuk yanıt'):
                account_tools.run('alice',{'service':'gmail','operation':'list_unread','limit':5})


if __name__=='__main__':
    unittest.main()
