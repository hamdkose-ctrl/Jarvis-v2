"""Speech output envelope contract: identity, stages, TTL, validity and backpressure.

Every adapter, clock and audio device here is fake. These tests establish the
typed contract only; they are not evidence of audible Windows output or AEC.
"""
import threading
import time
import unittest

from modules.voice_core import (
    SPEECH_REQUEST_SCHEMA,
    SpeechReceipt,
    SpeechRequest,
    VoiceCatalog,
    VoiceCoordinator,
    VoiceSpec,
)


def catalog():
    return VoiceCatalog((
        VoiceSpec("tr_erkek", "Erkek", "piper", "male-tr.onnx"),
        VoiceSpec("tr_kadin", "Kadın", "piper", "female-tr.onnx"),
    ))


def request(ident="r1", **kwargs):
    base = {"owner": "alice", "request_id": ident, "voice_id": "tr_erkek", "text": "Merhaba"}
    base.update(kwargs)
    return SpeechRequest(**base)


class SpeechEnvelopeTests(unittest.TestCase):
    def test_context_fields_are_carried_without_a_caller_priority(self):
        req = request(turn_id="t1", event_id="e1", goal_id="g1", state_version=7,
                      artifact_id="a1", approval_id="p1", kind="reminder",
                      lane="background", ttl_seconds=30.0)
        self.assertEqual(req.schema, SPEECH_REQUEST_SCHEMA)
        self.assertEqual((req.turn_id, req.event_id, req.goal_id), ("t1", "e1", "g1"))
        self.assertEqual((req.state_version, req.artifact_id, req.approval_id), (7, "a1", "p1"))
        self.assertEqual(req.kind, "reminder")
        self.assertEqual(req.ttl_seconds, 30.0)
        # Priority is derived from the lane, never a model-supplied urgency value.
        self.assertFalse(hasattr(req, "priority"))

    def test_unknown_schema_kind_and_identity_fields_fail_closed(self):
        for kwargs in ({"schema": "speech.request.v99"}, {"kind": "emergency"},
                       {"kind": ""}, {"state_version": -1}, {"state_version": True},
                       {"ttl_seconds": -1}, {"ttl_seconds": 99999},
                       {"goal_id": "x" * 200}, {"turn_id": None}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    request(**kwargs)

    def test_receipt_keeps_the_utterance_identity_for_ui_correlation(self):
        receipt = SpeechReceipt("r1", "alice", "tr_erkek", "played", "VOICE_PLAYBACK_RETURNED",
                                turn_id="t1", event_id="e1", goal_id="g1", kind="reply")
        self.assertEqual((receipt.turn_id, receipt.event_id, receipt.goal_id), ("t1", "e1", "g1"))
        self.assertEqual(receipt.kind, "reply")


class CoordinatorOutputTests(unittest.TestCase):
    def setUp(self):
        self.receipts = []
        self.stages = []
        self.signal = threading.Event()
        self.coordinator = None
        self.now = 1000.0

    def tearDown(self):
        if self.coordinator is not None:
            self.coordinator.close()

    def report(self, receipt):
        self.receipts.append(receipt)
        self.signal.set()

    def stage(self, req, name):
        self.stages.append((req.request_id, name))

    def clock(self):
        return self.now

    def start(self, synth=None, play=None, **kwargs):
        synth = synth or (lambda spec, text, cancel: b"audio")
        play = play or (lambda audio, cancel, on_start: on_start())
        self.coordinator = VoiceCoordinator(
            catalog(), synth, play, self.report,
            stages=self.stage, clock=self.clock, **kwargs,
        )
        return self.coordinator

    def until(self, count):
        # CI koşucusu başka işlerle paylaşılırken 2 sn yetmiyordu (canlı: 24 Kasım
        # koşuları, "0 not greater than or equal to 1 : []" dalgalı hatası). Emniyet
        # payı 10 sn; bekleme bitince aynı iddia kontrol edilir, yani test zayıflamaz.
        deadline = time.monotonic() + 10
        while len(self.receipts) < count and time.monotonic() < deadline:
            self.signal.wait(0.02)
            self.signal.clear()
        self.assertGreaterEqual(len(self.receipts), count, self.receipts)

    def wait_stage(self, name):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if any(stage == name for _, stage in self.stages):
                return
            time.sleep(0.01)
        self.fail(f"stage {name} not reached: {self.stages}")

    def test_playback_started_comes_from_the_player_not_from_enqueue_or_wav(self):
        release = threading.Event()
        entered = threading.Event()

        def play(audio, cancel, on_start):
            entered.set()
            self.assertTrue(release.wait(2))
            on_start()

        self.start(play=play)
        self.assertTrue(self.coordinator.submit(request()))
        self.assertTrue(entered.wait(1))
        # WAV bytes exist and enqueue succeeded, but the player has not started.
        self.assertIn(("r1", "audio_ready"), self.stages)
        self.assertNotIn(("r1", "playback_started"), self.stages)
        release.set()
        self.until(1)
        self.assertEqual([name for _, name in self.stages],
                         ["accepted", "synthesizing", "audio_ready", "playback_started"])
        self.assertEqual(self.receipts[0].status, "played")

    def test_one_utterance_reports_start_once_across_chunks(self):
        starts = []

        def play(audio, cancel, on_start):
            starts.append(1)
            on_start()

        self.start(play=play)
        self.assertTrue(self.coordinator.submit(request(text="cümle bir. " * 200)))
        self.until(1)
        self.assertGreater(len(starts), 1)
        self.assertEqual([name for _, name in self.stages].count("playback_started"), 1)
        self.assertEqual(self.receipts[0].status, "played")

    def test_ttl_drops_queued_audio_without_a_second_voice_or_core_cancel(self):
        release = threading.Event()
        entered = threading.Event()
        goal_running = threading.Event()
        goal_running.set()

        def synth(spec, text, cancel):
            if not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"

        self.start(synth=synth)
        self.assertTrue(self.coordinator.submit(request("active")))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(self.coordinator.submit(request("stale", ttl_seconds=5.0)))
            self.now += 10.0
        finally:
            release.set()
        self.until(2)
        by_id = {r.request_id: r for r in self.receipts}
        self.assertEqual(by_id["active"].status, "played")
        self.assertEqual((by_id["stale"].status, by_id["stale"].reason_code),
                         ("cancelled", "VOICE_TTL_EXPIRED"))
        self.assertTrue(goal_running.is_set())
        self.assertNotIn(("stale", "playback_started"), self.stages)

    def test_validity_is_checked_at_enqueue_and_again_before_playback(self):
        release = threading.Event()
        entered = threading.Event()
        state = {"valid": True}
        played = []

        def synth(spec, text, cancel):
            if not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"

        def play(audio, cancel, on_start):
            played.append(audio)
            on_start()

        self.start(synth=synth, play=play,
                   validate=lambda req: "" if state["valid"] else "VOICE_INVALIDATED")
        self.assertTrue(self.coordinator.submit(request("active")))
        self.assertTrue(entered.wait(1))
        state["valid"] = False
        self.assertFalse(self.coordinator.submit(request("blocked-at-entrance")))
        try:
            release.set()
            self.until(2)
        finally:
            release.set()
        by_id = {r.request_id: r for r in self.receipts}
        self.assertEqual((by_id["blocked-at-entrance"].status,
                          by_id["blocked-at-entrance"].reason_code),
                         ("rejected", "VOICE_INVALIDATED"))
        self.assertEqual(by_id["active"].status, "cancelled")
        self.assertEqual(played, [])

    def test_broken_validator_fails_closed_instead_of_playing(self):
        def validate(req):
            raise OSError("canonical state unreadable")

        self.start(validate=validate)
        self.assertFalse(self.coordinator.submit(request()))
        self.assertEqual((self.receipts[0].status, self.receipts[0].reason_code),
                         ("rejected", "VOICE_VALIDITY_UNKNOWN"))

    def test_invalidation_targets_identity_and_keeps_unrelated_queued_order(self):
        release = threading.Event()
        entered = threading.Event()

        def synth(spec, text, cancel):
            if not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"

        self.start(synth=synth)
        self.assertTrue(self.coordinator.submit(request("active", goal_id="g1")))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(self.coordinator.submit(request("other", goal_id="g2")))
            self.assertTrue(self.coordinator.submit(request("stale", goal_id="g1", turn_id="t1")))
            self.assertEqual(self.coordinator.invalidate(goal_id="g1"), 2)
        finally:
            release.set()
        self.until(3)
        by_id = {r.request_id: r for r in self.receipts}
        self.assertEqual((by_id["stale"].status, by_id["stale"].reason_code),
                         ("cancelled", "VOICE_INVALIDATED"))
        self.assertEqual(by_id["active"].status, "cancelled")
        self.assertEqual(by_id["other"].status, "played")

    def test_invalidation_without_an_identity_cannot_blindly_clear_the_queue(self):
        self.start()
        with self.assertRaises(ValueError):
            self.coordinator.invalidate()
        with self.assertRaises(ValueError):
            self.coordinator.invalidate(goal_id="  ")
        self.assertTrue(self.coordinator.submit(request(goal_id="g1", state_version=3)))
        self.until(1)
        # Only a matching result identity invalidates audio; a state_version bump
        # or an unrelated goal id is not an audio clearing authority.
        self.assertEqual(self.coordinator.invalidate(goal_id="g9"), 0)
        self.assertEqual(self.receipts[0].status, "played")

    def test_full_queue_produces_a_typed_backpressure_receipt(self):
        release = threading.Event()
        entered = threading.Event()

        def synth(spec, text, cancel):
            entered.set()
            self.assertTrue(release.wait(2))
            return b"audio"

        coordinator = VoiceCoordinator(catalog(), synth, lambda a, c, s: s(), self.report,
                                       max_pending=1, clock=self.clock)
        self.coordinator = coordinator
        self.assertTrue(coordinator.submit(request("one")))
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(coordinator.submit(request("two")))
            self.assertFalse(coordinator.submit(request("three", goal_id="g1", turn_id="t1")))
            rejected = [r for r in self.receipts if r.request_id == "three"]
            self.assertEqual(len(rejected), 1)
            self.assertEqual((rejected[0].status, rejected[0].reason_code),
                             ("rejected", "VOICE_QUEUE_FULL"))
            self.assertEqual((rejected[0].owner, rejected[0].goal_id, rejected[0].turn_id),
                             ("alice", "g1", "t1"))
        finally:
            release.set()
        self.until(3)

    def test_submit_after_close_is_a_typed_rejection_not_a_silent_drop(self):
        coordinator = self.start()
        coordinator.close()
        self.coordinator = None
        self.assertFalse(coordinator.submit(request()))
        self.assertEqual((self.receipts[0].status, self.receipts[0].reason_code),
                         ("rejected", "VOICE_CLOSED"))

    def test_unavailable_identity_is_rejected_without_switching_voice(self):
        calls = []
        self.start(synth=lambda spec, text, cancel: calls.append(spec.voice_id) or b"audio")
        with self.assertRaises(ValueError):
            self.coordinator.submit(request(voice_id="yok"))
        self.assertEqual(calls, [])
        self.assertEqual(self.receipts, [])

    def block_one(self, *, max_pending=3):
        """Occupy the single worker so later submissions are provably WAITING."""
        self.release = threading.Event()
        entered = threading.Event()
        self.heard = []

        def synth(spec, text, cancel):
            self.heard.append(text)
            if not entered.is_set():
                entered.set()
            self.assertTrue(self.release.wait(2))
            return b"audio"

        coordinator = VoiceCoordinator(catalog(), synth, lambda a, c, s: s(), self.report,
                                       max_pending=max_pending, clock=self.clock)
        self.coordinator = coordinator
        self.assertTrue(coordinator.submit(request("active", text="ilk yanit")))
        self.assertTrue(entered.wait(1))
        return coordinator

    def test_full_notice_queue_never_costs_the_user_their_answer(self):
        # §4-C: background notifications used to hold every slot, so the current
        # user speech got VOICE_QUEUE_FULL and the preemption never happened.
        # The bounded queue is kept; the STALEST waiting notice is coalesced away
        # instead, and it is the only thing dropped.
        coordinator = self.block_one(max_pending=3)
        for name in ("n1", "n2", "n3"):
            self.assertTrue(coordinator.submit(request(
                name, text="bildirim-" + name, lane="background", kind="progress",
                goal_id="g1", turn_id=name)))
        self.assertTrue(coordinator.submit(request("ask", text="su anki soru",
                                                   goal_id="g2", turn_id="t2")))
        try:
            evicted = [r for r in self.receipts if r.request_id == "n1"]
            self.assertEqual([(r.status, r.reason_code) for r in evicted],
                             [("cancelled", "VOICE_NOTICE_EVICTED")])
            # The receipt carries the result identity so Core can still show the
            # written result; the goal itself is untouched and the newer notices
            # keep their place.
            self.assertEqual((evicted[0].goal_id, evicted[0].turn_id, evicted[0].kind),
                             ("g1", "n1", "progress"))
        finally:
            self.release.set()
        self.until(5)
        by_id = {r.request_id: r for r in self.receipts}
        self.assertEqual(sorted(by_id), ["active", "ask", "n1", "n2", "n3"])
        self.assertEqual(by_id["n2"].status, "played")   # newest notices survive
        self.assertEqual(by_id["n3"].status, "played")
        self.assertEqual(by_id["ask"].status, "played")
        self.assertNotIn("bildirim-n1", self.heard)      # evicted never reached the adapter

    def test_backpressure_stays_honest_when_no_notice_can_be_coalesced(self):
        # An answer is user speech too: it is never displaced to make room, so a
        # queue of foreground replies keeps the typed VOICE_QUEUE_FULL receipt.
        coordinator = self.block_one(max_pending=1)
        self.assertTrue(coordinator.submit(request("a1", text="birinci yanit")))
        self.assertFalse(coordinator.submit(request("a2", text="ikinci yanit")))
        self.assertFalse(coordinator.submit(request("a3", text="onluk bildirim",
                                                    lane="background")))
        reasons = {(r.request_id, r.status, r.reason_code) for r in self.receipts}
        self.assertEqual(reasons, {("a2", "rejected", "VOICE_QUEUE_FULL"),
                                   ("a3", "rejected", "VOICE_QUEUE_FULL")})
        self.release.set()
        self.until(4)
        by_id = {r.request_id: r.status for r in self.receipts}
        self.assertEqual(by_id["a1"], "played")
        self.assertEqual(by_id["active"], "played")

    def test_one_result_identity_is_announced_once_however_often_core_offers_it(self):
        # §7: the same reminder/event result must not reach the speaker twice.
        # The claim is on the result identity, not on the request id, so a second
        # enqueue of the same announcement is a typed refusal instead of audio.
        heard = []
        coordinator = self.start(synth=lambda spec, text, cancel: heard.append(text) or b"audio")
        self.assertTrue(coordinator.submit(request("n1", text="Toplantın 14:00", kind="reminder",
                                                    lane="background", event_id="reminder:7")))
        self.until(1)
        self.assertFalse(coordinator.submit(request("n2", text="Toplantın 14:00", kind="reminder",
                                                     lane="background", event_id="reminder:7")))
        self.assertEqual([(r.request_id, r.status, r.reason_code) for r in self.receipts if r.request_id == "n2"],
                         [("n2", "rejected", "VOICE_DUPLICATE_DELIVERY")])
        self.assertEqual(heard, ["Toplantın 14:00"])

    def test_duplicate_protection_never_swallows_an_ordinary_reply_or_a_new_occurrence(self):
        # Two turns can legitimately answer with the same sentence, and the same
        # reminder record at a new time is a new result: neither may be silenced
        # by an over-wide identity match.
        heard = []
        coordinator = self.start(synth=lambda spec, text, cancel: heard.append(text) or b"audio")
        self.assertTrue(coordinator.submit(request("p1", text="Evet")))
        self.until(1)
        self.assertTrue(coordinator.submit(request("p2", text="Evet")))
        self.assertTrue(coordinator.submit(request("t1", text="Evet", turn_id="t1")))
        self.assertTrue(coordinator.submit(request("t2", text="Evet", turn_id="t2")))
        self.assertTrue(coordinator.submit(request("r1", text="Su iç", kind="reminder",
                                                    event_id="reminder:7")))
        self.assertTrue(coordinator.submit(request("r2", text="Su iç", kind="reminder",
                                                    event_id="reminder:8")))
        self.until(6)
        self.assertEqual(len(heard), 6)

    def test_a_result_that_never_started_keeps_its_next_chance_to_be_heard(self):
        # Releasing a slot for the user's answer must not also blacklist the
        # notice it displaced: an utterance that never reached the player is not
        # a delivery, so Core can offer that same result again.
        coordinator = self.block_one(max_pending=3)
        notice = request("n1", text="Rapor hazır", kind="notice", lane="background",
                         event_id="goal:9", goal_id="g9")
        self.assertTrue(coordinator.submit(request("n0", text="önceki bildirim", lane="background")))
        self.assertTrue(coordinator.submit(notice))
        coordinator.interrupt_speech()          # the waiting notice is cancelled, unplayed
        self.release.set()
        self.until(3)                           # both unplayed notices + the active answer
        self.assertTrue(coordinator.submit(request("n2", text="Rapor hazır", kind="notice",
                                                    lane="background", event_id="goal:9",
                                                    goal_id="g9")))
        self.until(4)
        self.assertIn("Rapor hazır", self.heard)

    def test_validity_authority_rejects_a_stale_turn_before_any_synthesis(self):
        # §6 lives in Core, not here: Voice never invents a cancel decision.
        # The coordinator only honors its validity authority, so a turn the
        # authority declares stopped cannot reach the adapter, while the next
        # turn and a turn-less notice are still spoken.
        heard = []
        seen = []

        def validity(request):
            seen.append(request.turn_id)
            return "VOICE_SUSPENDED_TURN" if request.turn_id == "t1" else ""

        coordinator = self.start(synth=lambda spec, text, cancel: heard.append(text) or b"audio",
                                 validate=validity)
        self.assertFalse(coordinator.submit(request("tail", turn_id="t1", text="modelden geç geldi")))
        refused = [r for r in self.receipts if r.request_id == "tail"][0]
        self.assertEqual((refused.status, refused.reason_code),
                         ("rejected", "VOICE_SUSPENDED_TURN"))
        self.assertEqual((refused.turn_id, refused.kind), ("t1", "reply"))
        self.assertNotIn("modelden geç geldi", heard)          # never synthesized
        self.assertTrue(coordinator.submit(request("next", turn_id="t2", text="yeni soru")))
        self.assertTrue(coordinator.submit(request("note", text="turnsuz bildirim")))
        self.until(3)
        self.assertIn("yeni soru", heard)
        self.assertIn("turnsuz bildirim", heard)
        self.assertEqual(seen[:3], ["t1", "t2", ""], "authority decides per request, never blanket")

    def test_concurrent_submitters_leave_no_request_unaccounted(self):
        # several Core threads submitting at once, every request id gets exactly
        # one terminal receipt and the queue never exceeds its bound.
        slow = threading.Event()

        def synth(spec, text, cancel):
            slow.wait(0.005)
            return b"audio"

        coordinator = self.start(synth=synth, max_pending=2)
        total, workers = 4, 6
        ids = [f"u{worker}-{i}" for worker in range(workers) for i in range(total)]

        def push(worker):
            for i in range(total):
                ident = f"u{worker}-{i}"
                coordinator.submit(request(
                    ident, lane="background" if i % 2 else "foreground",
                    goal_id="g1" if i % 2 else "", turn_id=ident))

        threads = [threading.Thread(target=push, args=(w,)) for w in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        self.assertTrue(self._wait_for(lambda: len(self.receipts) == len(ids), 5), self.receipts)
        self.assertEqual(sorted(r.request_id for r in self.receipts), sorted(ids))
        self.assertLessEqual(coordinator._pending.qsize(), 2)

    def _wait_for(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False


if __name__ == "__main__":
    unittest.main()