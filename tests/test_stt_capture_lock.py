"""The microphone is claimed only while it records, not while a provider reads.

Real chain, read from the code before writing this file: `engine_loop.main` handles
the push-to-talk `('listen',)` event and the wake-word listener captures on the same
physical device, both inside `runtime.audio_lock` and around `voice.listen(...)`.
`voice.listen` closed its PortAudio stream and then awaited Gemini or the Google web
service, so the last frames of silence were followed by an unbounded network wait
that still owned the only capture device — and the Google call had no timeout at all.

`voice.capture` is now the device step and `voice.recognize` the text step, so the
callers hold the lock over the first and release it before the second. These tests
pin both halves: the recorder still owns the microphone while it records, and the
recognition wait runs with the lock free and a bounded provider request.
"""
import contextlib
import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import speech_recognition as sr
from modules import engine_loop, engine_voice, voice


class _FakeStream:
    """One loud frame then silence: a short utterance that the recorder ends itself."""

    SILENCE = b"\x00\x00" * 512          # 1024 bytes of int16 zeros
    LOUD = b"\x00\x10" * 512             # every sample 4096: above any noise threshold

    def __init__(self, opened, closed):
        self._frames = [self.SILENCE] * 3 + [self.LOUD] + [self.SILENCE] * 20
        self._opened, self._closed = opened, closed

    def __enter__(self):
        self._opened.append(True)
        return self

    def __exit__(self, *exc):
        self._closed.append(True)

    def read(self, n):
        return (self._frames.pop(0) if self._frames else self.SILENCE, None)


class CaptureAndRecognizeAreSeparateSteps(unittest.TestCase):
    def _recording(self, opened, closed):
        """A microphone that yields one loud frame and then silence; never the real one."""
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(voice, "_input_device", return_value=None))
        stack.enter_context(patch.object(voice.sd, "RawInputStream",
                                         lambda **kw: _FakeStream(opened, closed)))
        return stack

    def test_capture_closes_the_device_and_returns_only_bytes(self):
        opened, closed = [], []
        with self._recording(opened, closed), patch.object(voice, "recognize") as recognize:
            raw = voice.capture(timeout=5)
        self.assertEqual(opened, [True])
        self.assertEqual(closed, [True], "the stream stays open when capture returns")
        self.assertTrue(raw)
        recognize.assert_not_called()

    def test_listen_is_capture_then_recognize_of_exactly_that_recording(self):
        opened, closed = [], []
        with self._recording(opened, closed), patch.object(voice, "recognize"):
            recorded = voice.capture(timeout=5)
        with self._recording(opened, closed), \
                patch.object(voice, "recognize", return_value="not al") as recognize:
            self.assertEqual(voice.listen(timeout=5, announce_fail=True, cheap=True), "not al")
        self.assertEqual(recognize.call_args.args[0], recorded)
        self.assertEqual(recognize.call_args.kwargs["cheap"], True)

    def test_an_aborted_wait_produces_no_text_and_no_provider_call(self):
        opened, closed = [], []
        abort = threading.Event()
        abort.set()
        with self._recording(opened, closed), patch.object(voice, "recognize") as recognize:
            self.assertIsNone(voice.listen(timeout=5, abort=abort))
        recognize.assert_not_called()


class BoundedProviderWait(unittest.TestCase):
    def test_the_google_request_carries_a_timeout_instead_of_waiting_forever(self):
        bound = voice._rec.operation_timeout
        self.assertIsInstance(bound, (int, float))
        self.assertTrue(0 < bound <= 15, f"an endless wait holds the engine loop: {bound}")

    def test_a_timed_out_google_request_is_reported_as_no_text(self):
        with patch.object(voice, "_engine", return_value="google"), \
                patch.object(voice._rec, "recognize_google",
                             side_effect=sr.RequestError("recognition connection failed")):
            self.assertIsNone(voice.recognize(b"\x00\x00" * 1600))


class CaptureLockScope(unittest.TestCase):
    """The engine loop keeps `audio_lock` over the recording and drops it before the text."""

    def context(self):
        import tempfile
        from pathlib import Path
        from modules import engine_runtime
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root_logger = engine_runtime.logging.getLogger()
        previous = set(root_logger.handlers)
        with patch.object(engine_runtime, "DATA_DIR", Path(temp.name)):
            context = engine_runtime.EngineContext()

        def close_handlers():
            for handler in list(root_logger.handlers):
                if handler not in previous:
                    root_logger.removeHandler(handler)
                    handler.close()
        self.addCleanup(close_handlers)
        self.addCleanup(context._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        return context

    def test_the_stt_wait_runs_with_the_capture_device_free(self):
        context = self.context()
        lock = threading.Lock()
        context.audio_lock = lock
        seen = {}

        def recording(**kwargs):
            seen["capturing"] = lock.locked()     # the loop holds the device while it records
            return b"\x00\x00" * 3200

        def waiting(raw, **kwargs):
            got = lock.acquire(timeout=2)         # a lock the loop never dropped stays False
            seen["free_for_stt"] = got
            if got:
                lock.release()
            seen["bytes"] = raw
            context.stop_event.set()
            return None

        context.voice = SimpleNamespace(HINTS=[], capture=recording, recognize=waiting)
        context.emit, context._start_hang_watch = Mock(), Mock()
        context.list_users = lambda: [context.profile.name]
        context.threading = SimpleNamespace(Thread=Mock(), Timer=Mock())
        context.events.put(("listen",))
        session = SimpleNamespace(manual_local_stt=False, listening_enabled=False,
                                  speak_enabled=False, state={})
        with patch("modules.engine_voice.VoiceSession", return_value=session), \
                patch("instance.take_over", return_value=False), \
                patch("updater.pop_notice", return_value=None), \
                patch("modules.perf.start"), patch("release_guard.ready"):
            engine_loop.main(context, ui=Mock())
        self.assertEqual(seen["capturing"], True)
        self.assertEqual(seen["free_for_stt"], True)
        self.assertEqual(seen["bytes"], b"\x00\x00" * 3200)
        self.assertFalse(context.pause_listening.is_set())
        self.assertFalse(lock.locked(), "the recognition wait left the microphone claimed")

    def test_no_engine_path_uses_the_combined_listen_anymore(self):
        """Every engine caller of the microphone takes the two steps separately.

        `voice.listen` stays correct for a caller that owns neither device nor loop,
        but a path that wraps it in `runtime.audio_lock` re-creates the old wait.
        """
        import inspect
        for module in (engine_loop, engine_voice):
            source = inspect.getsource(module)
            self.assertNotIn("voice.listen(", source, module.__name__)
            self.assertIn("voice.capture(", source, module.__name__)


if __name__ == "__main__":
    unittest.main()
