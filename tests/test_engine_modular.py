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
        context.emit=Mock();context._finalize=lambda text:text;context._emit_route=Mock()
        context._start_hang_watch=Mock()
        context.profile.log_agent=Mock()
        context.threading=SimpleNamespace(Thread=Mock(),Timer=Mock())
        context.time=SimpleNamespace(time=time.time,sleep=lambda seconds:None)
        context.events.put(('command','selam','web',owner,'one'))
        voice=SimpleNamespace(manual_local_stt=False,listening_enabled=False,speak_enabled=False,state={},speak=Mock())
        # This checks the event-loop handoff and stop lifecycle, not model
        # availability. A free-language turn now requires the primary model;
        # mock that external decision seam so the fixture cannot hang in an
        # unavailable provider while never reaching the handler.
        def handoff(_runtime, _entry, handler, command):
            return handler(command), SimpleNamespace(result_status='handled'), None
        with patch('modules.engine_voice.VoiceSession',return_value=voice), \
             patch('instance.take_over',return_value=False), \
             patch('updater.pop_notice',return_value=None), \
             patch('modules.perf.start'), patch('release_guard.ready'), \
             patch('modules.brain_entry._install_core_guards'), \
             patch('modules.brain_entry.prepare',return_value=SimpleNamespace(stage='semantic')), \
             patch('modules.brain_entry.handoff',side_effect=handoff), \
             patch('modules.brain_echo.present'), \
             patch.object(context._llm,'take_route',return_value=None):
            context.main(ui=Mock())
        context.handle.assert_called_once_with('selam')
        voice.speak.assert_called_once_with('Merhaba')
        context.emit.assert_any_call('assistant','Merhaba')
        context.emit.assert_any_call('quit')
        self.assertTrue(context.stop_event.is_set())
        self.assertFalse(context.pause_listening.is_set())

    def test_voice_sessions_do_not_share_wake_continuation_state(self):
        runtime=SimpleNamespace(sys=SimpleNamespace(argv=['main.py','--text','--mute']))
        # Wake-state isolation is independent of the single output owner; mock its
        # setup so two sessions can be compared without registering a global lane.
        with patch('modules.voice_runtime.maybe_start',return_value=(None,False)):
            first,second=VoiceSession(runtime),VoiceSession(runtime)
        first.state['awake_until']=100
        self.assertEqual(second.state['awake_until'],0)
        self.assertFalse(first.listening_enabled);self.assertFalse(first.speak_enabled)

    def test_local_button_in_real_loop_uses_local_recognition_and_reports_missing_model(self):
        context=self.context();context.emit=Mock();context._start_hang_watch=Mock()
        context.list_users=lambda:[context.profile.name]
        context.threading=SimpleNamespace(Thread=Mock(),Timer=Mock())
        def fail_local_stt(*args, **kwargs):
            context.stop_event.set()
            raise ValueError('Yerel ses modeli hazır değil.')
        context.voice=SimpleNamespace(HINTS=[],capture=Mock(return_value=b''),recognize=Mock(side_effect=fail_local_stt))
        context.events.put(('listen',))
        session=SimpleNamespace(manual_local_stt=True,listening_enabled=True,speak_enabled=False,state={})
        with patch('modules.engine_voice.VoiceSession',return_value=session),patch('instance.take_over',return_value=False),patch('updater.pop_notice',return_value=None),patch('modules.perf.start'),patch('release_guard.ready'):
            context.main(ui=Mock())
        self.assertTrue(context.voice.recognize.call_args.kwargs['local'])
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
        runtime=SimpleNamespace(sys=SimpleNamespace(argv=['main.py','--text']),flags={'speak':True,'mic':False},emit=Mock(),threading=SimpleNamespace(Event=threading.Event,Thread=Mock()),profile=person,voice=SimpleNamespace(speak=Mock()),_record_failure=lambda *a:None)
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
        def mute_during_recognize(*args,**kwargs):
            # Kayıt kilidi dışında beklenen yazıya çevirme: ses bitmiş, susturma bu beklemesinde gelmiş.
            context.flags['mic']=False;context.stop_event.set()
            return 'hey jarvis merhaba'
        context.voice=SimpleNamespace(capture=lambda **kwargs: b'ses',recognize=mute_during_recognize,last_noise=1)
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
        voice=SimpleNamespace(manual_local_stt=False,listening_enabled=False,speak_enabled=False)
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


    def barge_session(self):
        """A voice session with only what the barge watcher touches; the locks are real."""
        lock = threading.RLock()
        speaker = SimpleNamespace(stop_speaking=Mock())
        runtime = SimpleNamespace(
            stop_event=threading.Event(), flags={"mic": True}, audio_lock=lock,
            time=time, log=Mock(), SESSION_SECONDS=20, WAKE_WORD="Jarvis",
            voice=speaker, _record_failure=lambda *args: None,
        )
        session = VoiceSession.__new__(VoiceSession)
        session.runtime = runtime
        session.manual_local_stt = False
        session.listening_enabled = True
        session.state = {"awake_until": 0.0}
        return session, lock, speaker

    def test_barge_watch_holds_the_wake_microphone_under_the_audio_lock(self):
        # §P2: Jarvis speaking plus the user opening the mic used to mean two
        # PortAudio capture streams on one device, with the wake model hearing the
        # speaker. The watch now owns the device the way the recorder does, and in
        # bounded slices, so a recording can win the lock between slices instead of
        # waiting out one 600-second grab.
        from modules import wakeword
        session, lock, speaker = self.barge_session()
        done = threading.Event()
        beside_a_free_stream, slices = [], []

        def fake_wait(should_stop, capture=True, max_seconds=None, min_threshold=None):
            opened = []

            def try_open():
                opened.append(lock.acquire(blocking=False))
                if opened[0]:
                    lock.release()

            tester = threading.Thread(target=try_open)
            tester.start()
            tester.join(1)
            beside_a_free_stream.append(bool(opened and opened[0]))
            slices.append(max_seconds)
            return b"" if len(slices) == 3 else None     # third slice: "Hey Jarvis"

        with patch.object(wakeword, "wanted", return_value=True), \
                patch.object(wakeword, "ready", return_value=True), \
                patch.object(wakeword, "wait", side_effect=fake_wait):
            session._barge_watch(done)
        self.assertEqual(beside_a_free_stream, [False, False, False])
        self.assertEqual(set(slices), {2.0})
        speaker.stop_speaking.assert_called_once_with()
        self.assertGreater(session.state["awake_until"], time.time())

    def test_barge_hit_after_the_utterance_ended_does_not_cut_the_next_answer(self):
        # A wake word heard while the receipt was already landing belongs to the
        # next turn; cutting then would silence an answer that had not started.
        from modules import wakeword
        session, _lock, speaker = self.barge_session()
        done = threading.Event()

        def late_hit(should_stop, **kwargs):
            done.set()                    # the speech finished during the same slice
            return b""

        with patch.object(wakeword, "wanted", return_value=True), \
                patch.object(wakeword, "ready", return_value=True), \
                patch.object(wakeword, "wait", side_effect=late_hit):
            session._barge_watch(done)
        speaker.stop_speaking.assert_not_called()
        self.assertEqual(session.state["awake_until"], 0.0)

    def test_typed_dur_keeps_the_authoritative_cancel_entry_point(self):
        # §P2: the keyboard had its own stop-word shortcut that turned "dur" into
        # "sus" — speech-only, with no Core cancellation — while the same words
        # from the UI and the phone kept their different authorities. One entry
        # point now owns the vocabulary, so the keyboard cannot silently re-scope it.
        runtime = SimpleNamespace(stop_event=threading.Event(), submit=Mock(),
                                  voice=SimpleNamespace(stop_speaking=Mock()))
        session = VoiceSession.__new__(VoiceSession)
        session.runtime = runtime
        with patch("builtins.input", side_effect=["Dur.", EOFError]):
            session.read_keyboard()
        runtime.submit.assert_called_once_with("Dur.", "yazı")
        runtime.voice.stop_speaking.assert_not_called()


class UserSwitchAudibleStopTests(unittest.TestCase):
    """_switch_user must connect the user change to the real audible stop."""

    def profile(self, slug, name):
        p = SimpleNamespace(slug=slug, name=name, exists=True, data={'prefs': {}, 'goals': []})
        p.save = Mock()
        return p

    def runtime(self, source):
        alice = self.profile('alice', 'Alice')
        rt = SimpleNamespace(
            _cur_source=source, profile=alice, _guest=None, _home=None,
            _get_profile=lambda name: self.profile('bob', 'Bob'),
            _llm=SimpleNamespace(set_user_context=Mock()), set_active=Mock(),
            _sessions=SimpleNamespace(reset=Mock(), _owner=SimpleNamespace(set=Mock())),
            _session=lambda: SimpleNamespace(last_doc=None, pending_level=None,
                                             pending_confirm=None, pending_voice=None,
                                             pending_event_title=None, pending_msg=None,
                                             pending_organize=None),
            log=SimpleNamespace(info=Mock()), slugify=lambda n: n.lower(),
            list_users=lambda: ['Alice', 'Bob'],
        )
        rt.pc_profile = lambda: rt.profile
        return rt

    def test_pc_owner_switch_stops_previous_owner_speech(self):
        from modules import engine_context
        rt = self.runtime('web')
        with patch('modules.voice_runtime.on_owner_switch') as stop, \
                patch('modules.pc_guide.stop'), patch('modules.hooks.observe'):
            engine_context._switch_user(rt, 'Bob')
        stop.assert_called_once_with('alice')   # previous speaker, not the new one

    def test_phone_switch_does_not_stop_pc_speaker(self):
        from modules import engine_context
        rt = self.runtime('telefon')
        with patch('modules.voice_runtime.on_owner_switch') as stop, \
                patch('modules.pc_guide.stop'), patch('modules.hooks.observe'):
            engine_context._switch_user(rt, 'Bob')
        stop.assert_not_called()   # the machine's audible owner did not change

    def test_a_switch_whose_stop_was_not_verified_says_so(self):
        # The greeting is what the new user hears as the switch result, so an
        # unverified stop must not be presented as a clean one. The wording also
        # must not claim a physical device cut nobody verified, while still saying
        # the one guarantee the single output owner does provide: the new user's
        # own answer never plays over the leftover audio.
        from modules import engine_context
        for stopped, expected in ((True, 'Merhaba Bob.'),
                                  (False, 'Merhaba Bob. Önceki kullanıcının sesi')):
            with self.subTest(stopped=stopped):
                rt = self.runtime('web')
                with patch('modules.voice_runtime.on_owner_switch', return_value=stopped) as stop, \
                        patch('modules.pc_guide.stop'), patch('modules.hooks.observe'):
                    message = engine_context._switch_user(rt, 'Bob')
                stop.assert_called_once_with('alice')
                self.assertTrue(message.startswith(expected), message)
                if stopped:
                    self.assertNotIn("Önceki kullanıcının", message)
                else:
                    self.assertIn("kesilemedi", message, message)
                    self.assertIn("üst üste binmez", message, message)
