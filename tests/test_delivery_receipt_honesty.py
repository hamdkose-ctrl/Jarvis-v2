"""PR-5 delivery-receipt honesty and stale planning status.

Three verified seams are held here:
1. ``engine_background._emit_for`` returns False ONLY when the window callback
   really raised; a swallowed UI error must never look like a delivery.
2. ``event_channels.deliver`` records that False as ``failed:RuntimeError`` for
   the ui channel, and ``canonical_goal_flow._accepted_user_channel`` accepts
   only an owner-visible ``delivered`` receipt (never log-only).
3. ``canonical_planning_queue.status`` claims "model çalışıyor" only for an
   attempt this process actually dispatched (``_LIVE_ATTEMPTS``); a leftover
   planning_running record is reported honestly and never replayed.

No real window, phone, speaker, network or model call happens.
"""
from __future__ import annotations

from contextlib import ExitStack, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import threading

from modules import (
    canonical_planning_queue, canonical_goal_flow, engine_background,
    event_channels, execution_record, goal_executor, model_wait, requests_state,
    task_queue,
)
import release_guard


class _RecordingUi:
    def __init__(self, raises=False):
        self.calls = []
        self.raises = raises

    def __call__(self, kind, text, source):
        self.calls.append((kind, text, source))
        if self.raises:
            raise RuntimeError("pencere kapandı")


class _EmitRuntime:
    """Only the fields _emit_for touches, with the real event-log semantics."""

    def __init__(self, owner, ui):
        import threading as _th
        import datetime as _dt
        self._event_lock = _th.Lock()
        self._log_id = 0
        self.event_log = []
        self.history = SimpleNamespace(append=lambda slug, kind, text, source: None)
        self.response_waiters = None
        self.datetime = _dt
        self._ui = ui
        self.failures = []
        self._owner = owner

    def pc_profile(self):
        return self._owner

    def _record_failure(self, site):
        self.failures.append(site)


class EmitForReceiptTests(TestCase):
    def setUp(self):
        self.owner = SimpleNamespace(name="Hamdi", slug="ui-receipt-owner")
        self.other = SimpleNamespace(name="Ayse", slug="ui-receipt-other")

    def test_raising_window_callback_returns_false_and_records_failure(self):
        ui = _RecordingUi(raises=True)
        runtime = _EmitRuntime(self.owner, ui)
        ok = engine_background._emit_for(runtime, self.owner, "assistant", "mesaj")
        self.assertIs(ok, False)
        self.assertIn("main.py:_emit_for", runtime.failures)
        # The written notice is still durable even though the UI failed.
        self.assertEqual([e["text"] for e in runtime.event_log], ["mesaj"])

    def test_working_window_callback_returns_true(self):
        ui = _RecordingUi()
        runtime = _EmitRuntime(self.owner, ui)
        self.assertIs(engine_background._emit_for(runtime, self.owner, "assistant", "mesaj"), True)
        self.assertEqual(ui.calls, [("assistant", "mesaj", "")])
        self.assertEqual(runtime.failures, [])

    def test_metadata_capable_ui_gets_metadata_and_honest_receipt(self):
        calls = []

        def ui(kind, text, source, metadata=None):
            calls.append((kind, text, metadata))
            raise OSError("boru koptu")
        ui.event_metadata = True
        runtime = _EmitRuntime(self.owner, ui)
        self.assertIs(engine_background._emit_for(runtime, self.owner, "assistant", "x"), False)
        self.assertEqual(calls[0][0], "assistant")
        self.assertEqual(calls[0][2]["user"], "ui-receipt-owner")

    def test_no_ui_and_non_foreground_owner_stay_true(self):
        runtime = _EmitRuntime(self.owner, None)
        self.assertIs(engine_background._emit_for(runtime, self.owner, "assistant", "x"), True)
        runtime2 = _EmitRuntime(self.owner, _RecordingUi())
        self.assertIs(engine_background._emit_for(runtime2, self.other, "assistant", "x"), True)
        self.assertEqual(runtime2._ui.calls, [])


class _DeliverRuntime:
    def __init__(self, profile, emit_result):
        self.profile = profile
        self._emit_result = emit_result
        self.emit_calls = []
        self.events = SimpleNamespace(put=lambda item: None)
        self.log = SimpleNamespace(info=lambda *a: None)
        self.notify = SimpleNamespace(send=lambda *a: True)

    def list_users(self):
        return [self.profile.name]

    def _get_profile(self, name):
        return self.profile if name == self.profile.name else None

    def _emit_for(self, profile, kind, text, source=""):
        self.emit_calls.append(text)
        return self._emit_result


def _profile(prefs=None):
    return SimpleNamespace(name="fanout-owner", slug="fanout-owner",
                           data={"prefs": prefs if prefs is not None else {}})


_EVENT = {"source": "watcher", "kind": "file_rule", "payload": {"text": "kural çalıştı"}}


class DeliverReceiptTests(TestCase):
    def _deliver(self, emit_result, prefs=None, notify_ok=True):
        runtime = _DeliverRuntime(_profile(prefs), emit_result)
        runtime.notify.send = lambda *a: notify_ok
        with patch.object(event_channels, "announce_speech", return_value=False):
            return event_channels.deliver(runtime, "fanout-owner", dict(_EVENT))

    def test_ui_false_is_a_failed_channel_not_a_delivery(self):
        receipt = self._deliver(False)
        self.assertEqual(receipt["ui"], "failed:RuntimeError")
        self.assertEqual(receipt["log"], "delivered")

    def test_ui_true_and_legacy_none_stub_both_receipt_delivered(self):
        self.assertEqual(self._deliver(True)["ui"], "delivered")
        self.assertEqual(self._deliver(None)["ui"], "delivered")

    def test_every_owner_channel_failing_raises_instead_of_claiming_delivery(self):
        with patch.object(event_channels, "channels", return_value=["ui", "ntfy"]):
            with self.assertRaises(RuntimeError) as raised:
                self._deliver(False, prefs={"ntfy_topic": "t"}, notify_ok=False)
        self.assertIn("hiçbir kanala", str(raised.exception))

    def test_ntfy_failure_alone_is_visible_but_ui_carries_the_event(self):
        receipt = self._deliver(True, prefs={"ntfy_topic": "t"}, notify_ok=False)
        self.assertEqual(receipt["ui"], "delivered")
        self.assertEqual(receipt["ntfy"], "failed:ConnectionError")


class AcceptedChannelTests(TestCase):
    def test_only_owner_visible_delivered_receipt_is_accepted(self):
        flow = canonical_goal_flow
        self.assertIsNone(flow._accepted_user_channel({"ui": "failed:RuntimeError", "log": "delivered"}))
        self.assertIsNone(flow._accepted_user_channel({"log": "delivered", "voice": "delivered"}))
        self.assertEqual(flow._accepted_user_channel({"ui": "delivered", "ntfy": "failed:ConnectionError"}), "ui")
        self.assertEqual(flow._accepted_user_channel({"ui": "unavailable", "ntfy": "delivered"}), "ntfy")
        self.assertIsNone(flow._accepted_user_channel(None))


class _PlannerFixture(TestCase):
    """Same durable seams as the scheduler handoff suite, no model/network."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = "ui-receipt-planner"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(goal_executor, "STORE", self.root))
        self.stack.enter_context(patch.object(requests_state, "register_background", return_value=True))
        self.stack.enter_context(patch.object(requests_state, "check", return_value=None))
        self.stack.enter_context(patch.object(requests_state, "activate",
                                              side_effect=lambda *a, **k: nullcontext()))
        self.stack.enter_context(patch.object(requests_state, "allow_long_operation"))
        self.cancelled = self.stack.enter_context(
            patch.object(requests_state, "is_cancelled", return_value=False))
        self.ask = self.stack.enter_context(patch.object(model_wait, "ask"))
        self.live = self.stack.enter_context(
            patch.object(canonical_planning_queue, "_LIVE_ATTEMPTS", set()))
        job_id, _message = canonical_planning_queue.enqueue(self.owner, "rid-5", "Bir hedef.")
        self.job_id = job_id

    def force_running(self):
        base = goal_executor._owner_root(self.owner)
        _state, record = canonical_planning_queue._check_pair(
            base, self.owner, self.job_id)
        record["state"] = "planning_running"
        release_guard.atomic(base / (self.job_id + ".execution.json"),
                             execution_record.encode(record))


class PlanningStatusHonestyTests(_PlannerFixture):
    PLAN = '{"tasks":[{"id":"s","agent":"research","depends":[],"input":{"url":"https://example.test/a","question":"q"}}]}'

    def test_queued_status_still_names_the_queue(self):
        self.assertIn("Scheduler kuyruğunda",
                      canonical_planning_queue.status(self.owner, self.job_id))

    def test_stale_planning_running_is_reported_as_not_running(self):
        self.force_running()
        status = canonical_planning_queue.status(self.owner, self.job_id)
        self.assertIn("model çalışmıyor", status)
        self.assertIn("otomatik tekrar başlatılmaz", status)
        self.assertNotIn("planlama modeli çalışıyor", status)

    def test_live_attempt_is_the_only_running_claim(self):
        self.force_running()
        self.live.add((self.owner, self.job_id))
        status = canonical_planning_queue.status(self.owner, self.job_id)
        self.assertIn("planlama modeli çalışıyor", status)

    def test_execute_marks_attempt_live_then_clears_it(self):
        seen = []

        def ask(*args, **kwargs):
            seen.append((self.owner, self.job_id) in self.live)
            return self.PLAN
        self.ask.side_effect = ask
        outcome = canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), self.job_id, stop_event=threading.Event())
        self.assertEqual(outcome, "planned")
        self.assertEqual(seen, [True])
        self.assertEqual(self.live, set())
        self.assertNotIn("planlama modeli çalışıyor",
                         canonical_planning_queue.status(self.owner, self.job_id) or "")

    def test_failed_attempt_never_leaves_a_live_claim(self):
        self.ask.side_effect = TimeoutError("simulated")
        outcome = canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), self.job_id, stop_event=threading.Event())
        self.assertEqual(outcome, "review")
        self.assertEqual(self.live, set())
        status = canonical_planning_queue.status(self.owner, self.job_id)
        self.assertNotIn("planlama modeli çalışıyor", status)

    def test_cancelled_attempt_clears_live_before_park(self):
        self.ask.side_effect = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("x"))
        self.cancelled.return_value = True
        outcome = canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), self.job_id, stop_event=threading.Event())
        self.assertEqual(outcome, "review")
        self.ask.assert_not_called()
        self.assertEqual(self.live, set())

    def test_restart_discovery_never_replays_or_claims_running(self):
        self.force_running()
        self.assertEqual(canonical_planning_queue.discover(self.owner), ())
        self.assertFalse(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), self.job_id))
        self.ask.assert_not_called()
        self.assertIn("model çalışmıyor", canonical_planning_queue.status(self.owner, self.job_id))
