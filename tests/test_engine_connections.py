"""Adapter contracts use actual engine queues/facade; providers and devices are mocked."""
import sys
import json
import threading
import urllib.request
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
import test_engine_modular as fixtures
from modules.phone import PhoneServer
from web_chat import WebChat
from web_files import WebFiles


class EngineConnectionTests(unittest.TestCase):
    def test_other_queued_ui_actions_keep_owner_and_surface_rejection(self):
        import web
        from web_memory import WebMemory
        context=self.context()
        captured=SimpleNamespace(name='Ebru',slug='ebru',data={'macros':{'work':{'title':'Çalışma'}}})
        context.requests_state=SimpleNamespace(register=Mock(return_value=True))
        context.profile=SimpleNamespace(name='Hamdi',slug='hamdi')
        bridge=WebMemory();bridge._runtime=SimpleNamespace(engine=context,_p=lambda:captured)
        token=web._bridge_profile.set(captured)
        self.addCleanup(web._bridge_profile.reset,token)
        with patch.object(web,'engine',context):
            actions=(lambda:bridge.macro_run('work'),lambda:web.bridge.whatsapp_send('Kişi','Merhaba'),web.bridge.daily)
            for action in actions:
                self.assertTrue(action())
                self.assertEqual(context.events.get_nowait()[3],'Ebru')
                context.requests_state.register.return_value=False
                self.assertFalse(action())
                self.assertTrue(context.events.empty())
                context.requests_state.register.return_value=True

    def test_file_action_keeps_captured_owner_when_pc_user_changes(self):
        context=self.context()
        captured=SimpleNamespace(name='Ebru',slug='ebru')
        context.requests_state=SimpleNamespace(register=Mock(return_value=True))
        context.profile=SimpleNamespace(name='Hamdi',slug='hamdi')
        bridge=WebFiles();bridge._runtime=SimpleNamespace(engine=context,_p=lambda:captured)
        with patch('modules.nxapi.action_command',return_value='"report.txt" özetle'):
            self.assertEqual(bridge.file_do('report.txt','ozet'),'"report.txt" özetle')
        self.assertEqual(context.events.get_nowait()[3],'Ebru')
        context.requests_state.register.assert_called_once()
        self.assertEqual(context.requests_state.register.call_args.args[0],'ebru')

    def test_file_action_rejection_is_not_reported_as_success(self):
        context=self.context()
        context.requests_state=SimpleNamespace(register=Mock(return_value=False))
        bridge=WebFiles();bridge._runtime=SimpleNamespace(engine=context,_p=lambda:context.pc_profile())
        with patch('modules.nxapi.action_command',return_value='"report.txt" özetle'):
            with self.assertRaisesRegex(ValueError,'kuyruğa alınmadı'):
                bridge.file_do('report.txt','ozet')
        self.assertTrue(context.events.empty())

    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def test_cli_import_main_alias_keeps_one_engine(self):
        module=ModuleType('__main__')
        context=SimpleNamespace(_exported=set(),list_input_devices=Mock())
        constructor=Mock(return_value=context)
        dependency=ModuleType('modules.engine_runtime');dependency.EngineContext=constructor
        with patch.dict(sys.modules,{'__main__':module,'modules.engine_runtime':dependency}),patch.object(sys,'argv',['main.py','--devices']):
            exec(compile((fixtures.ROOT/'main.py').read_bytes(),'main.py','exec'),module.__dict__)
            import main
            self.assertIs(main,module)
            self.assertIs(main._runtime,context)
            constructor.assert_called_once()
            context.list_input_devices.assert_called_once()

    def test_media_queue_captures_owner_before_profile_changes(self):
        context=self.context()
        original=context.profile.name
        context.submit_audio('record.wav');context.submit_photo('picture.png','anlat')
        context.profile=SimpleNamespace(name='Other',slug='other')
        audio = context.events.get_nowait()
        self.assertEqual(audio[:4],('audio','record.wav','telefon',original))
        self.assertTrue(audio[4])
        photo = context.events.get_nowait()
        self.assertEqual(photo[:5],('photo','picture.png','anlat','telefon',original))
        self.assertTrue(photo[5])

    def test_web_bridge_surfaces_rejection_and_immediate_stop(self):
        context=self.context()
        context.requests_state=SimpleNamespace(register=Mock(return_value=False),cancel=Mock(),
                                                   cancel_unambiguous=Mock(return_value=('cancelled','rid')))
        context.voice=SimpleNamespace(stop_speaking=Mock())
        bridge=WebChat();bridge._runtime=SimpleNamespace(engine=context,_p=lambda:context.pc_profile())
        with self.assertRaises(ValueError):bridge.send('merhaba','duplicate')
        with patch('modules.pc_guide.stop'):
            self.assertFalse(bridge.send('dur'))
        context.requests_state.cancel_unambiguous.assert_called_once()
        context.requests_state.cancel.assert_not_called()
        context.requests_state.register.return_value=True
        self.assertTrue(bridge.send('merhaba','new-rid'))
        self.assertEqual(context.events.get_nowait()[4],'new-rid')

    def test_phone_stop_cancels_the_authenticated_owner_without_queueing(self):
        context=self.context();context.match_user=lambda name:'Ebru' if name=='ebru' else None
        context.voice=SimpleNamespace(stop_speaking=Mock())
        context.requests_state=SimpleNamespace(
            cancel=Mock(), cancel_unambiguous=Mock(return_value=('cancelled','rid')),
        )
        with patch('modules.pc_guide.stop') as guide:
            self.assertEqual(PhoneServer(context).ask('dur','ebru'),'Tamam.')
        context.requests_state.cancel_unambiguous.assert_called_once_with('ebru')
        context.requests_state.cancel.assert_not_called()
        guide.assert_not_called()
        self.assertTrue(context.events.empty())

    def test_phone_missing_owner_never_falls_back_to_pc_user(self):
        context=self.context();context.match_user=lambda name:None
        context.submit=Mock()
        self.assertIn('kullanıcısı bulunamadı',PhoneServer(context).ask('merhaba','deleted'))
        context.submit.assert_not_called()

    def test_phone_rejected_queue_does_not_wait_for_a_reply(self):
        context=self.context();context.match_user=lambda name:context.profile.name
        context.requests_state=SimpleNamespace(register=Mock(return_value=False))
        with patch('modules.phone.time.sleep') as sleep:
            self.assertIn('kuyruğa alınmadı',PhoneServer(context).ask('merhaba','owner'))
        sleep.assert_not_called()

    def test_phone_internal_type_error_does_not_replay_the_command(self):
        context=self.context();context.match_user=lambda name:context.profile.name
        context.submit=Mock(side_effect=TypeError('provider failed after accepting command'))
        with self.assertRaises(TypeError):PhoneServer(context).ask('merhaba','owner')
        context.submit.assert_called_once()

    def test_phone_cancelled_request_finishes_without_timeout(self):
        context=self.context();context.match_user=lambda name:context.profile.name
        context.submit=Mock(return_value=True)
        context.requests_state=SimpleNamespace(is_cancelled=Mock(return_value=True))
        with patch('modules.phone.time.sleep') as sleep:
            self.assertIn('iptal edildi',PhoneServer(context).ask('merhaba','owner'))
        sleep.assert_not_called()

    def test_phone_reply_matches_both_owner_and_request_id(self):
        context=self.context();context.match_user=lambda name:'Ebru'
        context.requests_state=SimpleNamespace(is_cancelled=lambda *args:False)
        def submit(text,source,user,rid):
            context.event_log.extend([
                {'id':1,'rid':rid,'kind':'assistant','user':'Hamdi','text':'wrong user'},
                {'id':2,'rid':'other-rid','kind':'assistant','user':'Ebru','text':'wrong request'},
                {'id':3,'rid':rid,'kind':'assistant','user':'Ebru','text':'correct'},
            ])
            context.response_waiters.publish('hamdi',rid,'wrong user')
            context.response_waiters.publish('ebru','other-rid','wrong request')
            context.response_waiters.publish('ebru',rid,'correct')
            return True
        context.submit=submit
        context.richtext=SimpleNamespace(speakable=lambda text:text)
        self.assertEqual(PhoneServer(context).ask('merhaba','ebru'),'correct')

    def test_phone_shutdown_finishes_waiting_immediately(self):
        context=self.context();context.match_user=lambda name:context.profile.name
        context.submit=Mock(return_value=True);context.stop_event.set()
        with patch('modules.phone.time.sleep') as sleep:
            self.assertIn('kapandı',PhoneServer(context).ask('merhaba','owner'))
        sleep.assert_not_called()

    def test_real_web_http_reaches_the_engine_queue_and_reports_rejection(self):
        import web
        context=self.context()
        context.requests_state=SimpleNamespace(register=Mock(return_value=True))
        with patch.object(web,'engine',context):
            server=web.Server(('127.0.0.1',0),web.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def send(rid):
                    request=urllib.request.Request(f'http://127.0.0.1:{server.server_address[1]}/api/send',data=json.dumps(['merhaba',rid]).encode(),headers={'X-Jarvis-Token':web.TOKEN,'Content-Type':'application/json'})
                    with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)
                self.assertEqual(send('accepted'),{'ok':True,'data':True})
                event=context.events.get_nowait()
                self.assertEqual(event,('command','merhaba','yazı',context.profile.name,'accepted'))
                context.requests_state.register.return_value=False
                self.assertFalse(send('duplicate')['ok'])
                self.assertTrue(context.events.empty())
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
