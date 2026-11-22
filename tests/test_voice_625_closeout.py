"""Actual voice owner/queue races; only synth/player/wake hardware is fake."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext
import test_engine_modular  # noqa: F401
import test_voice_runtime_bridge as bridge_fixture
from modules import engine_voice, voice_runtime
from modules.voice_core import VoiceCatalog, VoiceCoordinator, VoiceSpec, SpeechRequest


def catalog():
    return VoiceCatalog((VoiceSpec('tr_kadin','Voice','piper','local.onnx'),))


class VoiceCloseoutTests(unittest.TestCase):
    def test_priority_rotation_releases_old_observation_without_waiting_for_queued_audio(self):
        from modules import wakeword
        runtime=SimpleNamespace(stop_event=threading.Event(),flags={'mic':True},WAKE_WORD='Jarvis',
            audio_lock=threading.Lock(),time=SimpleNamespace(time=lambda:100.),
            pc_profile=lambda:SimpleNamespace(slug='alice'),_record_failure=Mock())
        session=engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        session.runtime=runtime;session.voice_lane=SimpleNamespace(receipt_is_current=lambda done:False)
        session.manual_local_stt=False;session.listening_enabled=True
        done=Mock();done.wait.return_value=False;done.is_set.return_value=False
        with patch.object(wakeword,'wanted',return_value=True),patch.object(wakeword,'ready',return_value=True), \
             patch.object(wakeword,'wait') as capture,patch.object(voice_runtime,'interrupt_receipt') as cut:
            self.assertTrue(session._barge_watch(done))
        capture.assert_not_called();cut.assert_not_called();runtime._record_failure.assert_not_called()

    def test_failed_owner_snapshot_releases_observer_for_the_next_speech(self):
        session=engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        session.runtime=SimpleNamespace(threading=threading,stop_event=threading.Event(),
            pc_profile=Mock(side_effect=ValueError('owner snapshot unavailable')),_record_failure=Mock())
        session.voice_lane=SimpleNamespace(outstanding_receipts=lambda owner:())
        session._schedule_barge_watch(threading.Event())
        worker=session._barge_thread
        if worker is not None:worker.join(5);self.assertFalse(worker.is_alive())
        session.runtime._record_failure.assert_called_once_with('modules/engine_voice.py:barge_loop')
        self.assertIsNone(session._barge_thread)
        session.runtime.pc_profile.side_effect=None
        session.runtime.pc_profile.return_value=SimpleNamespace(slug='alice')
        session._schedule_barge_watch(threading.Event())
        worker=session._barge_thread
        if worker is not None:worker.join(5);self.assertFalse(worker.is_alive())
        self.assertIsNone(session._barge_thread)

    def test_capture_wait_revalidates_owner_and_ttl_before_playback(self):
        import tempfile
        for changed in ('owner','ttl'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
                runtime=bridge_fixture.runtime(directory);runtime.pc_profile=lambda:runtime.profile
                held=threading.Lock();held.acquire();attempted=threading.Event();played=Mock()
                class CaptureLock:
                    def acquire(self,timeout):attempted.set();return held.acquire(timeout=timeout)
                    def release(self):held.release()
                runtime.audio_lock=CaptureLock()
                lane=voice_runtime.VoiceLane(runtime,catalog(),lambda spec,text,cancel:b'audio',lambda audio,cancel,start:(played(),start()))
                now=[0.];lane._coordinator._clock=lambda:now[0]
                try:
                    done=lane.say('alice','tr_kadin','waiting audio',ttl_seconds=1)
                    self.assertTrue(attempted.wait(5))
                    if changed=='owner':runtime.profile=SimpleNamespace(slug='bob',data={'prefs':{'voice':'tr_kadin'}})
                    else:now[0]=2.
                    held.release();self.assertTrue(done.wait(5));played.assert_not_called()
                finally:
                    if held.locked():held.release()
                    lane.close();lane._coordinator._worker.join(10)
                    self.assertFalse(lane._coordinator._worker.is_alive())

    def test_owner_switch_during_cut_does_not_open_the_new_owners_wake_window(self):
        from modules import wakeword
        runtime=SimpleNamespace(
            stop_event=threading.Event(),flags={'mic':True},WAKE_WORD='Jarvis',
            audio_lock=threading.Lock(),time=SimpleNamespace(time=lambda:100.),
            SESSION_SECONDS=60,profile=SimpleNamespace(slug='alice'),log=Mock())
        runtime.pc_profile=lambda:runtime.profile
        session=engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        session.runtime=runtime;session.voice_lane=object();session.manual_local_stt=False
        session.listening_enabled=True;session.state={'awake_until':0.}
        done=Mock();done.wait.return_value=False;done.is_set.return_value=False
        def cut(*args):runtime.profile=SimpleNamespace(slug='bob');return True
        with patch.object(wakeword,'wanted',return_value=True),patch.object(wakeword,'ready',return_value=True), \
             patch.object(wakeword,'wait',return_value=b'wake'), \
             patch.object(engine_voice,'_physical_mic_claim',return_value=nullcontext()), \
             patch.object(voice_runtime,'interrupt_receipt',side_effect=cut):
            session._barge_watch(done)
        self.assertEqual(session.state['awake_until'],0.)

    def test_shutdown_inside_followup_mic_lock_opens_no_second_stream(self):
        import test_voice_device_handoff_guard as fixture
        lane=fixture._session().voice_lane;lane.busy_event=threading.Event()
        stop=threading.Event()
        class StopAtSecondLock(fixture._RaceAtSecondMicLock):
            def __enter__(self):
                result=super().__enter__()
                lane.is_busy.return_value=False  # Isolate shutdown from speaker-busy.
                return result
        runtime=SimpleNamespace(
            stop_event=stop,pause_listening=threading.Event(),flags={'mic':True},WAKE_WORD='Jarvis',
            mic_cancel=threading.Event(),speech_pending=threading.Event(),
            time=SimpleNamespace(time=lambda:100.),
            audio_lock=StopAtSecondLock(lane,stop),
            voice=SimpleNamespace(recognize=Mock(return_value='jarvis'),capture=Mock(return_value=b'first'),last_noise=1),
            _AnyAbort=lambda *events:None,find_wake=lambda text:0,_strip_wake=lambda text:'',
            _tr_lower=str.lower,events=SimpleNamespace(put=Mock()),emit=Mock(),log=Mock(),_record_failure=Mock())
        session=fixture.WakeFollowupRaceTests.session(runtime,lane)
        session.offline_wake_step=Mock(return_value=False);session.submit_voice=Mock()
        session.listen_for_wake_word()
        self.assertEqual(runtime.voice.capture.call_count,1)
        self.assertEqual(runtime.audio_lock.count,2)
        session.submit_voice.assert_not_called()
        runtime._record_failure.assert_not_called()

    def test_playback_waits_for_an_already_open_capture_and_stays_cancellable(self):
        import tempfile
        for cancel_before_start in (False,True):
            with self.subTest(cancel=cancel_before_start),tempfile.TemporaryDirectory() as directory:
                runtime=bridge_fixture.runtime(directory)
                held=threading.Lock();held.acquire();attempted=threading.Event();played=Mock()
                class CaptureLock:
                    def acquire(self,timeout):attempted.set();return held.acquire(timeout=timeout)
                    def release(self):held.release()
                runtime.audio_lock=CaptureLock()
                def play(audio,cancel,start):played();start()
                lane=voice_runtime.VoiceLane(runtime,catalog(),lambda spec,text,cancel:b'audio',play)
                try:
                    done=lane.say('alice','tr_kadin','pending audio')
                    self.assertTrue(attempted.wait(5),'output never checked the capture owner')
                    played.assert_not_called()
                    if cancel_before_start:
                        lane.interrupt()
                        self.assertTrue(done.wait(5),'cancel waited for a physically busy microphone')
                        played.assert_not_called()
                    else:
                        held.release()
                        self.assertTrue(done.wait(5))
                        played.assert_called_once()
                finally:
                    if held.locked():held.release()
                    lane.close();lane._coordinator._worker.join(10)
                    self.assertFalse(lane._coordinator._worker.is_alive())

    def test_targeted_runtime_cut_mutes_the_receipts_owner_not_the_new_profile(self):
        import tempfile
        from modules import requests_state
        with tempfile.TemporaryDirectory() as directory:
            runtime=bridge_fixture.runtime(directory)
            runtime.pc_profile=lambda:runtime.profile
            entered=threading.Event()
            def play(audio,cancel,start):
                start();entered.set();self.assertTrue(cancel.wait(10))
            lane=voice_runtime.VoiceLane(runtime,catalog(),lambda spec,text,cancel:b'audio',play)
            try:
                done=lane.say('alice','tr_kadin','first',turn_id='observed-turn')
                self.assertTrue(entered.wait(5))
                runtime.profile=SimpleNamespace(slug='bob',data={'prefs':{'voice':'tr_kadin'}})
                with patch.object(voice_runtime,'active',return_value=lane), \
                     patch.object(requests_state,'mute_speech') as mute:
                    self.assertTrue(voice_runtime.interrupt_receipt(lane,done))
                    mute.assert_called_once_with('alice','observed-turn')
                    self.assertTrue(done.wait(5))
                    self.assertFalse(voice_runtime.interrupt_receipt(lane,done))
                    self.assertEqual(mute.call_count,1)
            finally:
                lane.close();lane._coordinator._worker.join(10)
                self.assertFalse(lane._coordinator._worker.is_alive())

    def test_thread_start_failure_keeps_original_error_and_resets_observer(self):
        session=engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        factory=Mock(return_value=SimpleNamespace(start=Mock(side_effect=RuntimeError('cannot start'))))
        session.runtime=SimpleNamespace(threading=SimpleNamespace(Thread=factory),_record_failure=Mock())
        with self.assertRaisesRegex(RuntimeError,'cannot start'):
            session._schedule_barge_watch(threading.Event())
        session.runtime._record_failure.assert_called_once()
        self.assertIsNone(session._barge_thread)
        self.assertIsNone(session._barge_pending)

    def test_observer_error_is_reported_and_does_not_leave_a_dead_worker_slot(self):
        session=engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        session.runtime=SimpleNamespace(threading=threading,stop_event=threading.Event(),_record_failure=Mock())
        session._barge_watch=Mock(side_effect=ValueError('wake failed'))
        session._schedule_barge_watch(threading.Event())
        worker=session._barge_thread
        if worker is not None:worker.join(5);self.assertFalse(worker.is_alive())
        session.runtime._record_failure.assert_called_once_with('modules/engine_voice.py:barge_loop')
        self.assertIsNone(session._barge_thread)

    def test_cancelled_last_notice_does_not_hide_middle_live_speech_from_barge(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            runtime=bridge_fixture.runtime(directory)
            runtime.stop_event=threading.Event();runtime.flags['mic']=True
            factory=Mock(side_effect=lambda **kwargs:threading.Thread(**kwargs))
            runtime.threading=SimpleNamespace(Thread=factory)
            entered,release,observed,watch_started=threading.Event(),threading.Event(),threading.Event(),threading.Event()
            seen=[]
            def play(audio,cancel,start):
                start()
                if audio==b'first':entered.set();self.assertTrue(release.wait(10))
                if audio==b'middle':self.assertTrue(observed.wait(10))
            lane=voice_runtime.VoiceLane(runtime,catalog(),lambda spec,text,cancel:text.encode(),play)
            actual_say=lane.say;accepted={}
            def say(*args,**kwargs):
                done=actual_say(*args,**kwargs);accepted[args[2]]=done;return done
            lane.say=say
            session=engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
            session.runtime=runtime;session.voice_lane=lane;session.speak_enabled=True
            def watch(done):
                seen.append(done)
                if len(seen)==1:watch_started.set()
                else:observed.set()
                self.assertTrue(done.wait(10))
            session._barge_watch=watch
            try:
                session.speak('first',shown=True,identity={'event_id':'first'})
                self.assertTrue(entered.wait(5));self.assertTrue(watch_started.wait(5))
                session.speak('middle',shown=True,identity={'event_id':'middle'})
                session.speak('last',shown=True,identity={'event_id':'last'})
                lane.invalidate(event_id='last')
                release.set()
                self.assertTrue(observed.wait(5),'cancelled newest receipt discarded the still-live middle receipt')
                self.assertEqual(seen,[accepted['first'],accepted['middle']])
                self.assertEqual(factory.call_count,1)
            finally:
                release.set();observed.set();runtime.stop_event.set()
                worker=getattr(session,'_barge_thread',None)
                session.close()
                if worker is not None:worker.join(10);self.assertFalse(worker.is_alive())
                lane._coordinator._worker.join(10)
                self.assertFalse(lane._coordinator._worker.is_alive())

    def test_observer_selects_actual_foreground_ahead_of_older_queued_notice(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            runtime=bridge_fixture.runtime(directory)
            entered,release,foreground_started,finish= [threading.Event() for _ in range(4)]
            def play(audio,cancel,start):
                start()
                if audio==b'first':entered.set();self.assertTrue(release.wait(10))
                if audio==b'foreground':foreground_started.set();self.assertTrue(finish.wait(10))
            lane=voice_runtime.VoiceLane(runtime,catalog(),lambda spec,text,cancel:text.encode(),play)
            try:
                first=lane.say('alice','tr_kadin','first')
                self.assertTrue(entered.wait(5))
                notice=lane.say('alice','tr_kadin','notice',background=True)
                foreground=lane.say('alice','tr_kadin','foreground')
                release.set();self.assertTrue(foreground_started.wait(5))
                self.assertTrue(first.is_set());self.assertFalse(notice.is_set())
                self.assertIs(lane.outstanding_receipts('alice')[0],foreground)
                self.assertFalse(lane.receipt_is_current(notice))
                self.assertTrue(lane.receipt_is_current(foreground))
            finally:
                release.set();finish.set();lane.close();lane._coordinator._worker.join(10)
                self.assertFalse(lane._coordinator._worker.is_alive())

    def test_targeted_cut_cannot_interrupt_the_next_active_receipt(self):
        entered,release=threading.Event(),threading.Event()
        cancel_seen=[]
        def play(audio,cancel,start):
            cancel_seen.append(cancel);start();entered.set();self.assertTrue(release.wait(10))
        coordinator=VoiceCoordinator(catalog(),lambda spec,text,cancel:b'audio',play,lambda receipt:None)
        try:
            coordinator.submit(SpeechRequest('alice','next','tr_kadin','next'))
            self.assertTrue(entered.wait(5))
            self.assertEqual(coordinator.interrupt_speech(expected_request_id='old'),())
            self.assertFalse(cancel_seen[0].is_set())
        finally:
            release.set();coordinator.close();coordinator._worker.join(10)
            self.assertFalse(coordinator._worker.is_alive())

    def test_targeted_cut_preserves_other_owners_waiting_audio(self):
        entered,other_played=threading.Event(),threading.Event()
        def play(audio,cancel,start):
            start()
            if audio==b'alice':entered.set();self.assertTrue(cancel.wait(10))
            else:other_played.set()
        receipts=[]
        coordinator=VoiceCoordinator(catalog(),lambda spec,text,cancel:text.encode(),play,receipts.append)
        try:
            coordinator.submit(SpeechRequest('alice','active','tr_kadin','alice'))
            self.assertTrue(entered.wait(5))
            coordinator.submit(SpeechRequest('bob','waiting','tr_kadin','bob',lane='background'))
            stopped=coordinator.interrupt_speech(expected_request_id='active')
            self.assertEqual([row.owner for row in stopped],['alice'])
            self.assertTrue(other_played.wait(5),'targeted cut invalidated an unrelated owner generation')
        finally:
            coordinator.close();coordinator._worker.join(10);self.assertFalse(coordinator._worker.is_alive())
