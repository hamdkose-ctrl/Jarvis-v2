"""Durability and provider capability regressions without external services."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from modules import browser_agent as browser, task_agents as agents, docs, study, nxapi
from modules import personalization, smart_router as router, llm


class DurableWorkTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        for obj,name,value in [(agents,'STORE',self.root/'tasks'),(browser,'STORE',self.root/'browser'),
                              (nxapi,'FILES_DIR',self.root/'files'),(study,'ROOT',self.root/'study')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    def test_resume_records_report_and_running_step_before_abrupt_interruption(self):
        tasks=[{'id':'browse','agent':'browser'},
               {'id':'write','agent':'writer','depends':['browse'],'input':{'instruction':'write','filename':'rapor.md'}},
               {'id':'verify','agent':'verify','depends':['write']}]
        with patch.object(agents,'worker',return_value={'state':'approval','id':'approval'}):
            agents.execute('alice',tasks)
        original=agents.worker
        snapshots=[]
        def worker(owner,task,deps):
            saved=json.loads(next(agents._root(owner).glob('*.json')).read_text())
            snapshots.append(saved)
            if task['id']=='verify':raise KeyboardInterrupt('simulated process interruption')
            return original(owner,task,deps)
        image=self.root/'screen.png';image.write_bytes(b'test screenshot')
        with patch.object(browser,'run',return_value={'state':'done','text':'browser done','steps':[{'op':'read','verified':True}], 'page':{'url':'https://example.com'},'image':str(image)}), \
             patch.object(agents.llm,'ask',return_value='Kaydedilmiş rapor'),patch.object(agents,'worker',side_effect=worker):
            with self.assertRaises(KeyboardInterrupt):agents.resume('alice','approval')
        self.assertEqual(snapshots[0]['tasks'][1]['state'],'running')
        self.assertEqual(snapshots[1]['tasks'][2]['state'],'running')
        saved=agents.recent('alice')
        self.assertEqual(saved['tasks'][1]['state'],'done')
        output=saved['outputs']['write']
        self.assertEqual(output['text'],'Kaydedilmiş rapor')
        self.assertEqual(Path(output['file']).read_text(),'Kaydedilmiş rapor')
        self.assertEqual(saved['tasks'][2]['state'],'interrupted')

    def test_pdf_subprocess_timeout_never_calls_inline_reader(self):
        profile=SimpleNamespace(slug='alice',data={},save=Mock(),_new_id=lambda:1)
        with patch.object(subprocess,'run',side_effect=subprocess.TimeoutExpired('pdf reader',900)), \
             patch.object(study,'_read_pdf_inline',return_value='incorrect unlimited fallback') as inline:
            with self.assertRaisesRegex(ValueError,'süre'):
                study._add(profile,str(self.root/'book.pdf'))
        inline.assert_not_called();profile.save.assert_not_called()

    def test_due_reminder_disk_failure_retries_and_preserves_existing_flags(self):
        profile=personalization.Profile('Alice');profile.path=self.root/'alice.json'
        old={'id':1,'title':'old','when':'2026-10-09T08:00','notified':True}
        timed={'id':2,'title':'timed','when':'2026-10-09T09:00','notified':False}
        whole_day={'id':3,'title':'day','when':'2026-10-09'}
        future={'id':4,'title':'future','when':'2026-10-10','notified':False}
        profile.data['events']=[old,timed,whole_day,future]
        profile.save();before=profile.path.read_bytes()
        with patch.object(personalization.os,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):profile.due_events(datetime(2026,10,9,10))
        self.assertFalse(timed.get('notified', False));self.assertNotIn('notified',whole_day)
        self.assertTrue(old['notified']);self.assertFalse(future['notified'])
        self.assertEqual(profile.path.read_bytes(),before)
        self.assertEqual([e['id'] for e in profile.due_events(datetime(2026,10,9,10))],[2,3])
        self.assertEqual(profile.due_events(datetime(2026,10,9,10)),[])
        saved=json.loads(profile.path.read_text())
        self.assertTrue(saved['events'][1]['notified']);self.assertTrue(saved['events'][2]['notified'])

    def test_real_ollama_image_capability_error_leaves_text_provider_available(self):
        image=self.root/'image.png';image.write_bytes(b'fake image')
        unsupported=Mock(status_code=400)
        unsupported.json.return_value={'error':'model does not support images'}
        successful=Mock(status_code=200);successful.json.return_value={'message':{'content':'metin cevabı'}}
        with patch.object(router,'_HEALTH',{}),patch.object(router,'_LAST',{}), \
             patch.object(router,'settings',return_value={'cloud_free_confirmed':False,'key':''}), \
             patch.object(router.privacy,'mode',return_value='normal'), \
             patch.object(llm,'provider',return_value='auto'),patch.object(llm,'current_user',return_value='alice'), \
             patch.object(llm,'_cfg',return_value={'url':'http://ollama.invalid','model':'text-only'}), \
             patch.object(llm,'ollama_models',return_value=['text-only']), \
             patch.object(llm.requests,'post',side_effect=[unsupported,successful]) as post:
            with self.assertRaises(RuntimeError):llm.ask_image(str(image),'görseli anlat')
            self.assertIn('ollama',router.candidates('alice','chat'))
            self.assertEqual(llm.ask('merhaba'),'metin cevabı')
            self.assertEqual(post.call_count,2)

    def test_image_connection_or_quota_error_still_cools_provider(self):
        for error in (llm.LocalModelError('connection failed'),llm.CloudError('quota')):
            with self.subTest(error=type(error).__name__),patch.object(llm, '_ollama_effective_model', return_value='local-test'), patch.object(router,'_HEALTH',{}), \
                 patch.object(router,'settings',return_value={'cloud_free_confirmed':False,'key':''}), \
                 patch.object(router.privacy,'mode',return_value='normal'):
                with self.assertRaises(RuntimeError):router.run('alice','image',Mock(side_effect=error),image=True)
                self.assertNotIn('ollama',router.candidates('alice','chat'))
