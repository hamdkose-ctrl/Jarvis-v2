"""VOICE-02C: long speech boundaries and cancellation, with fake audio only."""
import threading
import time
import unittest

from modules.voice_core import (
    SPEECH_CHUNK_CHARS, SpeechRequest, VoiceCatalog,
    VoiceCoordinator, VoiceSpec, split_speech_text,
)


def spec():
    return VoiceCatalog((
        VoiceSpec("tr_erkek", "Installed male test", "piper", "test-male.onnx"),
        VoiceSpec("tr_kadin", "Installed female test", "piper", "test-female.onnx"),
    ))


def request(ident, text, *, lane="foreground", voice="tr_kadin"):
    return SpeechRequest("alice", ident, voice, text, lane)


class ChunkedSpeechTests(unittest.TestCase):
    def setUp(self):
        self.receipts = []
        self.condition = threading.Condition()
        self.coordinator = None

    def tearDown(self):
        if self.coordinator is not None:
            self.coordinator.close()

    def notify(self, receipt):
        with self.condition:
            self.receipts.append(receipt)
            self.condition.notify_all()

    def start(self, synth, play, echo_note=None):
        self.coordinator = VoiceCoordinator(spec(), synth, play, self.notify,
                                            echo_note=echo_note)
        return self.coordinator

    def until(self, count):
        with self.condition:
            self.assertTrue(
                self.condition.wait_for(
                    lambda: len(self.receipts) >= count, timeout=4,
                ),
                self.receipts,
            )

    def test_sentence_first_chunks_preserve_every_character_and_utf8_text(self):
        text = ("İstanbul'da bugün hava güzel. " * 55) + (
            "Çalışırken kaynakları doğrula! "
        ) * 20
        parts = split_speech_text(text, max_chars=160)
        self.assertGreater(len(parts), 3)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(1 <= len(p) <= 160 for p in parts))
        self.assertTrue(any(p.rstrip().endswith(".") for p in parts))

    def test_unbroken_text_is_hard_capped_and_maximum_request_stays_bounded(self):
        parts = split_speech_text("ğ" * 12000)
        self.assertEqual(len(parts), 12000 // SPEECH_CHUNK_CHARS)
        self.assertEqual("".join(parts), "ğ" * 12000)
        self.assertTrue(all(len(p) == SPEECH_CHUNK_CHARS for p in parts))

    def test_bad_chunk_contract_rejected_without_playback(self):
        for bad in ("", "  ", "x" * 12001, None):
            with self.subTest(text=repr(bad)[:30]), self.assertRaises(ValueError):
                split_speech_text(bad)
        for limit in (31, 12001, True, 0):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                split_speech_text("Merhaba", max_chars=limit)

    def test_long_response_is_sequential_nonblocking_and_has_one_receipt(self):
        phrases = ("Merhaba, bu uzun bir yanıtın parçasıdır. " * 36).strip()
        starts, played = [], []
        def synth(voice, text, cancel):
            starts.append((voice.voice_id, text))
            return text.encode("utf-8")
        def play(audio, cancel, on_start):
            played.append(audio.decode("utf-8"))
            on_start()
        lane = self.start(synth, play)
        unrelated_goal = threading.Event()
        unrelated_goal.set()
        self.assertTrue(lane.submit(request("long", phrases)))
        self.assertTrue(unrelated_goal.is_set())
        self.until(1)
        self.assertGreater(len(starts), 1)
        self.assertEqual("".join(p[1] for p in starts), phrases)
        self.assertEqual([p[1] for p in starts], played)
        self.assertEqual({v for v, _ in starts}, {"tr_kadin"})
        self.assertEqual([(r.request_id, r.status) for r in self.receipts],
                         [("long", "played")])

    def test_every_audible_chunk_of_a_long_answer_reaches_the_echo_guard(self):
        phrases = ("Merhaba, bu uzun bir yanıtın parçasıdır. " * 36).strip()
        chunks = split_speech_text(phrases)
        self.assertGreater(len(chunks), 1)
        heard = []
        lane = self.start(lambda voice, text, cancel: text.encode("utf-8"),
                          lambda audio, cancel, on_start: on_start(),
                          echo_note=lambda req, text: heard.append(text))
        self.assertTrue(lane.submit(request("full", phrases)))
        self.until(1)
        self.assertEqual(heard, list(chunks))
        self.assertEqual("".join(heard), phrases)
        self.assertEqual(self.receipts[0].status, "played")

    def test_sus_registers_only_the_chunk_that_was_on_the_speaker(self):
        phrases = ("Merhaba, bu uzun bir yanıtın parçasıdır. " * 36).strip()
        chunks = split_speech_text(phrases)
        self.assertGreater(len(chunks), 1)
        heard = []
        started, released = threading.Event(), threading.Event()

        def play(audio, cancel, on_start):
            on_start()
            if not started.is_set():
                started.set()
                self.assertTrue(released.wait(3))

        lane = self.start(lambda voice, text, cancel: text.encode("utf-8"), play,
                          echo_note=lambda req, text: heard.append(text))
        try:
            self.assertTrue(lane.submit(request("cut", phrases)))
            self.assertTrue(started.wait(2))
            lane.interrupt_speech()
        finally:
            released.set()
        self.until(1)
        self.assertEqual(heard, [chunks[0]])
        self.assertEqual(self.receipts[0].status, "cancelled")

    def test_whitespace_only_chunks_do_not_trigger_piper(self):
        chunks = []
        def synth(voice, text, cancel):
            self.assertTrue(text.strip())
            chunks.append(text)
            return b"audio"
        lane = self.start(synth, lambda audio, cancel, on_start: on_start())
        text = (" " * 900) + "Merhaba, bu konuşma devam ediyor."
        self.assertTrue(lane.submit(request("spaces", text)))
        self.until(1)
        self.assertEqual("".join(x.strip() for x in chunks),
                         "Merhaba, bu konuşma devam ediyor.")
        self.assertEqual(self.receipts[0].status, "played")

    def test_sus_during_first_chunk_never_starts_next_chunk(self):
        entered = threading.Event()
        released = threading.Event()
        calls = []
        played = []
        def synth(voice, text, cancel):
            calls.append(text)
            entered.set()
            self.assertTrue(released.wait(3))
            return b"audio"
        lane = self.start(synth, lambda audio, cancel, on_start: (played.append(audio), on_start()))
        try:
            self.assertTrue(lane.submit(request("long", "Merhaba! " * 180)))
            self.assertTrue(entered.wait(1))
            goal = threading.Event()
            goal.set()
            lane.interrupt_speech()
            self.assertTrue(goal.is_set())  # speech-only stop, not a Core cancellation
        finally:
            released.set()
        self.until(1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(played, [])
        self.assertEqual(self.receipts[0].status, "cancelled")

    def test_interrupt_drains_all_pending_receipts_without_waiting_for_tts(self):
        entered = threading.Event()
        released = threading.Event()
        def synth(voice, text, cancel):
            entered.set()
            self.assertTrue(released.wait(3))
            return b"audio"
        lane = self.start(synth, lambda audio, cancel, on_start: on_start())
        try:
            self.assertTrue(lane.submit(request("active", "Merhaba")))
            self.assertTrue(entered.wait(1))
            self.assertTrue(lane.submit(request("queued-1", "İkinci")))
            self.assertTrue(lane.submit(request("queued-2", "Üçüncü")))
            lane.interrupt_speech()
            self.until(2)
            self.assertEqual(
                {x.request_id for x in self.receipts},
                {"queued-1", "queued-2"},
            )
            self.assertTrue(all(r.status == "cancelled" for r in self.receipts))
        finally:
            released.set()
        self.until(3)
        self.assertEqual({r.request_id for r in self.receipts},
                         {"active", "queued-1", "queued-2"})
        self.assertTrue(all(r.status == "cancelled" for r in self.receipts))

    def test_close_settles_waiting_receipts_and_does_not_block_caller(self):
        entered, released = threading.Event(), threading.Event()
        def synth(voice, text, cancel):
            entered.set()
            self.assertTrue(released.wait(3))
            return b"audio"
        lane = self.start(synth, lambda audio, cancel, on_start: on_start())
        try:
            self.assertTrue(lane.submit(request("active", "A")))
            self.assertTrue(entered.wait(1))
            self.assertTrue(lane.submit(request("queued", "B")))
            start = time.monotonic()
            lane.close()
            self.assertLess(time.monotonic() - start, 1)
            self.until(1)
            self.assertEqual(self.receipts[0].request_id, "queued")
            self.assertEqual(self.receipts[0].status, "cancelled")
            self.assertFalse(lane.submit(request("after-close", "C")))
            closed_receipt = self.receipts[-1]
            self.assertEqual((closed_receipt.request_id, closed_receipt.status,
                              closed_receipt.reason_code),
                             ("after-close", "rejected", "VOICE_CLOSED"))
        finally:
            released.set()
        self.until(3)
        self.assertEqual({x.request_id for x in self.receipts},
                         {"active", "queued", "after-close"})

    def test_mid_sentence_synthesis_failure_never_plays_later_chunks(self):
        calls, played = [], []
        def synth(voice, text, cancel):
            calls.append(text)
            return b"audio" if len(calls) == 1 else b""
        lane = self.start(synth, lambda audio, cancel, on_start: (played.append(audio), on_start()))
        self.assertTrue(lane.submit(request("failed", "Devam! " * 260)))
        self.until(1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(played, [b"audio"])
        self.assertEqual(self.receipts[0].status, "failed")
        self.assertEqual(self.receipts[0].reason_code, "VOICE_EMPTY_AUDIO")

    def test_foreground_preempts_long_background_without_switching_voice(self):
        started = threading.Event()
        released = threading.Event()
        calls = []
        played = []
        def synth(voice, text, cancel):
            calls.append((voice.voice_id, text))
            if not started.is_set():
                started.set()
                self.assertTrue(released.wait(3))
            return b"audio"
        lane = self.start(synth, lambda audio, cancel, on_start: (played.append(audio), on_start()))
        try:
            self.assertTrue(lane.submit(request("background", "Bildirim. " * 210,
                                                lane="background", voice="tr_erkek")))
            self.assertTrue(started.wait(1))
            self.assertTrue(lane.submit(request("foreground", "Merhaba.", voice="tr_kadin")))
        finally:
            released.set()
        self.until(2)
        self.assertEqual([(r.request_id, r.status) for r in self.receipts],
                         [("background", "cancelled"), ("foreground", "played")])
        self.assertEqual(len(calls), 2)
        self.assertEqual([voice for voice, _ in calls], ["tr_erkek", "tr_kadin"])
        self.assertEqual(played, [b"audio"])


if __name__ == "__main__":
    unittest.main()
