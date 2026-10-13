import base64
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from modules import mail_content as content, account_tools as accounts, task_agents as agents, task_results, google_api, llm, nxapi


def part(text, mime='text/plain', charset='utf-8', **extra):
    return {'mimeType': mime, 'headers': [{'name': 'Content-Type', 'value': mime+'; charset='+charset}],
            'body': {'data': base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip('=')}, **extra}


class MimeTests(unittest.TestCase):
    def test_plain_preferred_and_text_attachment_excluded(self):
        payload={'mimeType':'multipart/mixed','parts':[{'mimeType':'multipart/alternative','parts':[
            part('<p>HTML duplicate</p>','text/html'),part('Düz metin')]},part('attachment','text/plain',filename='a.txt')]}
        self.assertEqual(content.extract(payload),{'body':'Düz metin','format':'plain','truncated':False})

    def test_html_is_text_not_executable_and_charset_decodes(self):
        output=content.extract(part('<head><style>bad</style></head><p>Merhaba &amp; dünya</p><script>evil()</script><img src="https://track.test">','text/html'))
        self.assertEqual(output['body'],'Merhaba & dünya')
        self.assertEqual(output['format'],'html_text')
        self.assertEqual(content.extract(part('Türkçe','text/plain','iso-8859-9'))['body'],'Türkçe')

    def test_long_body_is_explicitly_truncated(self):
        output=content.extract(part('x'*(content.MAX_TEXT+1)))
        self.assertEqual(len(output['body']),content.MAX_TEXT)
        self.assertTrue(output['truncated'])

    def test_malformed_missing_attachment_only_and_deep_mime_fail(self):
        deep=part('x')
        for _ in range(18):deep={'mimeType':'multipart/mixed','parts':[deep]}
        cases=[{},part('text',filename='a.txt'),{'mimeType':'text/plain','body':{'attachmentId':'not_downloaded'}},
               {'mimeType':'text/plain','body':{'data':'!!!'}},deep,
               {'mimeType':'text/plain','body':{'data':'x'*(content.MAX_ENCODED+1)}}]
        for payload in cases:
            with self.subTest(payload=str(payload)[:60]),self.assertRaises(ValueError):content.extract(payload)


class MailReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        for mod,name,sub in ((agents,'STORE','tasks'),(nxapi,'FILES_DIR','files')):
            p=patch.object(mod,name,Path(self.tmp.name)/sub);p.start();self.addCleanup(p.stop)
        p=patch.object(accounts.privacy,'blocked',return_value=None);p.start();self.addCleanup(p.stop)
        self.messages=Mock();self.svc=Mock();self.svc.users.return_value.messages.return_value=self.messages
        payload=part('Please reply about meeting.')
        payload['headers'] += [{'name':'From','value':'sender@example.com'},{'name':'Subject','value':'Meeting'}]
        self.messages.get.return_value.execute.return_value={'id':'M1','payload':payload}
        self.data={'service':'gmail','operation':'read_message','message_id':'M1'}

    def read(self):
        with patch.object(google_api,'_service',return_value=self.svc):return task_results.seal('account',accounts.run('alice',self.data))

    def test_full_read_does_not_modify_or_fetch_attachments(self):
        out=self.read();self.assertTrue(task_results.verify(out,owner='alice'))
        self.messages.get.assert_called_once_with(userId='me',id='M1',format='full')
        self.assertEqual({call[0] for call in self.messages.method_calls},{'get'})
        self.assertIn('Please reply',out['text'])

    def test_no_snippet_fallback_wrong_id_or_body_can_complete(self):
        for msg in ({'id':'wrong','payload':part('body')},{'id':'M1','payload':{},'snippet':'partial only'}):
            self.messages.get.return_value.execute.return_value=msg
            with self.assertRaises(ValueError):self.read()

    def test_message_selection_schema_rejected_before_api(self):
        cases=[{}, {'message_id':'../other'}, {'message_id':False},{'message_id':'M1','index':1},
               {'index':True},{'index':0},{'index':21},{'message_id':'M1','limit':5}]
        with patch.object(google_api,'_service') as connect:
            for selection in cases:
                with self.assertRaises(ValueError):accounts.run('alice',{'service':'gmail','operation':'read_message',**selection})
            connect.assert_not_called()

    def test_index_uses_verified_owner_list_and_cannot_invent_id(self):
        snap={'owner':'alice','service':'gmail','operation':'list_unread','fetched_at':1,
              'query':'is:unread in:inbox','limit':5,'items':[{'id':'M1','from':'sender','subject':'subject'}],'has_more':False}
        listed=task_results.seal('account',{'state':'done','snapshot':snap,'sha256':accounts.digest(snap),'text':accounts.render_snapshot(snap)})
        self.assertEqual(listed['text'],'Listelenen okunmamış mail başlıkları:\nsender: subject')
        self.assertTrue(task_results.verify(listed,owner='alice'))
        data={'service':'gmail','operation':'read_message','index':1}
        with patch.object(google_api,'_service',return_value=self.svc):
            self.assertEqual(accounts.run('alice',data,{'list':listed})['state'],'done')
        self.messages.get.assert_called_once_with(userId='me',id='M1',format='full')
        with patch.object(google_api,'_service') as connect:
            for deps in ({},{'a':listed,'b':listed}):
                with self.assertRaises(ValueError):accounts.run('alice',data,deps)
            with self.assertRaises(ValueError):accounts.run('alice',{**data,'index':2},{'a':listed})
            altered=copy.deepcopy(listed);altered['snapshot']['items'][0]['id']='madeup'
            with self.assertRaises(ValueError):accounts.run('alice',data,{'a':altered})
            connect.assert_not_called()

    def test_changed_saved_body_stops_resume_without_reread(self):
        with patch.object(google_api,'_service',return_value=self.svc):
            job=agents.execute('alice',[{'id':'mail','agent':'account','input':self.data}])
        job['outputs']['mail']['snapshot']['message']['body']='changed';agents._save(agents._root('alice'),job)
        with patch.object(google_api,'_service') as connect:
            with self.assertRaises(ValueError):agents.continue_job('alice',job['id'])
            connect.assert_not_called()

    def test_direct_reply_command_creates_local_file_without_send_or_model_plan(self):
        with patch.object(google_api,'_service',return_value=self.svc),patch.object(llm,'ask',return_value='Yerel cevap taslağı; gönderilmedi.') as ask:
            result=agents.handle('alice','Görev mail taslak M1')
        self.assertIn('done',result);self.assertEqual(ask.call_count,1)
        job=agents.recent('alice');self.assertEqual(job['state'],'done')
        self.assertTrue(Path(job['outputs']['reply']['file']).is_file())
        self.assertEqual({call[0] for call in self.messages.method_calls},{'get'})
        self.assertIn('Please reply',ask.call_args.args[0])
        self.assertIn('talimat',ask.call_args.kwargs['system'])

    def test_first_unread_reply_selects_real_list_id_and_stops_if_empty(self):
        self.messages.list.return_value.execute.return_value={'messages':[{'id':'M1'}]}
        with patch.object(google_api,'_service',return_value=self.svc),patch.object(llm,'ask',return_value='Cevap taslağı') as ask:
            self.assertIn('done',agents.handle('alice','görev ilk mail taslak'))
            self.assertEqual(ask.call_count,1)
        calls=self.messages.get.call_args_list
        self.assertEqual(calls[-1].kwargs,{'userId':'me','id':'M1','format':'full'})
        self.messages.get.reset_mock()
        self.messages.list.return_value.execute.return_value={}
        with patch.object(google_api,'_service',return_value=self.svc),patch.object(llm,'ask') as ask:
            self.assertIn('incomplete',agents.handle('alice','görev ilk mail taslak'))
            ask.assert_not_called();self.messages.get.assert_not_called()


if __name__=='__main__':unittest.main()
