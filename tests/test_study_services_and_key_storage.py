"""Study APIs run with small fakes; protected key migration is atomic."""
import contextvars
import concurrent.futures
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import config
from web_study import WebStudy
from modules.study_services import StudyServices


class StudyServicesTests(unittest.TestCase):
    def setUp(self):
        self.profile=SimpleNamespace(slug='alice')
        self.services=StudyServices(current_profile=lambda:self.profile,study=Mock(),exams=Mock(),
            media=Mock(),llm=Mock(),privacy=Mock(),config=Mock(),events=Mock())
        self.services.privacy.blocked.return_value=None
        self.bridge=WebStudy(self.services)

    def test_answer_context_and_legacy_alias(self):
        self.services.study.ask.return_value='Answer';self.services.study.last_topic.return_value='Topic'
        expected={'text':'Answer','topic':'Topic'}
        self.assertEqual(self.bridge.study_answer_with_context('Question'),expected)
        self.assertEqual(self.bridge.study_ask2('Question'),expected)
        self.services.llm.set_user_context.assert_called_with('alice')
        self.assertEqual(self.bridge.study_answer_text('Question'),'Answer')
        self.assertEqual(self.bridge.study_ask('Question'),'Answer')

    def test_explicit_source_selection(self):
        self.services.study.ask_source.return_value={'text':'Source answer','topic':'Source topic'}
        self.bridge.study_answer_with_context('Question','teacher',42)
        self.services.study.ask_source.assert_called_once_with(self.profile,'Question',42,'teacher')
        self.services.study.ask.assert_not_called()

    def test_document_names_and_legacy_aliases(self):
        self.bridge.study_remove_document(42);self.bridge.study_remove(43)
        self.assertEqual([call.args for call in self.services.study.remove.call_args_list],[(self.profile,42),(self.profile,43)])
        self.bridge.study_clear_documents();self.bridge.study_clear()
        self.assertEqual(self.services.study.clear.call_count,2)
        self.services.exams.mock_start.assert_not_called()

    def test_exam_dependency_is_injected(self):
        self.services.exams.mock_start.return_value={'count':10}
        self.assertEqual(self.bridge.study_mock_start(10),{'count':10})
        self.services.exams.mock_start.assert_called_once_with(self.profile,10)

    def test_identity_is_resolved_per_concurrent_request(self):
        current=contextvars.ContextVar('test-profile')
        barrier=threading.Barrier(2)
        study=Mock();study.ask.side_effect=lambda profile,*args:profile.slug
        services=StudyServices(current_profile=current.get,study=study,exams=Mock(),media=Mock(),
            llm=Mock(),privacy=Mock(),config=Mock(),events=Mock())
        bridge=WebStudy(services)
        def request(slug):
            current.set(SimpleNamespace(slug=slug));barrier.wait()
            return bridge.study_answer_text('Question')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a=pool.submit(request,'alice');b=pool.submit(request,'bob')
            self.assertEqual(a.result(),'alice');self.assertEqual(b.result(),'bob')

    def test_private_mode_saves_key_without_network(self):
        key='AIza'+'x'*35
        self.services.privacy.blocked.return_value='Blocked'
        result=self.bridge.study_set_youtube_key(key)
        self.services.media.check_key.assert_not_called()
        self.services.config.set_youtube_key.assert_called_once_with(key)
        self.assertNotIn(key,json.dumps(result))


class YoutubeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'settings.json'
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config,'SETTINGS_FILE',self.path))
        self.stack.enter_context(patch.object(config,'_cache',{'key':None,'text':'{}'}))
        self.stack.enter_context(patch.dict(os.environ,{'YOUTUBE_API_KEY':''}))

    def _mock_protection(self):
        # Storage logic uses an in-memory adapter; this is not an encryption test.
        tokens = {}
        def protect(key):
            token = 'dpapi:test-' + str(len(tokens))
            tokens[token] = key
            return token
        adapter = SimpleNamespace(protect=protect, unprotect=lambda token: tokens[token])
        return patch.object(config, '_privacy', return_value=adapter)

    @unittest.skipUnless(os.name == 'nt', 'Gerçek DPAPI testi Windows gerektirir')
    def test_real_windows_protection_and_readback(self):
        key='AIza'+'dummy-test-key'*3
        config.set_youtube_key(key)
        text=self.path.read_text(encoding='utf-8')
        self.assertNotIn(key,text)
        self.assertTrue(json.loads(text)['youtube_key_protected'].startswith('dpapi:'))
        self.assertEqual(config.get_youtube_key(),key)

    def test_legacy_migration_preserves_other_settings(self):
        self.stack.enter_context(self._mock_protection())
        key='AIza'+'legacy-test-key'*3
        config.save_settings(youtube_key=key,fullscreen=True,assistant_name='Jarvis')
        self.assertEqual(config.get_youtube_key(),key)
        saved=config.load_settings()
        self.assertNotIn('youtube_key',saved)
        self.assertTrue(saved['fullscreen']);self.assertEqual(saved['assistant_name'],'Jarvis')
        self.assertNotIn(key,self.path.read_text(encoding='utf-8'))

    def test_protected_storage_roundtrip_with_adapter(self):
        self.stack.enter_context(self._mock_protection())
        key = 'test-storage-secret'
        config.set_youtube_key(key)
        self.assertNotIn(key, self.path.read_text(encoding='utf-8'))
        self.assertEqual(config.get_youtube_key(), key)

    def test_protection_failure_never_falls_back_to_base64(self):
        config.save_settings(youtube_key='old-key',fullscreen=True)
        before=self.path.read_bytes()
        with patch.object(config,'_privacy',return_value=SimpleNamespace(protect=lambda key:'b64:encoded')):
            with self.assertRaises(OSError):config.get_youtube_key()
        self.assertEqual(self.path.read_bytes(),before)

    def test_atomic_write_failure_preserves_existing_settings(self):
        self.stack.enter_context(self._mock_protection())
        config.save_settings(youtube_key='old-key',fullscreen=True)
        before=self.path.read_bytes()
        with patch.object(config.os,'replace',side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):config.get_youtube_key()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(list(self.path.parent.glob('.jarvis-settings-*')))

    def test_delete_and_environment_priority(self):
        self.stack.enter_context(self._mock_protection())
        config.set_youtube_key('dummy-key')
        with patch.dict(os.environ,{'YOUTUBE_API_KEY':'environment-key'}):
            self.assertEqual(config.get_youtube_key(),'environment-key')
        config.set_youtube_key('')
        self.assertEqual(config.get_youtube_key(),'')
        self.assertNotIn('youtube_key_protected',config.load_settings())

    def test_error_response_does_not_echo_key_or_request_url(self):
        from modules import studymedia
        key='AIza'+'x'*35
        with patch.object(studymedia,'_get',side_effect=RuntimeError('https://youtube.invalid/?key='+key)):
            result=studymedia.check_key(key)
        self.assertNotIn(key,json.dumps(result))
        self.assertNotIn('youtube.invalid',json.dumps(result))
        self.assertIsInstance(result['key'],bool)

    def test_api_error_message_cannot_echo_key(self):
        from modules import studymedia
        import requests
        key='secret-key';response=Mock()
        response.json.return_value={'error':{'message':'bad key '+key,'errors':[{'reason':'unknownReason'}]}}
        result=studymedia._err_text(requests.HTTPError(response=response))
        self.assertNotIn(key,result)

    def test_settings_response_excludes_plaintext_and_protected_keys(self):
        import ast
        source=Path(__file__).resolve().parents[1]/'web.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        bridge=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Bridge')
        method=next(n for n in bridge.body if isinstance(n,ast.FunctionDef) and n.name=='settings')
        config.save_settings(youtube_key='legacy-secret',youtube_key_protected='dpapi:protected-secret',fullscreen=True)
        ns={'config':config,'DATA_DIR':config.DATA_DIR,'_aname':lambda:'Jarvis',
            'llm':SimpleNamespace(model_names=lambda owner:['test-model']), '_p':lambda:SimpleNamespace(slug='test'),
            '_wakeword':lambda:SimpleNamespace(mode=lambda:'off'),'_wake_note':lambda:''}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(source),'exec'),ns)
        response=ns['settings'](object())
        serialized=json.dumps(response)
        self.assertNotIn('legacy-secret',serialized);self.assertNotIn('protected-secret',serialized)
        self.assertTrue(response['saved']['fullscreen'])
