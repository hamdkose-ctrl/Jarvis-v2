"""Real runtime composition/facade/loop tests with only hardware/providers mocked."""
import ast
import contextlib
from pathlib import Path
import tempfile
import threading
import time
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch, mock_open
import test_privacy_voice_and_pending
if 'pyautogui' not in sys.modules:
    keyboard = ModuleType('pyautogui')
    keyboard.__getattr__ = lambda name: Mock()
    sys.modules['pyautogui'] = keyboard
from modules import engine_runtime, engine_commands
from modules.engine_voice import VoiceSession

ROOT=Path(__file__).resolve().parents[1]


class ModularEngineTests(unittest.TestCase):
    def context(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root_logger=engine_runtime.logging.getLogger()
        previous_handlers=set(root_logger.handlers)
        with patch.object(engine_runtime,'DATA_DIR',Path(temp.name)):
            context=engine_runtime.EngineContext()
        def close_test_handlers():
            for handler in list(root_logger.handlers):
                if handler not in previous_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()
        self.addCleanup(close_test_handlers)
        self.addCleanup(context._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        def close_voice_lane():
            from modules import voice_runtime
            lane = voice_runtime.active()
            if lane is not None:
                lane.close()
        self.addCleanup(close_voice_lane)
        return context

    def test_entry_point_is_small_and_components_do_not_import_main(self):
        source=(ROOT/'main.py').read_text()
        self.assertLessEqual(len(source.splitlines()),80)
        tree=ast.parse(source)
        names={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
        self.assertEqual(names,{'main','_context'})
        self.assertNotIn('while ',source)
        for path in (ROOT/'modules').glob('engine_*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Import):self.assertFalse(any(a.name=='main' for a in node.names),path.name)
                if isinstance(node,ast.ImportFrom):self.assertNotEqual(node.module,'main',path.name)

    def test_contexts_do_not_share_mutable_queue_flags_locks_or_sessions(self):
        first,second=self.context(),self.context()
        first.flags['mic']=False;first.events.put(('status','first'))
        first._session().pending_msg={'to':'Alice'}
        self.assertTrue(second.flags['mic']);self.assertTrue(second.events.empty())
        self.assertIsNone(second._session().pending_msg)
        for name in ('events','stop_event','pause_listening','audio_lock','_execution_lock','_profiles','_sessions'):
            self.assertIsNot(getattr(first,name),getattr(second,name),name)

    def test_configured_logging_does_not_open_an_unused_file_handler(self):
        with patch.object(engine_runtime.logging.getLogger(), 'handlers', [Mock()]), patch.object(engine_runtime, 'RotatingFileHandler') as handler:
            self.context()
        handler.assert_not_called()

    def test_command_and_queue_handlers_are_bound_to_their_own_context(self):
        context=self.context()
        self.assertIs(context.handle.func,engine_commands.handle_request)
        self.assertIs(context.handle.args[0],context)
        context.requests_state=SimpleNamespace(register=Mock(return_value=True))
        context.submit('merhaba','web',context.profile.name,'rid')
        self.assertEqual(context.events.get_nowait(),('command','merhaba','web',context.profile.name,'rid'))

    def test_web_facade_patch_and_restore_use_one_authoritative_context(self):
        import main
        previous=main.profile
        owner=SimpleNamespace(slug='facade-test',name='Facade',data={'prefs':{}})
        with patch.object(main,'profile',owner):
            self.assertIs(main._runtime.profile,owner)
            main._session().last_doc=('document','','text')
            self.assertEqual(main.last_doc,('document','','text'))
            with patch.object(main,'handle',return_value='mocked'):
                self.assertEqual(main._runtime.handle('question'),'mocked')
        self.assertIs(main.profile,previous)
        self.assertIs(main._runtime.profile,previous)
        self.assertNotIn('profile',vars(main))
        self.assertNotIn('handle',vars(main))

    def test_real_loop_uses_context_handler_and_closes_without_hardware(self):
        context=self.context()
        owner=context.profile.name
        context.list_users=lambda:[owner]
        context.requests_state=SimpleNamespace(is_cancelled=lambda *a:False,activate=lambda *a:contextlib.nullcontext())
        def handle_once(command):
            context.stop_event.set()
            return 'Merhaba'
        context.handle=Mock(side_effect=handle_once)
        context.emit=Mock();context._finalize=lambda text:text
        context._start_hang_watch=Mock()
        context.profile.log_agent=Mock()
        context.threading=SimpleNamespace(Thread=Mock(),Timer=Mock())
        context.time=SimpleNamespace(time=time.time,sleep=lambda seconds:None)
        context.events.put(('command','selam','web',owner,'one'))
        voice=SimpleNamespace(manual_local_stt=False,listening_enabled=False,speak_enabled=False,live_on=False,state={},speak=Mock())
        with patch('modules.engine_voice.VoiceSession',return_value=voice),patch('instance.take_over',return_value=False),patch('updater.pop_notice',return_value=None),patch('modules.perf.start'),patch('release_guard.ready'),patch('modules.brain_entry._install_core_guards'):
            context.main(ui=Mock())
        context.handle.assert_called_once_with('selam')
        voice.speak.assert_called_once_with('Merhaba')
        context.emit.assert_any_call('assistant','Merhaba')
        context.emit.assert_any_call('quit')
        self.assertTrue(context.stop_event.is_set())
        self.assertFalse(context.pause_listening.is_set())

    def test_voice_sessions_do_not_share_wake_continuation_state(self):
        runtime=SimpleNamespace(sys=SimpleNamespace(argv=['main.py','--text','--mute']),live=SimpleNamespace(enabled=Mock()))
        # Wake-state isolation is independent of the single output owner; mock its
        # setup so two sessions can be compared without registering a global lane.
        with patch('modules.voice_runtime.maybe_start',return_value=(None,False)):
            first,second=VoiceSession(runtime),VoiceSession(runtime)
        first.state['awake_until']=100
        self.assertEqual(second.state['awake_until'],0)
        self.assertFalse(first.listening_enabled);self.assertFalse(first.speak_enabled)
        runtime.live.enabled.assert_not_called()

    def test_local_button_in_real_loop_uses_local_recognition_and_reports_missing_model(self):
        context=self.context();context.emit=Mock();context._start_hang_watch=Mock()
        context.list_users=lambda:[context.profile.name]
        context.threading=SimpleNamespace(Thread=Mock(),Timer=Mock())
        def fail_local_listen(**kwargs):
            context.stop_event.set()
            raise ValueError('Yerel ses modeli hazır değil.')
        context.voice=SimpleNamespace(HINTS=[],listen=Mock(side_effect=fail_local_listen))
        context.events.put(('listen',))
        session=SimpleNamespace(manual_local_stt=True,listening_enabled=True,speak_enabled=False,live_on=False,state={})
        with patch('modules.engine_voice.VoiceSession',return_value=session),patch('instance.take_over',return_value=False),patch('updater.pop_notice',return_value=None),patch('modules.perf.start'),patch('release_guard.ready'):
            context.main(ui=Mock())
        self.assertTrue(context.voice.listen.call_args.kwargs['local'])
        context.emit.assert_any_call('system','Yerel ses modeli hazır değil.')
        self.assertFalse(context.pause_listening.is_set())
        self.assertNotIn('listen_for_wake_word',[str(c) for c in context.threading.Thread.call_args_list])

    def test_web_button_refuses_old_cloud_session_until_restart(self):
        import web
        fake=SimpleNamespace(_manual_local_stt=False,flags={'mic':True},events=Mock())
        with patch.object(web,'engine',fake),patch.object(web.config,'load_settings',return_value={'local_stt_enabled':True}),patch.object(web.hub,'publish'):
            with self.assertRaisesRegex(ValueError,'yeniden başlat'):web.bridge.listen_once()
            fake.events.put.assert_not_called()
            fake._manual_local_stt=True
            self.assertTrue(web.bridge.listen_once());fake.events.put.assert_called_once_with(('listen',))
            fake.flags['mic']=False
            self.assertFalse(web.bridge.listen_once())
            self.assertEqual(fake.events.put.call_count,1)

    def test_extracted_speech_uses_selected_voice_and_respects_mute(self):
        # The selected profile voice key and rate go to the single owner (lane.say),
        # never to a legacy runtime.voice.speak path; mute enqueues nothing.
        lane=Mock();lane.say.return_value=threading.Event()
        person=SimpleNamespace(slug='alice',data={'prefs':{'voice':'tr_kadin','rate':-8}})
        runtime=SimpleNamespace(sys=SimpleNamespace(argv=['main.py','--text']),live=SimpleNamespace(enabled=Mock()),flags={'speak':True,'mic':False},emit=Mock(),threading=SimpleNamespace(Event=threading.Event,Thread=Mock()),profile=person,voice=SimpleNamespace(speak=Mock()),_record_failure=lambda *a:None)
        with patch('modules.voice_runtime.maybe_start',return_value=(lane,False)):
            session=VoiceSession(runtime)
        session.speak('Merhaba',slow=True)
        lane.say.assert_called_once_with('alice','tr_kadin','Merhaba',background=False,rate=-15,kind='reply',turn_id='')
        runtime.voice.speak.assert_not_called()
        runtime.flags['speak']=False;session.speak('Duyulmamalı')
        self.assertEqual(lane.say.call_count,1)

    def test_voice_stop_and_rejected_registration_release_listening(self):
        context=self.context();context.emit=Mock()
        context.voice=SimpleNamespace(stop_speaking=Mock())
        context.requests_state=SimpleNamespace(cancel=Mock(),register=Mock(return_value=False))
        with patch('modules.pc_guide.stop'):
            session=VoiceSession(context)
            self.assertFalse(session.submit_voice('dur'))
        self.assertFalse(context.pause_listening.is_set())
        self.assertTrue(context.events.empty())
        context.requests_state.cancel.assert_called_once()
        self.assertFalse(session.submit_voice('reddedilen komut'))
        self.assertFalse(context.pause_listening.is_set())
        context.requests_state.register.return_value=True
        self.assertTrue(session.submit_voice('merhaba'))
        self.assertTrue(context.pause_listening.is_set())
        self.assertEqual(context.events.get_nowait()[1],'merhaba')

    def test_silence_only_does_not_cancel_active_work(self):
        context=self.context();context.emit=Mock()
        context.voice=SimpleNamespace(stop_speaking=Mock())
        context.requests_state=SimpleNamespace(cancel=Mock(),register=Mock(return_value=True))
        with patch('modules.pc_guide.stop') as guide:
            for text in ('sus', 'yeter', 'sesini kes', 'konuşmayı kes'):
                self.assertFalse(context.submit(text))
        self.assertEqual(context.voice.stop_speaking.call_count, 4)
        context.requests_state.cancel.assert_not_called()
        context.requests_state.register.assert_not_called()
        guide.assert_not_called()
        self.assertTrue(context.events.empty())

    def test_voice_submission_failure_also_releases_listening(self):
        context=self.context();context.emit=Mock()
        context.submit=Mock(side_effect=RuntimeError('registration failed'))
        with self.assertRaises(RuntimeError):VoiceSession(context).submit_voice('merhaba')
        self.assertFalse(context.pause_listening.is_set())

    def test_offline_recognition_completed_after_mute_is_discarded(self):
        context=self.context();context.emit=Mock();context.submit=Mock()
        context._strip_wake=lambda text:text
        def recognize(audio):
            context.flags['mic']=False
            return 'merhaba'
        context.voice=SimpleNamespace(recognize=recognize)
        session=VoiceSession(context)
        with patch('modules.wakeword.wanted',return_value=True),patch('modules.wakeword.ready',return_value=True),patch('modules.wakeword.wait',return_value=b'audio'):
            self.assertTrue(session.offline_wake_step())
        context.submit.assert_not_called()
        self.assertFalse(context.pause_listening.is_set())

    def test_online_recognition_completed_after_mute_is_discarded(self):
        context=self.context();context.emit=Mock();context.submit=Mock()
        context.live=SimpleNamespace(get=lambda:None,enabled=lambda:False)
        def listen(**kwargs):
            context.flags['mic']=False;context.stop_event.set()
            return 'hey jarvis merhaba'
        context.voice=SimpleNamespace(listen=listen,last_noise=1)
        session=VoiceSession(context)
        with patch.object(session,'offline_wake_step',return_value=False):session.listen_for_wake_word()
        context.submit.assert_not_called()

    def test_failed_clipboard_fallback_is_not_reported_as_success(self):
        import subprocess
        context=self.context();context._record_failure=Mock()
        context.subprocess=SimpleNamespace(run=Mock(side_effect=subprocess.CalledProcessError(1,'powershell')))
        with patch.dict(sys.modules,{'pyperclip':SimpleNamespace(copy=Mock(side_effect=RuntimeError('no clipboard')))}):
            self.assertFalse(context._copy_text('text'))
        self.assertTrue(context.subprocess.run.call_args.kwargs['check'])

    def test_loop_failure_stops_workers_and_clears_request_state(self):
        context=self.context();context.emit=Mock()
        context.list_users=lambda:[context.profile.name]
        context.threading=SimpleNamespace(Thread=Mock(),Timer=Mock())
        context._start_hang_watch=Mock()
        context.requests_state=SimpleNamespace(is_cancelled=Mock(side_effect=RuntimeError('queue provider failed')))
        context.events.put(('command','selam','web',context.profile.name,'rid'))
        voice=SimpleNamespace(manual_local_stt=False,listening_enabled=False,speak_enabled=False,live_on=False)
        with patch('modules.engine_voice.VoiceSession',return_value=voice),patch('instance.take_over',return_value=False),patch('updater.pop_notice',return_value=None),patch('modules.perf.start'),patch('release_guard.ready'):
            with self.assertRaises(RuntimeError):context.main(ui=Mock())
        self.assertTrue(context.stop_event.is_set())
        self.assertIsNone(context._cur_rid);self.assertEqual(context._cur_source,'')
        self.assertFalse(context.pause_listening.is_set())
        with self.assertRaises(RuntimeError):context._prefetch_pool.submit(lambda:None)
        context.emit.assert_any_call('quit')

    def test_hang_watch_closes_its_diagnostic_file_when_stopped(self):
        context=self.context();context.stop_event.set()
        context.threading=SimpleNamespace(Thread=lambda target,**kw:SimpleNamespace(start=target))
        handle=mock_open()
        with patch('builtins.open',handle),patch('faulthandler.cancel_dump_traceback_later'):
            context._start_hang_watch()
        handle().close.assert_called_once()
