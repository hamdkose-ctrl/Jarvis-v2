"""VOICE-02D: bounded speed is an immutable utterance setting, not a voice switch."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules.voice_core import VoiceCatalog, VoiceCoordinator, VoiceSpec, SpeechRequest
from modules.voice_offline import piper_length_scale
from modules import brain_core_map, engine_intents


def voice_catalog():
    return VoiceCatalog((VoiceSpec("tr_kadin", "Test", "piper", "female.onnx"),))


class PiperRateTests(unittest.TestCase):
    def test_rate_snapshot_preserves_voice_identity_and_catalog(self):
        calls = []
        reports = []
        arrived = threading.Condition()
        def report(receipt):
            with arrived:
                reports.append(receipt)
                arrived.notify_all()
        def synth(spec, text, cancel):
            calls.append((spec.voice_id, spec.asset_id, spec.speaking_rate))
            return b"pcm"
        catalog = voice_catalog()
        coordinator = VoiceCoordinator(catalog, synth, lambda audio, cancel, on_start: on_start(), report)
        try:
            for idx, speed in enumerate((25, -20, 0)):
                self.assertTrue(coordinator.submit(SpeechRequest(
                    "alice", str(idx), "tr_kadin", "Merhaba!", rate=speed,
                )))
            with arrived:
                self.assertTrue(arrived.wait_for(lambda: len(reports) == 3, timeout=3))
        finally:
            coordinator.close()
        self.assertEqual(calls, [
            ("tr_kadin", "female.onnx", 25),
            ("tr_kadin", "female.onnx", -20),
            ("tr_kadin", "female.onnx", 0),
        ])
        self.assertEqual(catalog.require("tr_kadin").speaking_rate, 0)
        self.assertTrue(all(receipt.status == "played" for receipt in reports))

    def test_invalid_speed_and_boolean_rejected_before_synthesis(self):
        for bad in (41, -41, True, False, "20", 1.5, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    SpeechRequest("alice", "id", "tr_kadin", "Hello", rate=bad)
                with self.assertRaises(ValueError):
                    VoiceSpec("tr_kadin", "Test", "piper", "female.onnx",
                              speaking_rate=bad)

    def test_real_piper_scale_is_monotonic_and_never_changes_pitch_contract(self):
        values = [piper_length_scale(rate) for rate in (-40, -20, 0, 20, 40)]
        self.assertEqual(values[2], 1.0)
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertTrue(all(0.5 < x < 1.7 for x in values))

    def test_spoken_speed_command_updates_only_active_profile(self):
        prefs = {"voice": "tr_kadin", "rate": 15}
        writes = []
        profile = SimpleNamespace(
            data={"prefs": prefs},
            set_pref=lambda key, val: (writes.append((key, val)),
                                       prefs.__setitem__(key, val)),
        )
        runtime = SimpleNamespace(profile=profile)
        installed = Mock()
        installed.check_voice.return_value = VoiceSpec(
            "tr_kadin", "Test", "piper", "female.onnx",
        )
        with patch("modules.voice_runtime.active", return_value=installed), \
             patch("modules.requests_state.check"):
            slow = brain_core_map.core_plan("voice.rate", {"direction": "slower"})
            self.assertEqual(slow, ("voice_rate", {"direction": "slower"}))
            self.assertEqual(engine_intents.dispatch(runtime, *slow, "yavaş konuş", "yavaş konuş"),
                             "Daha yavaş konuşuyorum.")
            self.assertEqual(prefs["rate"], 5)
            fast = brain_core_map.core_plan("voice.rate", {"direction": "faster"})
            self.assertEqual(fast, ("voice_rate", {"direction": "faster"}))
            self.assertEqual(engine_intents.dispatch(runtime, *fast, "hızlı konuş", "hızlı konuş"),
                             "Daha hızlı konuşuyorum.")
            self.assertEqual(prefs["rate"], 15)
        self.assertEqual([key for key, _ in writes], ["rate", "rate"])
        self.assertEqual(prefs["voice"], "tr_kadin")

    def test_missing_piper_model_never_reports_speed_change(self):
        prefs = {"voice": "tr_kadin", "rate": 10}
        writes = []
        profile = SimpleNamespace(
            data={"prefs": prefs},
            set_pref=lambda key, value: writes.append((key, value)),
        )
        runtime = SimpleNamespace(profile=profile)
        missing = Mock()
        missing.check_voice.side_effect = ValueError("Not installed")
        with patch("modules.voice_runtime.active", return_value=missing), \
             patch("modules.requests_state.check"):
            plan = brain_core_map.core_plan("voice.rate", {"direction": "slower"})
            answer = engine_intents.dispatch(runtime, *plan, "yavaş konuş", "yavaş konuş")
        self.assertIn("değiştirilmedi", answer)
        self.assertEqual(writes, [])
        self.assertEqual(prefs["rate"], 10)


if __name__ == "__main__":
    unittest.main()
