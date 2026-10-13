import base64
import copy
import unittest
from unittest.mock import Mock,patch
from modules import account_tools,mail_attachments,mail_content,google_api,llm,task_results


class MailAttachmentTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        privacy=patch.object(account_tools.privacy,'blocked',return_value=None);privacy.start();self.addCleanup(privacy.stop)
        self.messages=Mock();self.svc=Mock();self.svc.users.return_value.messages.return_value=self.messages
        p=patch.object(google_api,'_service',return_value=self.svc);self.service=p.start();self.addCleanup(p.stop)
        self.raw=b'hello attachment'
        self.part={'filename':'note.txt','mimeType':'text/plain','body':{'size':len(self.raw),'attachmentId':'A1'}}
        self.messages.get.return_value.execute.side_effect=lambda:{'id':'M1','payload':{'mimeType':'multipart/mixed','parts':[self.part]}}
        self.messages.attachments.return_value.get.return_value.execute.side_effect=lambda:{'data':base64.urlsafe_b64encode(self.raw).decode()}

    def read(self,operation='read_attachment'):
        data={'service':'gmail','operation':operation,'message_id':'M1'}
        if operation=='read_attachment':data['attachment_index']=1
        return task_results.seal('account',account_tools.run('alice',data))

    def test_listing_is_metadata_only_and_verifiable(self):
        result=self.read('list_attachments')
        self.messages.attachments.assert_not_called()
        self.assertEqual(result['snapshot']['items'][0]['filename'],'note.txt')
        self.assertTrue(task_results.verify(result,owner='alice'))

    def test_remote_and_inline_text_reads_are_verified(self):
        for inline in (False,True):
            if inline:self.part['body']['data']=base64.urlsafe_b64encode(self.raw).decode()
            result=self.read();self.assertIn('hello attachment',result['text'])
            self.assertTrue(task_results.verify(result,owner='alice'))

    def test_unsupported_or_oversized_attachment_is_not_downloaded(self):
        for name,mime,size in [('x.exe','application/octet-stream',12),('x.html','text/html',12),('x.txt','text/plain',mail_attachments.MAX_BYTES+1)]:
            self.part.update(filename=name,mimeType=mime);self.part['body']['size']=size
            result=self.read();self.assertEqual(result['state'],'unavailable')
        self.messages.attachments.assert_not_called()

    def test_size_mismatch_binary_or_empty_data_is_not_success(self):
        for raw in (b'x',b'\0'*len(self.raw),b' '*len(self.raw)):
            self.raw=raw
            with self.assertRaises(ValueError):self.read()

    def test_long_text_is_explicitly_truncated(self):
        self.raw=b'x'*(mail_content.MAX_TEXT+1);self.part['body']['size']=len(self.raw)
        result=self.read();self.assertTrue(result['snapshot']['attachment']['truncated'])
        self.assertIn('tamamı okunmadı',result['text'])

    def test_owner_privacy_and_tampered_evidence(self):
        result=self.read();altered=copy.deepcopy(result);altered['text']='fake'
        with self.assertRaises(ValueError):task_results.verify(altered,owner='alice')
        with self.assertRaises(PermissionError):task_results.verify(result,owner='bob')
        with self.assertRaises(PermissionError):account_tools.run('bob',{'service':'gmail','operation':'list_attachments','message_id':'M1'})
        self.service.reset_mock()
        with patch.object(account_tools.privacy,'blocked',return_value='blocked'):
            self.assertEqual(account_tools.run('alice',{'service':'gmail','operation':'list_attachments','message_id':'M1'})['state'],'blocked')
        self.service.assert_not_called()

    def test_bad_mime_and_selection_are_rejected(self):
        deep={'parts':[]}
        for _ in range(18):deep={'parts':[deep]}
        with self.assertRaises(ValueError):mail_attachments.parts(deep)
        for index in (0,21,True):
            with self.assertRaises(ValueError):account_tools.validate_input({'service':'gmail','operation':'read_attachment','message_id':'M1','attachment_index':index})
