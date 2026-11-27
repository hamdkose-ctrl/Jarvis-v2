"""Durability and provider capability regressions without external services."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import config
from modules import browser_agent as browser, task_agents as agents, docs, study, nxapi
from modules import personalization, smart_router as router, llm, goal_executor, resource_leases


class DurableWorkTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        # (T3d) Bu sınıf gerçek ~/.jarvis'e bakmaz: sağlayıcı seçimi/yerel model okuması
        # kullanıcının kendi ayarlarından gelirse sağlık anahtarı ve kota yolu ortam
        # bağımlı oluyordu (JARVIS_DATA_DIR yokken 2 FAIL). Veri kökü geçici klasördür.
        data=self.root/'data'
        self.enterContext(patch.dict(os.environ, {'JARVIS_DATA_DIR': str(data)}))
        from modules import user_models
        self.enterContext(patch.object(config, 'DATA_DIR', data))
        self.enterContext(patch.object(config, 'SETTINGS_FILE', data/'settings.json'))
        self.enterContext(patch.object(config, '_cache', {'key': None, 'text': '{}'}))
        self.enterContext(patch.object(user_models, 'DATA_DIR', data))
        self.enterContext(patch.object(router, '_STORE', data/'router'))
        self.enterContext(patch.object(goal_executor, 'STORE', data/'goals'))
        for obj,name,value in [(agents,'STORE',self.root/'tasks'),(browser,'STORE',self.root/'browser'),
                              (nxapi,'FILES_DIR',self.root/'files'),(study,'ROOT',self.root/'study')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    def test_durable_job_records_artifact_and_running_step_before_abrupt_interruption(self):
        # Aşama C: süreklilik ölçümü eski tarayıcı onay tüketicisine dayanmaz;
        # aynı kayıtlı görev yürütücüsü tek çalışmada sınanır.
        tasks=[{'id':'write','agent':'research','input':{'url':'https://example.org/report'}},
               {'id':'verify','agent':'verify','depends':['write']}]
        original=agents.worker
        snapshots=[]
        def worker(owner,task,deps):
            saved=json.loads(next(agents._root(owner).glob('*.json')).read_text())
            snapshots.append(saved)
            if task['id']=='verify':raise KeyboardInterrupt('simulated process interruption')
            if task['id']=='write':
                path=self.root/'files'/'rapor.md';path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('Kaydedilmiş rapor')
                return {'state':'done','text':'Kaydedilmiş rapor','file':str(path),
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            return original(owner,task,deps)
        with patch.object(agents.llm,'ask',side_effect=AssertionError('No model in durability')), \
             patch.object(agents,'worker',side_effect=worker):
            with self.assertRaises(KeyboardInterrupt):agents.execute('alice',tasks)
        self.assertEqual(snapshots[0]['tasks'][0]['state'],'running')
        self.assertEqual(snapshots[1]['tasks'][1]['state'],'running')
        saved=agents.recent('alice')
        self.assertEqual(saved['tasks'][0]['state'],'done')
        output=saved['outputs']['write']
        self.assertEqual(output['text'],'Kaydedilmiş rapor')
        self.assertEqual(Path(output['file']).read_text(),'Kaydedilmiş rapor')
        self.assertEqual(saved['tasks'][1]['state'],'interrupted')

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
        from modules import model_capabilities
        facts={("http://ollama.invalid","text-only"):{'features':frozenset({'verified_vision'}),'context_limit':None,'output_limit':None,'expires_at':__import__('time').time()+300}}
        with patch.object(model_capabilities,'_LOCAL_FACTS',facts),patch.object(router,'_HEALTH',{}),             patch.object(router,'settings',return_value={'gemini_scopes': []}), \
             patch.object(router.privacy,'mode',return_value='normal'), \
             patch.object(llm,'provider',return_value='auto'),patch.object(llm,'current_user',return_value='alice'), \
             patch.object(llm,'_cfg',return_value={'url':'http://ollama.invalid','model':'text-only'}), \
             patch.object(llm,'ollama_models',return_value=['text-only']), \
             patch.object(llm.requests,'post',side_effect=[unsupported,successful]) as post:
            with self.assertRaises(RuntimeError):llm.ask_image(str(image),'görseli anlat',strict=True)
            self.assertIn('ollama',router.candidates('alice','chat'))
            self.assertEqual(llm.ask('merhaba'),'metin cevabı')
            self.assertEqual(post.call_count,2)

    def test_image_connection_or_quota_error_still_cools_provider(self):
        # Exercise a *real attempted* adapter failure, not a preflight rejection
        # from another test's quota database or scheduler/provider lease. A
        # preflight rejection never calls the provider and must not cool it.
        for error in (llm.LocalModelError('connection failed'),llm.CloudError('quota')):
            adapter = Mock(side_effect=error)
            with self.subTest(error=type(error).__name__), \
                 patch.object(llm, '_ollama_effective_model', return_value='local-test'), \
                 patch.object(router, '_HEALTH', {}), \
                 patch.object(router, '_STORE', self.root / 'router'), \
                 patch.object(goal_executor, '_RESOURCE_LEASES', resource_leases.LeaseTable()), \
                 patch.object(router, 'settings', return_value={'gemini_scopes': []}), \
                 patch.object(router.privacy, 'mode', return_value='normal'):
                request = router.ModelRequest(owner='alice', profile='conversation',
                                              max_network_attempts=1)
                with self.assertRaises(RuntimeError):
                    router.run_request(request, adapter)
                adapter.assert_called_once()
                self.assertEqual(adapter.call_args.args[0].provider, 'ollama')
                self.assertGreater(router._health_wait('alice', 'ollama', 'local-test'), 0)
                self.assertNotIn('ollama', router.candidates('alice', 'chat'))
