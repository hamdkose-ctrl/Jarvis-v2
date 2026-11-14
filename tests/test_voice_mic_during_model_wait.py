"""VOICE P3: a bounded provider wait must not keep the microphone deaf.

Real chain, read from the code before writing this file:
  `engine_loop.main` drains `runtime.events` on one thread and runs the turn inside
  `runtime.as_user(...)` (which holds `runtime._execution_lock`) while `submit_voice`
  holds `runtime.pause_listening`.  `canonical_goal_flow._try_create_planned` asks the
  planner through `model_wait.ask(..., seconds=60)`, and that call blocks the loop
  thread.  `listen_for_wake_word` refuses to capture while `pause_listening` is set, so
  Jarvis was provably deaf for the whole turn even though the planner's own answer
  invites the user to keep talking.

The fix re-opens only the wait window.  These tests pin both halves: the microphone
comes back while the provider is answering, and the identity lock, the owner's queue,
the "sus"/"dur" scopes, the deadline and the late-answer fence are unchanged.
"""
import contextlib
import inspect
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modules import engine_loop, engine_voice, llm, model_wait, requests_state
from modules.engine_voice import VoiceSession


def _session(runtime, lane=None, manual=False, listening=True):
    """A VoiceSession carrying only the fields the microphone gate really reads."""
    session = VoiceSession.__new__(VoiceSession)
    session.runtime = runtime
    session.listening_enabled = listening
    session.manual_local_stt = manual
    session.voice_lane = lane
    session.state = {"awake_until": 0.0}
    return session


class ForegroundSeam(unittest.TestCase):
    """`model_wait` may hand the interaction layer back while it waits, nothing else."""

    def setUp(self):
        self.token = llm._key_context.set('voice-p3-tests')
        self.addCleanup(llm._key_context.reset, self.token)
        model_wait._PENDING.pop('voice-p3-tests', None)   # an earlier test's worker is not this one's fence
        failures = patch.object(model_wait, '_record_failure')
        self.failures = failures.start()
        self.addCleanup(failures.stop)

    def _drain(self):
        deadline = time.monotonic() + 5
        while model_wait._PENDING.get('voice-p3-tests') and time.monotonic() < deadline:
            time.sleep(.001)

    def test_the_foreground_window_holds_the_answer_wait_and_closes_after_it(self):
        answered = threading.Event()
        log = []

        class Scope:
            def __enter__(self):
                log.append(('enter', answered.is_set()))
                return self

            def __exit__(self, *exc):
                log.append(('exit', answered.is_set()))
                return False

        def model(*args, **kwargs):
            time.sleep(.05)
            answered.set()
            return 'answer'

        with patch.object(llm, 'ask', side_effect=model), model_wait.foreground(lambda: Scope()):
            self.assertEqual(model_wait.ask('question', seconds=5), 'answer')
        self.assertEqual([entry[0] for entry in log], ['enter', 'exit'])
        self.assertFalse(log[0][1], 'the window opened after the provider had already answered')
        self.assertTrue(log[1][1], 'the window closed before the provider answered')
        self.failures.assert_not_called()
        self.assertIsNone(model_wait._FOREGROUND.get())

    def test_primary_brain_smart_router_opens_actual_mic_wait_scope(self):
        # The primary semantic model bypasses model_wait.ask and calls the
        # Smart Router directly. This regression exercises its production seam,
        # not just the wrapper around brain_entry.prepare.
        from modules import brain_model_understanding as primary
        from modules.brain_contracts import (
            UnderstandingResult, RequestKind, ConversationRelation,
            TemporalNeed, Confidence,
        )
        current = UnderstandingResult(
            owner='voice-p3-tests', request_id='semantic-1',
            request_kind=RequestKind.CHAT, capability_hint=None,
            arguments={}, conversation_relation=ConversationRelation.NEW_REQUEST,
            temporal_need=TemporalNeed.UNSURE, confidence=Confidence.MEDIUM,
        )
        phases = []

        @contextlib.contextmanager
        def scope():
            phases.append('entered')
            try:
                yield
            finally:
                phases.append('exited')

        def router(*args, **kwargs):
            phases.append('provider-called')
            return '{}'  # invalid model proposal, but no live provider used

        with patch.object(llm, 'provider', return_value='groq'), \
                patch.object(llm.privacy, 'mode', return_value='normal'), \
                patch('modules.smart_router.selection', return_value={'candidates': ['groq']}), \
                patch('modules.smart_router.run', side_effect=router):
            with model_wait.foreground(scope):
                primary.propose(owner='voice-p3-tests', text='Merhaba',
                                current=current, arguments={})
        self.assertEqual(phases, ['entered', 'provider-called', 'exited'])
        self.assertIsNone(model_wait._FOREGROUND.get())

    def test_without_a_foreground_hook_the_wait_result_and_contracts_are_unchanged(self):
        with patch.object(llm, 'ask', return_value='answer') as model:
            self.assertEqual(model_wait.ask('question', seconds=5), 'answer')
        model.assert_called_once_with('question', system='', max_tokens=2000)
        self.failures.assert_not_called()

    def test_a_foreground_hook_never_reaches_the_provider_thread(self):
        seen = []

        def model(*args, **kwargs):
            seen.append(model_wait._FOREGROUND.get())
            return 'answer'

        with patch.object(llm, 'ask', side_effect=model), \
                model_wait.foreground(lambda: contextlib.nullcontext()):
            self.assertEqual(model_wait.ask('question', seconds=5), 'answer')
        self.assertEqual(seen, [None], 'a provider thread must never own the caller microphone')

    def test_a_failing_foreground_factory_cannot_change_the_provider_answer(self):
        def factory():
            raise RuntimeError('broken hook')

        with patch.object(llm, 'ask', return_value='answer'), model_wait.foreground(factory):
            self.assertEqual(model_wait.ask('question', seconds=5), 'answer')
        self.failures.assert_called_once_with('modules/model_wait.py:foreground')

    def test_a_failing_foreground_exit_cannot_change_the_provider_answer(self):
        class BrokenExit:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                raise RuntimeError('exit failed')

        with patch.object(llm, 'ask', return_value='answer'), \
                model_wait.foreground(lambda: BrokenExit()):
            self.assertEqual(model_wait.ask('question', seconds=5), 'answer')
        self.failures.assert_called_once_with('modules/model_wait.py:foreground_exit')

    def test_the_window_closes_when_the_model_wait_times_out(self):
        release = threading.Event()
        stopped = threading.Event()

        def model(*args, **kwargs):
            try:
                release.wait(2)
                return 'late answer'
            finally:
                stopped.set()

        depth = {'now': 0, 'max': 0}

        class Scope:
            def __enter__(self):
                depth['now'] += 1
                depth['max'] = max(depth['max'], depth['now'])
                return self

            def __exit__(self, *exc):
                depth['now'] -= 1
                return False

        try:
            with patch.object(llm, 'ask', side_effect=model), model_wait.foreground(lambda: Scope()):
                with self.assertRaisesRegex(model_wait.ModelWaitTimeout, 'yanıt vermedi'):
                    model_wait.ask('question', seconds=.05)
            self.assertEqual(depth, {'now': 0, 'max': 1})
            with self.assertRaisesRegex(RuntimeError, 'henüz kapanmadı'):
                model_wait.ask('second', seconds=.05)
        finally:
            release.set()
            self.assertTrue(stopped.wait(2), 'the provider worker never unwound')
            self._drain()
        self.assertIsNone(model_wait._PENDING.get('voice-p3-tests'))

    def test_the_window_closes_when_the_turn_is_cancelled(self):
        started = threading.Event()
        release = threading.Event()
        stopped = threading.Event()

        def model(*args, **kwargs):
            started.set()
            try:
                release.wait(2)
                return 'late answer'
            finally:
                stopped.set()

        polls = []

        def check():
            if len(polls) > 1:
                raise requests_state.Cancelled('iptal')
            polls.append(1)

        closed = []

        class Scope:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                closed.append(True)
                return False

        try:
            with patch.object(llm, 'ask', side_effect=model), model_wait.foreground(lambda: Scope()):
                with self.assertRaises(requests_state.Cancelled):
                    model_wait.ask('question', seconds=5, check=check)
            self.assertEqual(closed, [True], 'a cancelled turn left the microphone window open')
            self.assertTrue(started.is_set(), 'the provider call was not in flight when the turn cancelled')
            self.assertFalse(stopped.is_set(), 'the cancelled provider had already finished')
        finally:
            release.set()
            self.assertTrue(stopped.wait(2), 'the provider worker never unwound')
            self._drain()
        self.assertIsNone(model_wait._PENDING.get('voice-p3-tests'))


class MicrophoneGate(unittest.TestCase):
    """Which windows are allowed to re-open the existing `pause_listening` switch."""

    def setUp(self):
        self.pause = threading.Event()
        self.pause.set()                     # an engine turn owns the microphone
        self.runtime = SimpleNamespace(flags={'mic': True}, pause_listening=self.pause,
                                       emit=Mock(), log=Mock())
        settings = patch('config.load_settings', return_value={})
        settings.start()
        self.addCleanup(settings.stop)

    def test_the_microphone_reopens_only_inside_the_wait_window(self):
        session = _session(self.runtime)
        with session.mic_open_during_model_wait():
            self.assertFalse(self.pause.is_set())
        self.assertTrue(self.pause.is_set())

    def test_a_turn_that_never_paused_the_microphone_is_left_as_it_was(self):
        self.pause.clear()
        session = _session(self.runtime)
        with session.mic_open_during_model_wait():
            self.assertFalse(self.pause.is_set())
        self.assertFalse(self.pause.is_set(), 'a text/web turn got its microphone claim revoked')

    def test_the_gate_is_restored_when_the_wait_raises(self):
        session = _session(self.runtime)
        with self.assertRaises(RuntimeError):
            with session.mic_open_during_model_wait():
                raise RuntimeError('provider failed')
        self.assertTrue(self.pause.is_set())

    def test_the_setting_off_keeps_the_previous_behaviour(self):
        with patch('config.load_settings', return_value={'voice_mic_during_model_wait': False}):
            session = _session(self.runtime)
            with session.mic_open_during_model_wait():
                self.assertTrue(self.pause.is_set())
        self.assertTrue(self.pause.is_set())

    def test_playback_manual_stt_text_mode_and_muted_mic_never_reopen_the_gate(self):
        for name, kwargs, lane in [
            ('speaker busy', {}, SimpleNamespace(is_busy=lambda: True,
                                                 stop_unconfirmed=lambda: False)),
            ('cut not confirmed', {}, SimpleNamespace(is_busy=lambda: False,
                                                      stop_unconfirmed=lambda: True)),
            ('local stt', {'manual': True}, None),
            ('text mode', {'listening': False}, None),
            ('mic flag off', {}, None),
        ]:
            with self.subTest(case=name):
                runtime = self.runtime
                if name == 'mic flag off':
                    runtime = SimpleNamespace(flags={'mic': False}, pause_listening=self.pause,
                                              emit=Mock(), log=Mock())
                session = _session(runtime, lane=lane, **kwargs)
                with session.mic_open_during_model_wait():
                    self.assertTrue(self.pause.is_set())

    def test_every_microphone_gate_reads_the_same_speaker_proof(self):
        """The wake-word loop, its capture window and the P3 wait all read one predicate.

        A cut the device never admitted (`stop_unconfirmed`) is news about the
        speaker that `is_busy()` alone does not carry, and the handoff/UI idle
        paths already read both. If one of the three gates keeps its own private
        condition, the always-on listener goes deaf or hears Jarvis while
        push-to-talk behaves differently about the same speaker.
        """
        for kind in ('offline_wake_step', 'listen_for_wake_word'):
            with self.subTest(gate=kind):
                source = inspect.getsource(getattr(VoiceSession, kind))
                self.assertIn('speech_blocks_mic()', source)
        self.assertNotIn('is_busy()', inspect.getsource(VoiceSession.mic_open_during_model_wait))
        lane = SimpleNamespace(is_busy=lambda: False, stop_unconfirmed=lambda: True)
        self.assertTrue(_session(self.runtime, lane=lane).speech_blocks_mic())

    def test_no_speech_lane_means_the_speaker_is_not_occupied(self):
        self.assertFalse(_session(self.runtime).speech_blocks_mic())


class TurnWiring(unittest.TestCase):
    """The seam is installed by the engine turn, not by a test helper."""

    def test_the_turn_installs_the_session_gate_around_the_handoff(self):
        session = _session(SimpleNamespace(flags={'mic': True}, pause_listening=threading.Event(),
                                           emit=Mock(), log=Mock()))
        seen = {}

        def handoff():
            seen['hook'] = model_wait._FOREGROUND.get()
            return ('out', None, None)

        result = engine_loop._turn_with_listening_foreground(session, handoff)
        self.assertEqual(result, ('out', None, None))
        self.assertIs(seen['hook'].__func__, VoiceSession.mic_open_during_model_wait)
        self.assertIsNone(model_wait._FOREGROUND.get())

    def test_a_session_without_the_seam_runs_the_turn_exactly_as_before(self):
        """Borrowed engine tests hand the loop a stub session; the turn must still run once.

        Reading a missing attribute raised AttributeError inside `engine_loop.main`, whose
        except path swallowed it and the loop blocked forever on the empty event queue.
        """
        calls = []
        result = engine_loop._turn_with_listening_foreground(
            SimpleNamespace(), lambda: (calls.append('handoff'), ('out', None, None))[1])
        self.assertEqual(result, ('out', None, None))
        self.assertEqual(calls, ['handoff'])
        self.assertIsNone(model_wait._FOREGROUND.get())

    def test_the_seam_takes_no_lock_and_no_second_owner(self):
        import inspect
        source = inspect.getsource(engine_loop._turn_with_listening_foreground)
        for forbidden in ('Lock', 'acquire', 'Thread', 'submit'):
            self.assertNotIn(forbidden, source, f'the seam must not touch {forbidden}')

    def test_the_loop_routes_primary_understanding_and_handoff_through_same_seam(self):
        import inspect
        source = inspect.getsource(engine_loop.main)
        # Both primary semantic interpretation and the later Core handoff may
        # block on the model. Neither may close the microphone just for a wait.
        # Primary semantic understanding, normal Core handoff, and the
        # user-authorized exact-ID legacy foreground continuation share this
        # SAME microphone hook. None creates a second execution owner.
        self.assertEqual(source.count('_turn_with_listening_foreground'), 3)
        self.assertIn('brain_entry.prepare', source)
        self.assertIn('brain_entry.handoff', source)
        self.assertIn('runtime.as_user', source)          # identity still wraps the turn


class LongJobStaysHeard(unittest.TestCase):
    """The user-visible contract: the planner keeps working, the microphone keeps listening."""

    def setUp(self):
        wanted = patch('modules.wakeword.wanted', return_value=False)   # Google path, no offline wake
        wanted.start()
        self.addCleanup(wanted.stop)
        self.token = llm._key_context.set('voice-p3-tests')
        self.addCleanup(llm._key_context.reset, self.token)

    def _runtime(self):
        runtime = SimpleNamespace(
            stop_event=threading.Event(), pause_listening=threading.Event(),
            flags={'mic': True}, audio_lock=threading.RLock(), time=time, log=Mock(),
            emit=Mock(), _record_failure=Mock(), WAKE_WORD='Jarvis',
            mic_cancel=threading.Event(), _AnyAbort=lambda *events: object(),
            _execution_lock=threading.RLock())
        captured = []

        def capture(timeout=0, **kwargs):
            captured.append(time.monotonic())
            return b''                     # the device is free again: only bytes so far

        def recognize(raw, *args, **kwargs):
            return ''                      # nothing recognisable: the loop keeps listening

        runtime.voice = SimpleNamespace(capture=capture, recognize=recognize, last_noise=1)
        runtime.captured = captured
        return runtime

    def _planner_turn(self, runtime, session, release, blocking):
        """The production turn seam around the bounded wait the canonical planner really uses."""
        def model(*args, **kwargs):
            blocking.set()
            release.wait(20)
            return '{"operations": []}'

        def turn():
            # `runtime.as_user` holds `_execution_lock` for the whole engine turn; the
            # test reproduces that claim so the microphone cannot be bought by dropping it.
            with runtime._execution_lock:
                return engine_loop._turn_with_listening_foreground(
                    session, lambda: model_wait.ask('plan', seconds=20))

        with patch.object(llm, 'ask', side_effect=model):
            thread = threading.Thread(target=turn, daemon=True, name='planner-turn')
            thread.start()
            self.assertTrue(blocking.wait(5), 'the planner never reached the provider call')
        return thread

    def _listener(self, session):
        runtime = session.runtime
        listener = threading.Thread(target=session.listen_for_wake_word, daemon=True, name='wake-listener')
        listener.start()
        self.addCleanup(lambda: (runtime.stop_event.set(), listener.join(5)))
        return listener

    def test_a_spoken_follow_up_is_captured_while_the_planner_waits(self):
        runtime = self._runtime()
        session = _session(runtime)
        runtime.pause_listening.set()          # `submit_voice` holds it for the whole turn
        self._listener(session)
        release, blocking = threading.Event(), threading.Event()
        thread = self._planner_turn(runtime, session, release, blocking)
        try:
            deadline = time.monotonic() + 5
            while not runtime.captured and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(runtime.captured,
                            'the wake-word loop stayed deaf while the planner was only waiting')
            self.assertFalse(runtime.pause_listening.is_set())
            self.assertTrue(blocking.is_set(), 'the planner answer had already arrived')
            acquired = runtime._execution_lock.acquire(blocking=False)
            if acquired:
                runtime._execution_lock.release()
            self.assertFalse(acquired, 'the microphone was opened by dropping the identity lock')
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertTrue(runtime.pause_listening.is_set(), 'the turn lost its microphone claim')

    def test_a_disabled_setting_keeps_the_old_deaf_behaviour(self):
        runtime = self._runtime()
        session = _session(runtime)
        runtime.pause_listening.set()
        self._listener(session)
        release, blocking = threading.Event(), threading.Event()
        with patch('config.load_settings', return_value={'voice_mic_during_model_wait': False}):
            thread = self._planner_turn(runtime, session, release, blocking)
            try:
                time.sleep(.4)
                self.assertEqual(runtime.captured, [], 'the opt-out did not keep the previous behaviour')
                self.assertTrue(runtime.pause_listening.is_set())
            finally:
                release.set()
                thread.join(10)

    def test_the_follow_up_reaches_the_queue_without_waiting_for_the_planner(self):
        """`engine_queue.submit` runs on the caller thread, so a new utterance is accepted."""
        from modules import engine_queue
        self.queued = []
        runtime = self._runtime()
        runtime.events = SimpleNamespace(put=self.queued.append)
        runtime.requests_state = SimpleNamespace(
            register=lambda owner, rid, **kwargs: True,
            cancel=lambda owner: None,
        )
        runtime.slugify = lambda name: name
        runtime.pc_profile = lambda: SimpleNamespace(name='Hamdi', slug='Hamdi')
        runtime._emit_for = Mock()
        runtime.secrets = SimpleNamespace(token_hex=lambda n: 'rid')
        runtime._tr_lower = lambda text: text.lower()
        session = _session(runtime)
        runtime.pause_listening.set()
        release, blocking = threading.Event(), threading.Event()
        thread = self._planner_turn(runtime, session, release, blocking)
        result = {}
        try:
            with patch('modules.brain_entry.fast_lane', return_value=None):
                caller = threading.Thread(
                    target=lambda: result.update(
                        accepted=engine_queue.submit(runtime, 'hava durumu', 'ses')),
                    daemon=True)
                caller.start()
                caller.join(5)
            self.assertFalse(caller.is_alive(), 'queueing a follow-up waited for the planner')
            self.assertTrue(result['accepted'])
            self.assertEqual(self.queued[0][0], 'command')
            self.assertEqual([event[1] for event in self.queued], ['hava durumu'])
            self.assertEqual(self.queued[0][2], 'ses')
            notice = runtime._emit_for.call_args.args
            self.assertEqual(notice[1], 'system')
            self.assertIn('sıraya alındı', notice[2])
        finally:
            release.set()
            thread.join(10)

    def test_sus_still_mutes_immediately_while_the_planner_waits(self):
        from modules import engine_queue
        runtime = self._runtime()
        runtime.voice = SimpleNamespace(capture=lambda **k: b'', recognize=lambda *a, **k: '',
                                        last_noise=1, stop_speaking=Mock())
        runtime._tr_lower = lambda text: text.lower()
        session = _session(runtime)
        runtime.pause_listening.set()
        release, blocking = threading.Event(), threading.Event()
        thread = self._planner_turn(runtime, session, release, blocking)
        try:
            # The seam itself may hold the gate open during the wait; the contract here is
            # that "sus" neither takes the turn's microphone claim nor hands it back.
            claimed_before = runtime.pause_listening.is_set()
            self.assertFalse(engine_queue.submit(runtime, 'sus', 'ses'))
            runtime.voice.stop_speaking.assert_called_once_with()
            self.assertTrue(blocking.is_set(), 'the planner was interrupted by the mute word')
            self.assertEqual(runtime.pause_listening.is_set(), claimed_before,
                             '"sus" changed the turn microphone claim')
        finally:
            release.set()
            thread.join(10)


if __name__ == '__main__':
    unittest.main()
