"""Continuation checks: owner isolation and bounded non-blocking read-only UI work."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_engine_modular as fixtures
from modules import user_models, ui_jobs, phone
from modules.response_waiters import ResponseWaiters

class FollowupReviewTests(unittest.TestCase):
    def test_model_preferences_are_per_owner(self):
        with tempfile.TemporaryDirectory() as td, patch.object(user_models,'DATA_DIR',Path(td)):
            user_models.save('hamdi',['main-h','fallback-h'])
            user_models.save('ebru',['main-e'])
            self.assertEqual(user_models.get('hamdi',['default']),['main-h','fallback-h'])
            self.assertEqual(user_models.get('ebru',['default']),['main-e'])
            self.assertEqual(user_models.get('new',['default']),['default'])
            with self.assertRaises(ValueError):user_models.save('../escape',['main'])

    def test_corrupt_models_preserve_record_and_use_defaults(self):
        with tempfile.TemporaryDirectory() as td, patch.object(user_models,'DATA_DIR',Path(td)):
            p=Path(td)/'models'/'hamdi.json';p.parent.mkdir();p.write_text('{bad')
            self.assertEqual(user_models.get('hamdi',['default']),['default'])
            self.assertEqual(p.read_text(),'{bad')

    def test_jobs_return_before_operation_and_isolate_results(self):
        gate=threading.Event();entered=threading.Event()
        def operation():entered.set();gate.wait(2);return {'path':'example'}
        try:
            job=ui_jobs.start('test-owner','folder-test',operation)['job']
            self.assertTrue(entered.wait(1))
            self.assertIn(ui_jobs.status('test-owner',job)['state'],('queued','running'))
            self.assertEqual(ui_jobs.start('test-owner','folder-test',operation)['job'],job)
            with self.assertRaises(ValueError):ui_jobs.status('another-owner',job)
        finally:gate.set()
        for _ in range(100):
            result=ui_jobs.status('test-owner',job)
            if result['state']=='done':break
            time.sleep(.01)
        self.assertEqual(result,{'state':'done','data':{'path':'example'}})

    def test_reply_isolation_and_subscription_cleanup(self):
        service=ResponseWaiters()
        with service.subscribe('hamdi','rid') as a, service.subscribe('ebru','rid') as b:
            service.publish('hamdi','bbbbbbbbbbbbbbbbbbbbbbbb','wrong')
            service.publish('hamdi','rid','aaaaaaaaaaaaaaaaaaaaaaaa')
            service.publish('hamdi','rid','duplicate')
            self.assertEqual(a.get_nowait(),'aaaaaaaaaaaaaaaaaaaaaaaa');self.assertTrue(b.empty())
            service.publish('ebru','rid','second');self.assertEqual(b.get_nowait(),'second')
        self.assertEqual(service._waiting,{})
        with self.assertRaises(RuntimeError):
            with service.subscribe('hamdi','rid'):raise RuntimeError('interruption')
        self.assertEqual(service._waiting,{})

    def test_token_cache_reloads_on_replace_and_does_not_return_shared_dict(self):
        with tempfile.TemporaryDirectory() as td, patch.object(phone,'USER_TOKENS_FILE',Path(td)/'tokens.json'):
            p=phone.USER_TOKENS_FILE;p.write_text('{"hamdi":"aaaaaaaaaaaaaaaaaaaaaaaa"}')
            phone._token_cache.clear()
            returned=phone._read_user_tokens();returned['hamdi']='modified'
            self.assertEqual(phone._read_user_tokens()['hamdi'],'aaaaaaaaaaaaaaaaaaaaaaaa')
            replacement=p.with_suffix('.new');replacement.write_text('{"hamdi":"bbbbbbbbbbbbbbbbbbbbbbbb"}');replacement.replace(p)
            self.assertEqual(phone._read_user_tokens()['hamdi'],'bbbbbbbbbbbbbbbbbbbbbbbb')
            p.unlink();self.assertEqual(phone._read_user_tokens(),{})

    def test_source_cache_reuses_read_but_observes_replacement_and_deletion(self):
        from modules import source_text
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'main.py';p.write_text('first')
            source_text._CACHE.clear()
            with patch.object(Path,'read_bytes',autospec=True,side_effect=Path.read_bytes) as read:
                self.assertEqual(source_text.read(p),'first')
                self.assertEqual(source_text.read(p),'first');self.assertEqual(read.call_count,1)
                replacement=p.with_suffix('.new');replacement.write_text('other');replacement.replace(p)
                self.assertEqual(source_text.read(p),'other');self.assertEqual(read.call_count,2)
            p.unlink();self.assertIsNone(source_text.read(p))

    def test_file_order_cache_returns_independent_rows_and_observes_mtime(self):
        from modules import nxapi
        rows=[{'path':'a','mtime':1,'cat':'other'},{'path':'b','mtime':2,'cat':'other'}]
        nxapi._SHAPE_CACHE.clear()
        first=nxapi._shape_files(rows,1);first['files'][0]['path']='modified'
        self.assertEqual(nxapi._shape_files(rows,2)['files'][0]['path'],'b')
        rows[0]['mtime']=3
        self.assertEqual(nxapi._shape_files(rows,2)['files'][0]['path'],'a')

    def test_active_fallback_state_is_not_shared_between_users(self):
        from modules import llm
        with tempfile.TemporaryDirectory() as td, patch.object(user_models,'DATA_DIR',Path(td)), patch.object(llm,'_fallback_states',{}):
            user_models.save('hamdi',['main','fallback']);user_models.save('ebru',['main','fallback'])
            llm._fallback_states[('hamdi',('main','fallback'))]=(1,time.time())
            self.assertEqual(llm.active_model('hamdi'),'fallback')
            self.assertEqual(llm.active_model('ebru'),'main')

    def test_key_save_does_not_measure_models_or_write_global_settings(self):
        import ast
        from types import SimpleNamespace
        from unittest.mock import Mock
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'web_models.py').read_text())
        bridge=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WebModels')
        method=next(n for n in bridge.body if isinstance(n,ast.FunctionDef) and n.name=='api_key_save')
        llm=Mock();ns={'llm':llm,'_p':lambda:SimpleNamespace(slug='hamdi')}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'web.py','exec'),ns)
        self.assertEqual(ns['api_key_save'](SimpleNamespace(_runtime=SimpleNamespace(**ns)),'secret','my-model','fallback'),{'Gemini':{'ok':True,'saved':True}})
        llm.set_user_key.assert_called_once_with('hamdi','secret')
        llm.model_settings.assert_called_once_with('hamdi','my-model',['fallback'])
        self.assertFalse(llm.model_check.called)

    def test_local_embeddings_use_bounded_batches(self):
        from modules import ollama_embed
        from unittest.mock import Mock
        calls=[]
        def send(url,json,timeout):
            calls.append((url,json,timeout))
            return Mock(status_code=200,json=lambda:{'embeddings':[[float(int(t)),1] for t in json['input']]})
        with patch.object(ollama_embed.requests,'post',side_effect=send):
            values=ollama_embed.run([str(n) for n in range(101)],'http://local','model')
        self.assertEqual([len(c[1]['input']) for c in calls],[50,50,1])
        self.assertEqual(values[100],[100.,1]);self.assertTrue(all(not c[1]['truncate'] for c in calls))

    def test_old_embedding_endpoint_fallback_and_missing_model_distinction(self):
        from modules import ollama_embed
        from unittest.mock import Mock
        import requests
        missing_route=Mock(status_code=404,text='404 page not found')
        vector=Mock(status_code=200,json=lambda:{'embedding':[1.,2.]})
        with patch.object(ollama_embed.requests,'post',side_effect=[missing_route,vector,vector]) as post:
            self.assertEqual(ollama_embed.run(['a','b'],'http://local','model'),[[1.,2.],[1.,2.]])
            self.assertEqual(post.call_count,3)
        missing_model=Mock(status_code=404,text='{"error":"model not found"}')
        missing_model.raise_for_status.side_effect=requests.HTTPError('model not found')
        with patch.object(ollama_embed.requests,'post',return_value=missing_model) as post:
            with self.assertRaises(requests.HTTPError):ollama_embed.run(['a'],'http://local','model')
            self.assertEqual(post.call_count,1)

    def test_embedding_invalid_count_and_cancel_does_not_continue(self):
        from modules import ollama_embed, requests_state
        from unittest.mock import Mock
        response=Mock(status_code=200,json=lambda:{'embeddings':[]})
        with patch.object(ollama_embed.requests,'post',return_value=response):
            with self.assertRaises(ValueError):ollama_embed.run(['a'],'http://local','model')
        with patch.object(ollama_embed.requests_state,'check',side_effect=requests_state.Cancelled('stop')), patch.object(ollama_embed.requests,'post') as post:
            with self.assertRaises(requests_state.Cancelled):ollama_embed.run(['a'],'http://local','model')
            post.assert_not_called()

    def test_ui_jobs_capture_context_without_leaking_worker_context(self):
        import contextvars
        marker=contextvars.ContextVar('test-ui-owner',default='none')
        token=marker.set('first')
        try:first=ui_jobs.start('first','context-test',lambda:marker.get())['job']
        finally:marker.reset(token)
        second=ui_jobs.start('second','context-test',lambda:marker.get())['job']
        for _ in range(100):
            a=ui_jobs.status('first',first);b=ui_jobs.status('second',second)
            if a['state']=='done' and b['state']=='done':break
            time.sleep(.01)
        self.assertEqual(a['data'],'first');self.assertEqual(b['data'],'none')
