import base64
import unittest
from unittest.mock import Mock, patch
from modules import account_tools, llm, task_results
from tests import test_mail_attachments as _fixtures

class MailFollowupIntegrationTests(unittest.TestCase):
    setUp = _fixtures.MailAttachmentTests.setUp
    read = _fixtures.MailAttachmentTests.read

    def test_read_without_attachments_returns_verified_empty_list(self):
        self.messages.get.return_value.execute.side_effect=lambda:{'id':'M1','payload':{'mimeType':'text/plain','body':{'data':'aGVsbG8='}}}
        result=self.read()
        self.assertEqual(result['state'],'done')
        self.assertEqual(result['snapshot']['items'],[])
        self.assertIn('Ek yok.',result['text'])
        self.assertTrue(task_results.verify(result,owner='alice'))
        self.messages.attachments.assert_not_called()

    def test_empty_attachment_followup_finishes_without_resume_prompt(self):
        import tempfile
        from pathlib import Path
        from modules import task_agents
        self.messages.get.return_value.execute.side_effect=lambda:{'id':'M1','payload':{'mimeType':'text/plain','body':{'data':'aGVsbG8='}}}
        self.messages.list.return_value.execute.return_value={'messages':[{'id':'M1'}]}
        with tempfile.TemporaryDirectory() as folder,patch.object(task_agents,'STORE',Path(folder)),patch.object(llm,'ask',side_effect=AssertionError('no model')):
            task_agents.handle('alice','İlk mailin eklerini göster')
            result=task_agents.handle('alice','İlk ekini oku')
            self.assertIn('ek yok.',result)
            self.assertNotIn('Sürdürmek için',result)
            self.assertEqual(task_agents.recent('alice')['state'],'done')

    def test_followup_keeps_displayed_mail_when_inbox_changes(self):
        import tempfile
        from pathlib import Path
        from modules import task_agents
        self.messages.list.return_value.execute.return_value={'messages':[{'id':'M1'}]}
        with tempfile.TemporaryDirectory() as folder,patch.object(task_agents,'STORE',Path(folder)),patch.object(llm,'ask',side_effect=AssertionError('no model')):
            task_agents.handle('alice','görev mail oku')
            self.messages.list.reset_mock()
            self.messages.list.return_value.execute.return_value={'messages':[{'id':'M2'}]}
            self.assertIn('note.txt',task_agents.handle('alice','İlk mailin eklerini göster!'))
            self.assertIn('hello attachment',task_agents.handle('alice','İlk   ekini oku.'))
            self.assertIn('hello attachment',task_agents.handle('alice','ilk eki oku'))
            self.messages.list.assert_not_called()
            self.messages.attachments.return_value.get.assert_called_with(userId='me',messageId='M1',id='A1')

    def test_dispatch_short_read_followup_uses_gmail(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from test_mail_calendar_fixes import _runtime
        from brain_turn_fixture import turn
        from datetime import datetime
        from modules import task_agents
        self.messages.list.return_value.execute.return_value={'messages':[{'id':'M1'}]}
        context=_runtime(self, SimpleNamespace(slug='alice', name='Alice', data={'prefs': {}}), datetime.now())
        with tempfile.TemporaryDirectory() as folder,patch.object(task_agents,'STORE',Path(folder)),patch.object(llm,'ask',side_effect=AssertionError('no model')):
            result=turn(context, 'İlk ekini oku!', 'mail.read', {'source': 'first_attachment_read'})
            self.assertIn('hello attachment',result)
