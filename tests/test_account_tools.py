import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from modules import account_tools as accounts, task_agents as agents, task_results, google_api, llm, nxapi


class AccountToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        for module, name, subdir in ((agents, 'STORE', 'tasks'), (nxapi, 'FILES_DIR', 'files')):
            p = patch.object(module, name, Path(self.tmp.name) / subdir)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(accounts.privacy, 'blocked', return_value=None)
        p.start(); self.addCleanup(p.stop)
        self.messages = Mock()
        self.service = Mock()
        self.service.users.return_value.messages.return_value = self.messages
        self.messages.list.return_value.execute.return_value = {'messages': [{'id': 'm1'}]}
        self.messages.get.return_value.execute.return_value = {
            'id': 'm1', 'payload': {'headers': [{'name': 'from', 'value': 'Sender'},
                                                {'name': 'Subject', 'value': 'Hello'}]}}
        self.data = {'service': 'gmail', 'operation': 'list_unread', 'limit': 5}

    def read(self):
        with patch.object(google_api, '_service', return_value=self.service) as connect:
            output = accounts.run('alice', self.data)
            connect.assert_called_once_with('gmail', 'v1', interactive=False)
        return output

    def test_read_uses_metadata_and_never_mutates_mail(self):
        output = task_results.seal('account', self.read())
        self.assertTrue(task_results.verify(output, owner='alice'))
        self.messages.list.assert_called_once_with(userId='me', q='is:unread in:inbox', maxResults=5)
        self.messages.get.assert_called_once_with(userId='me', id='m1', format='metadata', metadataHeaders=['From', 'Subject'])
        self.assertEqual({c[0] for c in self.messages.method_calls}, {'list', 'get'})
        self.assertEqual(output['snapshot']['items'][0]['subject'], 'Hello')
        with self.assertRaises(PermissionError): task_results.verify(output, owner='bob')

    def test_empty_result_is_valid_and_pagination_is_explicit(self):
        self.messages.list.return_value.execute.return_value = {}
        output = task_results.seal('account', self.read())
        self.assertEqual(output['snapshot']['items'], [])
        self.messages.get.assert_not_called()
        self.messages.list.return_value.execute.return_value = {'messages': [], 'nextPageToken': 'private-page-token'}
        output = task_results.seal('account', self.read())
        self.assertTrue(output['snapshot']['has_more'])
        self.assertNotIn('private-page-token', str(output))

    def test_invalid_inputs_no_connection(self):
        bad = [{'limit': True}, {'limit': 0}, {'limit': 21}, {'limit': '5'},
               {'service': 'unknown'}, {'operation': []}, {'owner': 'bob'}]
        with patch.object(google_api, '_service') as connect:
            for extra in bad:
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    accounts.run('alice', {**self.data, **extra})
            connect.assert_not_called()

    def test_wrong_or_missing_execution_identity_cannot_connect(self):
        with patch.object(google_api, '_service') as connect:
            with self.assertRaises(PermissionError): accounts.run('bob', self.data)
            token = llm._key_context.set(None)
            try:
                with self.assertRaises(PermissionError): accounts.run('alice', self.data)
            finally: llm._key_context.reset(token)
            connect.assert_not_called()

    def test_privacy_and_unsupported_operation_do_not_connect(self):
        with patch.object(google_api, '_service') as connect:
            with patch.object(accounts.privacy, 'blocked', return_value='Web kapalı'):
                self.assertEqual(accounts.run('alice', self.data)['state'], 'blocked')
            for service in accounts.SERVICES:
                self.assertEqual(accounts.run('alice', {'service': service, 'operation': 'send'})['state'], 'unavailable')
            connect.assert_not_called()

    def test_missing_permission_does_not_open_login_or_claim_done(self):
        with patch.object(google_api, '_service', side_effect=PermissionError('secret')):
            output = accounts.run('alice', self.data)
        self.assertEqual(output['state'], 'unavailable')
        self.assertNotIn('secret', output['text'])
        self.assertNotIn('verification', task_results.seal('account', output))

    def test_incomplete_or_wrong_message_cannot_complete(self):
        for msg in ({'id': 'other'}, {'id': 'm1', 'payload': {'headers': [{'name': 'Subject', 'value': False}]}}):
            self.messages.get.return_value.execute.return_value = msg
            with self.assertRaises(ValueError): self.read()
        self.messages.list.return_value.execute.return_value = {'messages': [{'id': 'm1'}, {'id': 'm1'}]}
        with self.assertRaises(ValueError): self.read()

    def test_snapshot_change_is_rejected_on_resume_without_api_call(self):
        with patch.object(google_api, '_service', return_value=self.service):
            job = agents.execute('alice', [{'id': 'mail', 'agent': 'account', 'input': self.data}])
        self.assertEqual(job['state'], 'done')
        job['outputs']['mail']['snapshot']['items'][0]['subject'] = 'changed'
        agents._save(agents._root('alice'), job)
        with patch.object(google_api, '_service') as connect:
            with self.assertRaises(ValueError): agents.continue_job('alice', job['id'])
            connect.assert_not_called()

    def test_result_text_and_timestamp_are_validated(self):
        output = task_results.seal('account', self.read())
        changed = copy.deepcopy(output)
        changed['text'] = 'Model says something else'
        with self.assertRaises(ValueError): task_results.verify(changed)
        for timestamp in (float('nan'), float('inf'), False, -1):
            changed = copy.deepcopy(output)
            changed['snapshot']['fetched_at'] = timestamp
            changed['sha256'] = accounts.digest(changed['snapshot'])
            with self.assertRaises(ValueError): task_results.verify(changed)

    def test_mail_writer_verify_chain_and_resume_without_rereading(self):
        tasks = [{'id': 'mail', 'agent': 'account', 'input': self.data},
                 {'id': 'report', 'agent': 'writer', 'depends': ['mail'], 'input': {'instruction': 'Özetle'}},
                 {'id': 'check', 'agent': 'verify', 'depends': ['mail', 'report']}]
        with patch.object(google_api, '_service', return_value=self.service), patch.object(llm, 'ask', return_value='Mail raporu') as ask:
            job = agents.execute('alice', tasks)
        self.assertEqual(job['state'], 'approval')
        ask.assert_not_called()  # The model is not run before file consent.
        self.assertEqual(job['tasks'][0]['state'],'done')
        self.assertEqual(job['tasks'][1]['state'],'approval')
        self.assertEqual(job['tasks'][2]['state'],'queued')
        self.assertEqual(job['tasks'][0]['execution']['risk'], 'account_read')
        with patch.object(google_api, '_service') as connect:
            self.assertEqual(agents.continue_job('alice', job['id'])['state'], 'approval')
            connect.assert_not_called()

    def test_direct_command_and_capabilities_do_not_call_model(self):
        with patch.object(llm, 'ask') as ask, patch.object(google_api, '_service', return_value=self.service):
            self.assertIn('done', agents.handle('alice', 'görev mail oku'))
            self.assertIn('list_unread', agents.handle('alice', 'hesap bağlantıları'))
            ask.assert_not_called()


if __name__ == '__main__': unittest.main()
