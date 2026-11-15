"""Real conversation/request orchestration; devices and providers are mocked."""
from contextvars import ContextVar
import concurrent.futures
import copy
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch
import test_engine_modular as fixtures
from modules import app_actions, engine_loop, requests_state as state
from modules.command_manager import PENDING_INPUT_FIELDS
from modules.engine_voice import VoiceSession
from web_chat import WebChat


class ConversationRequestSafetyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for name, value in [('_journal', self.folder/'requests.json'), ('_records', {}),
                            ('_current', ContextVar('safety_request', default=None))]:
            p = patch.object(state, name, value); p.start(); self.addCleanup(p.stop)
        self.runtime = fixtures.ModularEngineTests.context(self)
        self.runtime.requests_state = state
        self.runtime.emit = Mock()
        self.runtime.voice = SimpleNamespace(stop_speaking=Mock())
        self.owner = self.runtime.pc_profile().slug
        self.user = self.runtime.pc_profile().name
        self.runtime.match_user = lambda name: self.user if name in (self.user, self.owner) else None
        profile = self.runtime.profile
        self.runtime._get_profile = lambda name: profile
        from dataclasses import replace
        from modules import brain_entry
        from modules.brain_contracts import RequestKind
        def model(current, text, *, active_context=None):
            # A known explicit desktop protocol owns this fixture turn.
            return replace(current, request_kind=RequestKind.CHAT, arguments={'original_text': text})
        adapter=patch.object(brain_entry, 'apply_model_understanding', side_effect=model)
        adapter.start();self.addCleanup(adapter.stop)
        protocol=patch.object(brain_entry, '_is_explicit_owner_protocol', return_value=True)
        protocol.start();self.addCleanup(protocol.stop)

    def stop(self):
        with patch('modules.pc_guide.stop'):
            self.assertFalse(self.runtime.submit('dur', user=self.user))

    def audio(self):
        path = self.folder/'record.wav'; path.write_bytes(b'fake audio')
        self.runtime.submit_audio(str(path), user=self.user)
        return path, self.runtime.events.get_nowait()

    def test_new_chat_clears_old_approval_and_all_pending_input_only_for_owner(self):
        session = self.runtime._sessions.for_owner(self.owner)
        for name in PENDING_INPUT_FIELDS: setattr(session, name, 'waiting')
        session.pending_action = {'owner':self.owner, 'expires':time.time()+60,
            'stage':'confirm', 'action':'task_delete', 'params':{'tid':1}}
        session.pending_selfcode = {'change':'old'}
        session.last_doc = ('old', '', 'text'); session.speech_override = 'old speech'
        other = self.runtime._sessions.for_owner('other'); other.pending_confirm = 'shutdown'
        before = copy.deepcopy(self.runtime.profile.data)
        self.runtime._pending_photo[self.owner] = {'path':'old', 't':time.time()}
        state.register(self.owner, 'old-command')
        state.register('other','other-command')
        bridge = WebChat(); bridge._runtime = SimpleNamespace(engine=self.runtime,
            _p=lambda:self.runtime.pc_profile(), llm=SimpleNamespace(_histories={self.owner:['old']}))
        bridge._runtime.llm.reset_history = lambda user: bridge._runtime.llm._histories.__setitem__(user, [])
        with patch.object(app_actions, 'run') as run:
            bridge.chat_reset()
            self.assertIsNone(app_actions.continue_voice('tamam', self.runtime._session(), self.runtime.profile, self.runtime.emit))
            run.assert_not_called()
        fresh = self.runtime._session()
        for name in PENDING_INPUT_FIELDS:
            self.assertIn(getattr(fresh, name), (None, False), name)
        self.assertIsNone(fresh.last_doc); self.assertIsNone(fresh.speech_override)
        self.assertIsNone(getattr(fresh, 'pending_selfcode', None))
        self.assertEqual(other.pending_confirm, 'shutdown')
        self.assertEqual(self.runtime.profile.data, before)
        self.assertNotIn(self.owner, self.runtime._pending_photo)
        self.assertFalse(state.is_cancelled(self.owner, 'old-command'))
        self.assertFalse(state.is_cancelled('other','other-command'))

    def test_live_stop_blocks_side_effect_and_restores_context(self):
        self.runtime._cur_rid = 'outer'; self.runtime._cur_source = 'web'
        effect = Mock(); seen = []
        def handle(text):
            seen.append(state._current.get())
            self.stop(); state.check(); effect()
            return 'executed'
        self.runtime.handle = handle
        self.assertIn('iptal', self.runtime._live_command('işlem yap'))
        effect.assert_not_called()
        self.assertIsNotNone(seen[0]); self.assertEqual(seen[0][0], self.owner)
        self.assertTrue(state.is_cancelled(*seen[0]))
        self.assertIsNone(state._current.get())
        self.assertEqual((self.runtime._cur_source, self.runtime._cur_rid), ('web','outer'))

    def test_live_deadline_blocks_side_effect(self):
        effect = Mock()
        def handle(text):
            state._records[state._current.get()]['deadline'] = time.monotonic()-1
            state.check(); effect()
        self.runtime.handle = handle
        self.assertIn('iptal', self.runtime._live_command('işlem yap'))
        effect.assert_not_called(); self.assertIsNone(state._current.get())

    def test_live_stop_from_other_thread_while_command_is_running(self):
        entered,release=threading.Event(),threading.Event();effect=Mock()
        def handle(text):
            entered.set()
            if not release.wait(3): raise AssertionError('command wait timed out')
            state.check();effect();return 'executed'
        self.runtime.handle=handle
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.runtime._live_command,'işlem yap')
            try:
                self.assertTrue(entered.wait(2));self.stop()
            finally:release.set()
            self.assertIn('iptal',future.result(timeout=3))
        effect.assert_not_called()

    def test_bare_stop_does_not_cancel_queued_voice_turn_waiting_for_lock(self):
        effect = Mock()
        self.runtime.handle = lambda text: effect() or 'executed'
        self.runtime._execution_lock.acquire()
        released = False
        rid = None
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.runtime._live_command, 'kilitli işlem')
                for _ in range(100):
                    if state._records:
                        break
                    time.sleep(0.01)
                rid = next(iter(state._records))[1]
                self.assertEqual(state.request_state(self.owner, rid), 'queued')
                self.stop()
                self.assertEqual(state.request_state(self.owner, rid), 'queued')
                self.runtime._execution_lock.release()
                released = True
                self.assertNotIn('iptal', future.result(timeout=3).casefold())
        finally:
            if not released:
                self.runtime._execution_lock.release()
        effect.assert_called_once()
        self.assertFalse(state.is_cancelled(self.owner, rid))

    def test_audio_stop_during_transcription_never_creates_replacement_request(self):
        path, event = self.audio()
        rid = event[4] if len(event)>4 else None
        def transcribe(path):
            self.stop(); return 'işlem yap'
        self.runtime.llm_transcribe = transcribe
        engine_loop._queued_audio(self.runtime, event)
        self.assertFalse(path.exists()); self.assertTrue(self.runtime.events.empty())
        self.assertEqual(list(state._records), [(self.owner, rid)])
        self.assertTrue(state.is_cancelled(self.owner, rid)); self.assertIsNone(state._current.get())

    def test_audio_keeps_one_id_through_transcription_and_execution(self):
        path, event = self.audio(); seen = []
        self.runtime.llm_transcribe = lambda path: seen.append(state._current.get()) or 'merhaba'
        engine_loop._queued_audio(self.runtime, event)
        command = self.runtime.events.get_nowait()
        self.assertEqual(command, ('command','merhaba','telefon',self.user,event[4]))
        self.assertEqual(seen, [(self.owner,event[4])])
        self.assertEqual(state._records[seen[0]]['state'], 'queued')
        with state.activate(self.owner, command[4]): state.check()
        self.assertEqual(state._records[seen[0]]['state'], 'done')
        self.assertFalse(path.exists()); self.assertEqual(len(state._records),1)

    def test_bare_stop_does_not_cancel_queued_audio_transcription(self):
        path, event = self.audio()
        self.stop()
        self.runtime.llm_transcribe = Mock(return_value='merhaba')
        engine_loop._queued_audio(self.runtime, event)
        self.runtime.llm_transcribe.assert_called_once()
        self.assertFalse(path.exists())
        self.assertEqual(self.runtime.events.get_nowait()[4], event[4])
        self.assertFalse(state.is_cancelled(self.owner, event[4]))

    def test_audio_deadline_after_translation_prevents_handoff(self):
        path, event = self.audio()
        def transcribe(path):
            state._records[state._current.get()]['deadline'] = time.monotonic()-1
            return 'işlem yap'
        self.runtime.llm_transcribe = transcribe
        engine_loop._queued_audio(self.runtime, event)
        self.assertTrue(self.runtime.events.empty()); self.assertFalse(path.exists())
        self.assertTrue(state.is_cancelled(self.owner,event[4]))

    def test_audio_stop_from_other_thread_during_provider_wait(self):
        path,event = self.audio()
        entered,release = threading.Event(),threading.Event()
        def transcribe(path):
            entered.set()
            if not release.wait(3): raise AssertionError('test provider wait timed out')
            return 'işlem yap'
        self.runtime.llm_transcribe = transcribe
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(engine_loop._queued_audio,self.runtime,event)
            try:
                self.assertTrue(entered.wait(2));self.stop()
            finally: release.set()
            future.result(timeout=3)
        self.assertTrue(self.runtime.events.empty());self.assertFalse(path.exists())
        self.assertTrue(state.is_cancelled(self.owner,event[4]))

    def test_audio_intake_disk_failure_can_retry_same_id_without_phantom_event(self):
        with patch.object(state,'_save',side_effect=OSError('disk full')),self.assertRaises(OSError):
            self.runtime.submit_audio('record.wav',user=self.user,rid='record-id')
        self.assertTrue(self.runtime.events.empty());self.assertNotIn((self.owner,'record-id'),state._records)
        self.assertTrue(self.runtime.submit_audio('record.wav',user=self.user,rid='record-id'))
        self.assertFalse(self.runtime.submit_audio('record.wav',user=self.user,rid='record-id'))
        self.assertEqual(self.runtime.events.qsize(),1)

    def test_speech_failure_is_visible_in_ui(self):
        # The single owner surfaces an unavailable selected voice as a written UI
        # notice; VoiceSession never opens a second Edge/SAPI path or switches voice.
        # No-voice-switch and per-request identity are owned by test_voice_core /
        # test_voice_edge; this asserts the session-level UI visibility seam.
        lane = Mock()
        lane.say.side_effect = ValueError("selected voice unavailable")
        person = SimpleNamespace(slug='alice', data={'prefs': {'voice': 'tr_kadin', 'rate': 0}})
        runtime = SimpleNamespace(sys=SimpleNamespace(argv=['main.py', '--text']), flags={'speak': True, 'mic': False},
            emit=Mock(), threading=SimpleNamespace(Event=threading.Event, Thread=Mock()),
            profile=person, _record_failure=lambda *a: None)
        with patch('modules.voice_runtime.maybe_start', return_value=(lane, False)):
            session = VoiceSession(runtime)
        session.speak('Merhaba')
        runtime.emit.assert_any_call('system', 'Seçilen ses kullanılamıyor; başka ses kullanılmadı, yanıt yazılı korundu.')

    def test_phone_audio_acceptance_failure_is_reported_and_temp_file_removed(self):
        from modules import phone
        server = phone.PhoneServer(self.runtime,port=0)
        with patch.object(phone,'load_settings',return_value={'phone_scope':'both','phone_allow_http':True}), \
             patch.object(phone,'tailscale_ip',return_value=None),patch.object(phone,'lan_ip',return_value='127.0.0.1'),patch.object(phone,'_harden'), \
             patch.object(phone,'token_user',return_value=self.owner), \
             patch.object(phone.tempfile,'mkstemp',side_effect=lambda prefix,suffix,**kw:(__import__('os').open(self.folder/(prefix+'x'+suffix),__import__('os').O_CREAT|__import__('os').O_RDWR),str(self.folder/(prefix+'x'+suffix)))):
            server.start()
            try:
                url=f'http://127.0.0.1:{server._httpd.server_address[1]}/api/audio'
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for failure in (False,OSError('disk full')):
                    with self.subTest(failure=type(failure).__name__):
                        rejected = Mock(side_effect=failure) if isinstance(failure,Exception) else Mock(return_value=False)
                        with patch.object(self.runtime,'submit_audio',rejected):
                            request=urllib.request.Request(url,data=b'RIFFfake audio',headers={'X-Token':'test'})
                            with self.assertRaises(urllib.error.HTTPError) as result:
                                opener.open(request,timeout=3)
                            self.assertEqual(result.exception.code,400)
                            result.exception.close()
                        self.assertEqual(list(self.folder.glob('jarvis_ses_*.wav')),[])
            finally:server.stop()
