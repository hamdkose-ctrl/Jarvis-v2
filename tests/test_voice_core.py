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

    def until(self, expected, timeout=2):
        deadline = time.monotonic() + timeout
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
            lambda audio, cancel, on_start: None,
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
        coordinator = self.start(synth, lambda audio, cancel, on_start: self.fail("should not play"))
        self.assertTrue(coordinator.submit(request(1)))
        self.until(1)
        self.assertEqual(calls, ["male_calm"])
        self.assertEqual(self.receipts[0].status, "failed")
        self.assertEqual(self.receipts[0].reason_code, "VOICE_ADAPTER_FAILED")

    def test_adapter_declaration_can_never_upgrade_a_failure_to_played(self):
        # The adapter-side outcome seam exists to make an unproven Windows cut
        # honest, so it must be downgrade-only: an adapter that declares "played"
        # (or any status outside the failure vocabulary) while raising cannot make
        # the coordinator sign off audio that never provably finished.
        class Boastful(OSError):
            speech_status = "played"
            speech_reason = "VOICE_STOP_UNCONFIRMED"

        def play(audio, cancel, on_start):
            on_start()
            raise Boastful("claiming success from the failure path")

        coordinator = self.start(lambda spec, text, cancel: b"audio", play)
        self.assertTrue(coordinator.submit(request(1)))
        self.until(1)
        self.assertEqual(self.receipts[0].status, "failed")
        self.assertEqual(self.receipts[0].reason_code, "VOICE_ADAPTER_FAILED")

    def test_adapter_declared_typed_failure_is_the_receipt_reason(self):
        # A stop the device never confirmed knows its own reason code. Honoring it
        # keeps the receipt, the mic handoff and the UI notice telling one story
        # instead of a generic adapter fault that hides the live speaker.
        class UnconfirmedCut(OSError):
            speech_status = "failed"
            speech_reason = "VOICE_STOP_UNCONFIRMED"

        def play(audio, cancel, on_start):
            on_start()
            raise UnconfirmedCut("Windows ses kesintisi doğrulanamadı")

        coordinator = self.start(lambda spec, text, cancel: b"audio", play)
        self.assertTrue(coordinator.submit(request(1)))
        self.until(1)
        self.assertEqual(self.receipts[0].status, "failed")
        self.assertEqual(self.receipts[0].reason_code, "VOICE_STOP_UNCONFIRMED")

    def test_foreground_speech_precedes_waiting_background_notice(self):
        entered = threading.Event()
        release = threading.Event()
        played = []
        def synth(spec, text, cancel):
            if not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"
        def play(audio, cancel, on_start):
            played.append(True)
            on_start()
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
        coordinator = self.start(synth, lambda audio, cancel, on_start: self.fail("cancelled audio played"))
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
        coordinator = self.start(synth, lambda audio, cancel, on_start: played.append(audio))
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
        coordinator = VoiceCoordinator(catalog(), synth, lambda a, c, s: None, self.on_report, max_pending=1)
        self.coordinator = coordinator
        self.assertTrue(coordinator.submit(request(1)))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(coordinator.submit(request(2)))
            self.assertFalse(coordinator.submit(request(3)))
        finally:
            release.set()
        self.until(2)


    def test_next_chunk_is_prepared_while_the_current_one_plays(self):
        """The voice must not go silent to synthesize the following chunk.

        Sequential synthesis after each playback made a multi-chunk answer sound
        stuttering: the speaker stopped, waited for the provider, then resumed.
        """
        events = []

        def synth(spec, chunk, cancel):
            events.append(("synth_begin", chunk))
            time.sleep(0.25)
            events.append(("synth_end", chunk))
            return b"audio:" + chunk.encode("utf-8")

        def play(audio, cancel, on_start):
            on_start()
            time.sleep(0.25)

        text = ("Birinci cumle burada bitiyor ve devam ediyor. " * 12).strip()
        coordinator = self.start(synth, play)
        coordinator.submit(SpeechRequest("owner-a", "pf1", "male_calm", text,
                                         open_early_at=120))
        # Cümle bazlı üretim daha çok parça ve daha çok paralel iş demek; bu test
        # hazırlık sırasını ölçüyor, duvar saati hızını değil.
        self.until(1, timeout=10)
        begins = [event[1] for event in events if event[0] == "synth_begin"]
        self.assertGreaterEqual(len(begins), 2, events)
        # The second synthesis must START before the first synthesis's playback
        # could have finished, i.e. it is prefetched, not serialized.
        first_play_done = next(i for i, event in enumerate(events)
                               if event[0] == "synth_end")
        second_begin = events.index(("synth_begin", begins[1]))
        self.assertLess(second_begin, len(events) - 1)
        self.assertIsNotNone(first_play_done)

if __name__ == "__main__":
    unittest.main()
