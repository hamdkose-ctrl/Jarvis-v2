"""Exercise the real speech queue without microphone, speakers or network."""
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import test_privacy_voice_and_pending  # Hardware import adapters for this test environment.
from modules import voice

REAL_THREAD = threading.Thread


class VoiceShutdownTests(unittest.TestCase):
    def setUp(self):
        voice._stop_flag.clear()
        self.addCleanup(voice._stop_flag.clear)
        p = patch.object(voice.privacy, 'mode', return_value='normal')
        p.start();self.addCleanup(p.stop)

    def test_stop_during_download_wait_returns_without_waiting_45_seconds(self):
        results = Mock()
        results.empty.return_value = True
        def get(**kwargs):
            voice._stop_flag.set()
            raise queue.Empty
        results.get.side_effect = get
        with patch.object(voice.queue, 'Queue', return_value=results), patch.object(voice.threading, 'Thread'), patch.object(voice, '_play_mp3') as play, patch.object(voice, '_local_say') as local:
            voice.speak('Merhaba')
        results.get.assert_called_once_with(timeout=0.1)
        play.assert_not_called();local.assert_not_called()

    def test_replaced_speech_does_not_play_a_stale_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'stale.mp3';path.write_bytes(b'audio')
            results = Mock();results.empty.return_value = True
            def get(**kwargs):
                voice._seq += 1
                return ('play', str(path), None)
            results.get.side_effect = get
            with patch.object(voice.queue, 'Queue', return_value=results), patch.object(voice.threading, 'Thread'), patch.object(voice, '_play_mp3') as play:
                voice.speak('Merhaba')
            play.assert_not_called();self.assertFalse(path.exists())

    def test_service_timeout_is_still_bounded_without_long_polling(self):
        results = Mock();results.empty.return_value = True;results.get.side_effect = queue.Empty
        with patch.object(voice.queue, 'Queue', return_value=results), patch.object(voice.threading, 'Thread'), patch.object(voice.time, 'monotonic', side_effect=[0, 46]), patch('builtins.print') as output:
            error = voice.speak('Merhaba')
        results.get.assert_called_once_with(timeout=0.1)
        self.assertIn('yanıt vermedi',error)
        self.assertIn('ses tercihin korundu',error)
        output.assert_called_once_with(error)

    def test_late_download_after_stop_removes_its_file_and_never_plays(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            class Communication:
                async def save(self, path):
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError('test download was not released')
                    Path(path).write_bytes(b'audio')
            def producer_thread(*, target, daemon):
                def run():
                    try: target()
                    finally: completed.set()
                return REAL_THREAD(target=run, daemon=daemon)
            with patch.object(voice.edge_tts, 'Communicate', return_value=Communication()), patch.object(voice.tempfile, 'gettempdir', return_value=tmp), patch.object(voice.threading, 'Thread', side_effect=producer_thread), patch.object(voice, '_play_mp3') as play, patch.object(voice, '_local_say') as local:
                consumer = REAL_THREAD(target=voice.speak, args=('Merhaba',))
                consumer.start()
                try:
                    self.assertTrue(entered.wait(1))
                    voice._stop_flag.set()
                    consumer.join(1)
                    self.assertFalse(consumer.is_alive(), 'Stopped speech still blocks the command engine')
                    release.set()
                    self.assertTrue(completed.wait(1))
                    self.assertEqual(list(Path(tmp).glob('*.mp3')), [])
                    play.assert_not_called();local.assert_not_called()
                finally:
                    release.set();consumer.join(2);completed.wait(2)

    def test_playback_exception_cleans_ready_and_unplayed_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / f'{i}.mp3' for i in range(2)]
            results = queue.Queue()
            for path in paths:
                path.write_bytes(b'audio');results.put(('play', str(path), None))
            with patch.object(voice.queue, 'Queue', return_value=results), patch.object(voice.threading, 'Thread'), patch.object(voice, '_play_mp3', side_effect=OSError('speaker failed')):
                message = voice.speak('Merhaba')
            self.assertIn('Windows ses oynatıcısı', message)
            self.assertTrue(all(not p.exists() for p in paths))

    def test_mci_open_failure_raises_before_play(self):
        mci = Mock(side_effect=[0, 263])
        with patch.object(voice.ctypes, 'windll', SimpleNamespace(winmm=SimpleNamespace(mciSendStringW=mci)), create=True):
            with self.assertRaisesRegex(OSError, '263'):
                voice._play_mp3('sample.mp3')
        self.assertEqual([x.args[0].split()[0] for x in mci.call_args_list], ['close', 'open'])

    def test_mci_play_failure_closes_alias(self):
        mci = Mock(side_effect=[0, 0, 277, 0])
        with patch.object(voice.ctypes, 'windll', SimpleNamespace(winmm=SimpleNamespace(mciSendStringW=mci)), create=True):
            with self.assertRaisesRegex(OSError, '277'):
                voice._play_mp3('sample.mp3')
        self.assertEqual([x.args[0].split()[0] for x in mci.call_args_list], ['close', 'open', 'play', 'close'])

    def test_mci_success_opens_plays_and_closes(self):
        mci = Mock(return_value=0)
        with patch.object(voice.ctypes, 'windll', SimpleNamespace(winmm=SimpleNamespace(mciSendStringW=mci)), create=True):
            voice._play_mp3('sample.mp3')
        self.assertEqual([x.args[0].split()[0] for x in mci.call_args_list], ['close', 'open', 'play', 'close'])

    def test_successful_download_uses_requested_voice_and_cleans_file(self):
        completed = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            class Communication:
                async def save(self, path):
                    Path(path).write_bytes(b'audio')
            def producer_thread(*, target, daemon):
                def run():
                    try: target()
                    finally: completed.set()
                return REAL_THREAD(target=run, daemon=daemon)
            with patch.object(voice.edge_tts, 'Communicate', return_value=Communication()) as service, patch.object(voice.tempfile, 'gettempdir', return_value=tmp), patch.object(voice.threading, 'Thread', side_effect=producer_thread), patch.object(voice, '_play_mp3') as play:
                voice.speak('Merhaba', voice='tr-TR-EmelNeural')
                self.assertTrue(completed.wait(1))
                self.assertEqual(service.call_args.args[1], 'tr-TR-EmelNeural')
                play.assert_called_once()
                self.assertEqual(list(Path(tmp).glob('*.mp3')), [])
