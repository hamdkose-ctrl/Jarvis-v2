"""VOICE-01 deterministic queue tests; no sound card, network, LLM or Ollama."""
import threading
import time
import unittest

from modules.voice_core import SpeechRequest, VoiceCatalog, VoiceCoordinator, VoiceSpec


def catalog():
    return VoiceCatalog((
        VoiceSpec("male_calm", "Erkek sakin", "piper", "male-tr.onnx"),
        VoiceSpec("female_calm", "Kadın sakin", "piper", "female-tr.onnx"),
    ))


def request(number, voice="male_calm", lane="foreground"):
    return SpeechRequest("owner-a", str(number), voice, "Merhaba", lane)


class VoiceCoreTests(unittest.TestCase):
    def setUp(self):
        self.receipts = []
        self.output_event = threading.Event()
        self.coordinator = None

    def tearDown(self):
        if self.coordinator:
            self.coordinator.close()

    def on_report(self, receipt):
        self.receipts.append(receipt)
        self.output_event.set()

    def until(self, expected):
        deadline = time.monotonic() + 2
        while len(self.receipts) < expected and time.monotonic() < deadline:
            self.output_event.wait(0.03)
            self.output_event.clear()
        self.assertGreaterEqual(len(self.receipts), expected, self.receipts)

    def start(self, synth, play):
        self.coordinator = VoiceCoordinator(catalog(), synth, play, self.on_report)
        return self.coordinator

    def test_multiple_selectable_voices_with_no_implicit_switch(self):
        calls = []
        coordinator = self.start(
            lambda spec, text, cancel: (calls.append(spec.voice_id) or b"audio"),
            lambda audio, cancel: None,
        )
        self.assertTrue(coordinator.submit(request(1, "female_calm")))
        self.until(1)
        self.assertEqual(calls, ["female_calm"])
        self.assertEqual(self.receipts[0].voice_id, "female_calm")
        self.assertEqual(self.receipts[0].status, "played")
        with self.assertRaises(ValueError):
            coordinator.submit(request(2, "uninstalled_voice"))
        self.assertEqual(calls, ["female_calm"])

    def test_failed_voice_does_not_fallback_to_other_voice(self):
        calls = []
        def synth(spec, text, cancel):
            calls.append(spec.voice_id)
            raise OSError("offline engine unavailable")
        coordinator = self.start(synth, lambda audio, cancel: self.fail("should not play"))
        self.assertTrue(coordinator.submit(request(1)))
        self.until(1)
        self.assertEqual(calls, ["male_calm"])
        self.assertEqual(self.receipts[0].status, "failed")
        self.assertEqual(self.receipts[0].reason_code, "VOICE_ADAPTER_FAILED")

    def test_foreground_speech_precedes_waiting_background_notice(self):
        entered = threading.Event()
        release = threading.Event()
        played = []
        def synth(spec, text, cancel):
            if not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"
        def play(audio, cancel):
            played.append(True)
        coordinator = self.start(synth, play)
        self.assertTrue(coordinator.submit(request(1)))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(coordinator.submit(request(2, lane="background")))
            self.assertTrue(coordinator.submit(request(3, lane="foreground")))
        finally:
            release.set()
        self.until(3)
        self.assertEqual([r.request_id for r in self.receipts], ["1", "3", "2"])
        self.assertEqual(len(played), 3)

    def test_interrupt_cancels_speech_without_touching_background_work(self):
        entered = threading.Event()
        release = threading.Event()
        unrelated_goal_running = threading.Event()
        unrelated_goal_running.set()
        def synth(spec, text, cancel):
            entered.set()
            self.assertTrue(release.wait(2))
            return b"audio"
        coordinator = self.start(synth, lambda audio, cancel: self.fail("cancelled audio played"))
        self.assertTrue(coordinator.submit(request(1)))
        self.assertTrue(entered.wait(1))
        try:
            coordinator.interrupt_speech()
            self.assertTrue(unrelated_goal_running.is_set())
        finally:
            release.set()
        self.until(1)
        self.assertEqual(self.receipts[0].status, "cancelled")

    def test_foreground_preempts_active_background_audio_not_goal(self):
        entered = threading.Event()
        released = threading.Event()
        goal_running = threading.Event()
        goal_running.set()
        played = []
        def synth(spec, text, cancel):
            if not entered.is_set():
                entered.set()
                self.assertTrue(released.wait(2))
            return b"audio"
        coordinator = self.start(synth, lambda audio, cancel: played.append(audio))
        self.assertTrue(coordinator.submit(request(1, lane="background")))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(coordinator.submit(request(2, lane="foreground")))
            self.assertTrue(goal_running.is_set())
        finally:
            released.set()
        self.until(2)
        self.assertEqual([(r.request_id, r.status) for r in self.receipts],
                         [("1", "cancelled"), ("2", "played")])
        self.assertEqual(played, [b"audio"])

    def test_invalid_contract_and_duplicate_catalog_fail_closed(self):
        with self.assertRaises(ValueError):
            SpeechRequest("owner", "r", "male_calm", "", "foreground")
        with self.assertRaises(ValueError):
            SpeechRequest("owner", "r", "male_calm", "text", "emergency")
        with self.assertRaises(ValueError):
            VoiceCatalog((VoiceSpec("one", "a", "edge", "e"), VoiceSpec("one", "b", "sapi", "s")))
        with self.assertRaises(ValueError):
            VoiceSpec("one", "a", "ollama", "model")

    def test_queue_is_bounded_without_blocking_caller(self):
        entered = threading.Event()
        release = threading.Event()
        def synth(spec, text, cancel):
            entered.set()
            self.assertTrue(release.wait(2))
            return b"a"
        coordinator = VoiceCoordinator(catalog(), synth, lambda a, c: None, self.on_report, max_pending=1)
        self.coordinator = coordinator
        self.assertTrue(coordinator.submit(request(1)))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(coordinator.submit(request(2)))
            self.assertFalse(coordinator.submit(request(3)))
        finally:
            release.set()
        self.until(2)


if __name__ == "__main__":
    unittest.main()
