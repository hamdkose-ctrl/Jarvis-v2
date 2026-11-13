"""Interactive voice/model reservations use the existing Scheduler lease authority.

The tests do not claim human-audible audio, live provider performance or real
Windows microphone permission. They check trusted keys, exclusivity, identity,
actual callback boundaries and release. Real device acceptance is separate.
"""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import threading

from modules import interactive_resource_gate, resource_leases
from modules.voice_core import SpeechRequest, VoiceCatalog, VoiceCoordinator, VoiceSpec


class InteractiveResourcesTests(TestCase):
    def test_only_trusted_runtime_kind_and_backend_bindings(self):
        f = interactive_resource_gate.trusted_key
        self.assertEqual(f("stt", owner="one"), "stt:microphone")
        self.assertEqual(f("output_device", owner="one"), "output_device:default")
        self.assertEqual(f("tts", owner="one", backend="edge"), "tts:edge")
        self.assertEqual(f("tts", owner="one", backend="piper"), "tts:piper")
        self.assertNotEqual(f("llm", owner="one"), f("llm", owner="two"))
        for kind, backend in (("tts", "../unsafe"), ("stt", "edge"),
                              ("output_device", "edge"), ("unknown", None)):
            with self.subTest(kind=kind, backend=backend), self.assertRaises(ValueError):
                f(kind, owner="one", backend=backend)

    def test_shared_existing_table_conflict_and_release_with_physical_os_claim(self):
        from modules import goal_executor
        leases = resource_leases.LeaseTable()
        with TemporaryDirectory() as directory, \
                patch.object(goal_executor, "_RESOURCE_LEASES", leases), \
                patch.object(Path, "home", return_value=Path(directory)):
            with interactive_resource_gate.claim(
                    "output_device", owner="alice", operation_id="first"):
                self.assertTrue(leases.occupied("output_device:default"))
                with self.assertRaises(resource_leases.LeaseConflict):
                    with interactive_resource_gate.claim(
                            "output_device", owner="bob", operation_id="second"):
                        self.fail("A second user took the same physical speaker")
            self.assertFalse(leases.occupied("output_device:default"))
            with interactive_resource_gate.claim(
                    "output_device", owner="bob", operation_id="second"):
                self.assertTrue(leases.occupied("output_device:default"))
            self.assertFalse(leases.occupied("output_device:default"))

    def test_stt_and_output_are_separate_resources(self):
        from modules import goal_executor
        leases = resource_leases.LeaseTable()
        with TemporaryDirectory() as directory, \
                patch.object(goal_executor, "_RESOURCE_LEASES", leases), \
                patch.object(Path, "home", return_value=Path(directory)):
            with interactive_resource_gate.claim("stt", owner="device"):
                with interactive_resource_gate.claim("output_device", owner="alice"):
                    self.assertTrue(leases.occupied("stt:microphone"))
                    self.assertTrue(leases.occupied("output_device:default"))
        self.assertFalse(leases.occupied("stt:microphone"))
        self.assertFalse(leases.occupied("output_device:default"))

    def test_model_resource_is_held_in_provider_thread_not_just_waiting_caller(self):
        from modules import model_wait
        seen = []
        @contextmanager
        def lease(kind, *, owner, operation_id=None, backend=None):
            seen.append(("start", kind, owner))
            yield
            seen.append(("end", kind, owner))
        with patch.object(model_wait.llm, "current_user", return_value="alice"), \
                patch.object(model_wait.requests_state, "check", return_value=None), \
                patch.object(model_wait.llm, "take_route", return_value=[]), \
                patch.object(interactive_resource_gate, "claim", side_effect=lease):
            result = model_wait.ask("hello", ask_fn=lambda *a, **k: "answer", seconds=2)
        self.assertEqual(result, "answer")
        self.assertEqual(seen, [("start", "llm", "alice"), ("end", "llm", "alice")])

    def test_voice_coordinator_wraps_only_real_synth_and_play(self):
        phases = []
        completed = threading.Event()
        receipts = []
        @contextmanager
        def scope(request, phase):
            phases.append(("enter", phase))
            try:
                yield
            finally:
                phases.append(("exit", phase))
        def playback(audio, cancel, on_start):
            self.assertEqual(audio, b"valid-audio")
            on_start()
        def report(receipt):
            receipts.append(receipt)
            completed.set()
        catalog = VoiceCatalog((VoiceSpec("tr_kadin", "Türkçe", "edge", "tr-TR-EmelNeural"),))
        voice = VoiceCoordinator(
            catalog, lambda spec, text, cancel: b"valid-audio",
            playback, report, resource_scope=scope,
        )
        try:
            request = SpeechRequest(owner="alice", request_id="r1",
                                    voice_id="tr_kadin", text="Merhaba")
            self.assertTrue(voice.submit(request))
            self.assertTrue(completed.wait(3), "Speech worker did not issue its receipt")
            self.assertEqual(receipts[0].status, "played")
            self.assertEqual(phases, [
                ("enter", "tts"), ("exit", "tts"),
                ("enter", "output_device"), ("exit", "output_device"),
            ])
        finally:
            voice.close()
