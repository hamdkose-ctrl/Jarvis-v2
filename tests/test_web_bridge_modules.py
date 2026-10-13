"""Behavior contracts across extracted bridges, without real provider/OS calls."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_engine_modular as fixtures
from web_models import WebModels
from web_integrations import WebIntegrations
from modules import live, live_tools, ui_jobs

class BridgeModuleTests(unittest.TestCase):
    def models(self,slug):
        instance=WebModels()
        instance._runtime=SimpleNamespace(_p=lambda:SimpleNamespace(slug=slug,name=slug),llm=Mock(),config=Mock(),privacy=Mock())
        return instance

    def test_model_key_writes_use_each_injected_runtime(self):
        a=self.models('hamdi');b=self.models('ebru')
        a.api_key_save('key-a','model-a','backup-a');b.api_key_save('key-b','model-b','')
        a._runtime.llm.set_user_key.assert_called_once_with('hamdi','key-a')
        b._runtime.llm.set_user_key.assert_called_once_with('ebru','key-b')
        a._runtime.llm.model_settings.assert_called_once_with('hamdi','model-a',['backup-a'])
        b._runtime.llm.model_settings.assert_called_once_with('ebru','model-b',[])

    def test_key_validation_uses_owner_model_and_bounded_client(self):
        from google import genai
        bridge=self.models('hamdi');bridge._runtime.llm.model_names.return_value=['mine']
        client=Mock()
        with patch.object(genai,'Client',return_value=client) as factory:
            result=bridge.user_key_set('Hamdi','key')
        self.assertTrue(result['ok'])
        factory.assert_called_once_with(api_key='key',http_options={'timeout':45000})
        client.models.generate_content.assert_called_once_with(model='mine',contents="Yalnızca 'tamam' yaz.")

    def test_model_measure_retains_owner_after_profile_switch(self):
        bridge=self.models('hamdi');gate=threading.Event();entered=threading.Event()
        bridge._runtime.time=time;bridge._runtime._record_failure=Mock()
        bridge._runtime.llm.model_names.return_value=['mine']
        def get_client():entered.set();gate.wait(2);return Mock()
        bridge._runtime.llm.gemini_client.side_effect=get_client
        try:
            job=bridge.llm_measure()['job'];self.assertTrue(entered.wait(1))
            bridge._runtime._p=lambda:SimpleNamespace(slug='ebru',name='ebru')
            with self.assertRaises(ValueError):bridge.ui_job_status(job)
        finally:gate.set()
        for _ in range(100):
            result=ui_jobs.status('hamdi',job)
            if result['state']=='done':break
            time.sleep(.01)
        self.assertTrue(result['data']['mine']['ok'])
        bridge._runtime.llm.set_user_context.assert_called_once_with('hamdi')

    def test_invalid_google_upload_preserves_credentials(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'credentials.json';path.write_text('existing')
            bridge=WebIntegrations();bridge._runtime=SimpleNamespace(json=json,google_api=SimpleNamespace(CRED=path))
            for text in ('not-json','[]','{"key":"irrelevant"}'):
                with self.assertRaises(ValueError):bridge.google_upload(text)
            self.assertEqual(path.read_text(),'existing')
            bridge.google_upload('{"installed":{"client_id":"id"}}')
            self.assertEqual(json.loads(path.read_text()),{'installed':{'client_id':'id'}})

    def test_notification_preferences_remain_in_own_profile(self):
        profiles=[SimpleNamespace(data={'prefs':{}},save=Mock()) for _ in range(2)]
        for p in profiles:p.set_pref=lambda key,value,p=p:p.data['prefs'].__setitem__(key,value)
        a=WebIntegrations();b=WebIntegrations()
        a._runtime=SimpleNamespace(_p=lambda:profiles[0],notify=SimpleNamespace(new_topic=lambda:'topic-a'))
        b._runtime=SimpleNamespace(_p=lambda:profiles[1],notify=SimpleNamespace(new_topic=lambda:'topic-b'))
        a.ntfy('on');b.ntfy('on');a.ntfy('off')
        self.assertEqual(a.ntfy('show'),{'on':False,'topic':''})
        self.assertEqual(b.ntfy('show'),{'on':True,'topic':'topic-b'})

    def test_live_canonical_tools_preserve_compatibility(self):
        for name,args,expected in [('ses_ayarla',{'seviye':120},'ses seviyesini 100 yap'),('parlaklik_ayarla',{'seviye':'bad'},None),('medya',{'eylem':'sonraki'},'sonraki şarkı'),('komut',{'istek':'  dosyamı   aç '},'dosyamı aç'),('unknown',{},None)]:
            with self.subTest(name=name):
                self.assertEqual(live_tools._build_request(name,args),expected)
                self.assertEqual(live._build_request(name,args),expected)
        self.assertIs(live.TOOLS,live_tools.TOOLS)

    def test_classified_dispatch_preserves_document_session(self):
        from modules import engine_intents
        session=SimpleNamespace(last_doc=None)
        runtime=SimpleNamespace(_resolve_doc=lambda path,command:(path,None), docs=SimpleNamespace(summarize=Mock(return_value='summary')), _session=lambda:session, _explicit_output_format=lambda command:None)
        result=engine_intents.dispatch(runtime,'doc_summary',{'path':'document.pdf'},'özetle','özetle')
        self.assertIn('summary',result)
        self.assertEqual(session.last_doc,('summary','document.pdf','ozet'))
        runtime.docs.summarize.assert_called_once_with('document.pdf')

    def test_dispatch_unknown_intent_falls_back_to_own_user_chat(self):
        from modules import engine_intents
        runtime=SimpleNamespace(vision=SimpleNamespace(mode=lambda:False),profile=SimpleNamespace(slug='hamdi'),_sys_prompt=lambda command:'system',chat=Mock(return_value='answer'))
        self.assertEqual(engine_intents.dispatch(runtime,'unknown',{},'hello','hello'),'answer')
        runtime.chat.assert_called_once_with('hello','system',user='hamdi')

    def test_cancelled_dispatch_has_no_side_effect(self):
        from modules import engine_intents,requests_state
        close=Mock();runtime=SimpleNamespace(system_control=SimpleNamespace(close_application=close))
        with patch.object(requests_state,'check',side_effect=requests_state.Cancelled('stop')):
            with self.assertRaises(requests_state.Cancelled):engine_intents.dispatch(runtime,'close_app',{'name':'App'},'close app','close app')
        close.assert_not_called()
