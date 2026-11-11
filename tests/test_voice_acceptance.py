"""VOICE-02B: mocked output cannot pass unless a person confirms hearing it."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from modules.voice_core import VoiceSpec
from modules.voice_offline import PiperSynthesizer, OfflineVoiceUnavailable
from modules.voice_acceptance import preflight, probe, main


def wave_audio(*, silent=False):
    buff = io.BytesIO()
    with wave.open(buff, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes((b"\x00\x00" if silent else b"\x01\x00") * 300)
    return buff.getvalue()


class VoiceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = VoiceSpec("tr_kadin", "Deneme Kadın", "piper", "female.onnx")
        (self.root / "female.onnx").write_bytes(b"model")
        (self.root / "female.onnx.json").write_text(
            json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8",
        )

    def test_two_output_stages_need_explicit_human_confirmation(self):
        heard = []
        player = Mock(side_effect=lambda audio, cancelled, on_start: (heard.append(len(audio)), on_start()))
        with patch("modules.voice_acceptance._record_failure"):
            result = probe(self.spec, lambda s, t, c: wave_audio(), player,
                           lambda: "evet")
        self.assertEqual(result, {
            "voice_id": "tr_kadin", "synthesis": "valid_pcm",
            "playback": "returned", "human_heard": True,
            "verdict": "human_confirmed",
        })
        self.assertEqual(len(heard), 1)

    def test_returned_playback_alone_does_not_prove_audible(self):
        for answer, verdict, heard in (
            ("hayır", "not_audible", False),
            ("", "not_verified", None),
            ("belirsiz", "not_verified", None),
        ):
            with self.subTest(answer=answer):
                result = probe(self.spec, lambda s, t, c: wave_audio(),
                               lambda a, c, s: None, lambda: answer)
                self.assertEqual(result["playback"], "returned")
                self.assertEqual(result["verdict"], verdict)
                self.assertEqual(result["human_heard"], heard)

    def test_synthesis_error_or_silent_wave_never_opens_player(self):
        player, prompt = Mock(), Mock()
        for synth in (
            lambda s, t, c: b"not WAV",
            lambda s, t, c: wave_audio(silent=True),
            Mock(side_effect=OfflineVoiceUnavailable("no model")),
        ):
            with self.subTest(synth=synth), patch("modules.voice_acceptance._record_failure"):
                result = probe(self.spec, synth, player, prompt)
                self.assertEqual(result["synthesis"], "failed")
                self.assertEqual(result["playback"], "not_run")
                self.assertIsNone(result["human_heard"])
                self.assertEqual(result["verdict"], "not_verified")
        player.assert_not_called()
        prompt.assert_not_called()

    def test_output_device_error_does_not_mark_audio_heard(self):
        with patch("modules.voice_acceptance._record_failure"):
            result = probe(self.spec, lambda s, t, c: wave_audio(),
                           Mock(side_effect=OSError("no speaker")),
                           lambda: self.fail("must not ask after failed playback"))
        self.assertEqual(result["synthesis"], "valid_pcm")
        self.assertEqual(result["playback"], "failed")
        self.assertIsNone(result["human_heard"])

    def test_noninteractive_session_cannot_fake_confirmation(self):
        result = probe(self.spec, lambda s, t, c: wave_audio(),
                       lambda a, c, s: None, Mock(side_effect=EOFError()))
        self.assertEqual(result["playback"], "returned")
        self.assertEqual(result["verdict"], "not_verified")

    def test_preflight_requires_exact_asset_metadata_and_piper_executable(self):
        synth = PiperSynthesizer(self.root)
        with patch("modules.voice_acceptance.shutil.which", return_value="C:/piper/piper.exe"):
            preflight(synth, self.spec)
            (self.root / "female.onnx.json").unlink()
            with self.assertRaises(OfflineVoiceUnavailable):
                preflight(synth, self.spec)
            (self.root / "female.onnx.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(OfflineVoiceUnavailable):
                preflight(synth, self.spec)
        (self.root / "female.onnx.json").write_text(
            json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8")
        with patch("modules.voice_acceptance.shutil.which", return_value=None):
            with self.assertRaises(OfflineVoiceUnavailable):
                preflight(synth, self.spec)

    def test_preflight_refuses_model_path_escape(self):
        synth = PiperSynthesizer(self.root)
        foreign = VoiceSpec("bad", "bad", "piper", "../outside.onnx")
        with self.assertRaises(OfflineVoiceUnavailable):
            preflight(synth, foreign)

    def test_output_device_listing_does_not_need_model_or_license(self):
        from modules.voice_acceptance import available_output_devices
        devices = [
            {"name": "Mic only", "max_output_channels": 0},
            {"name": "Speaker A", "max_output_channels": 2},
            {"name": "Headset", "max_output_channels": 1},
        ]
        with patch.dict(sys.modules, {
            "sounddevice": SimpleNamespace(query_devices=lambda: devices),
        }):
            self.assertEqual(available_output_devices(), [
                {"index": 1, "name": "Speaker A", "channels": 2},
                {"index": 2, "name": "Headset", "channels": 1},
            ])
            with patch("builtins.print") as printed:
                self.assertEqual(main(["--list-output-devices"]), 0)
            listing = json.loads(printed.call_args.args[0])
            self.assertEqual(len(listing["output_devices"]), 2)

    def test_no_output_devices_is_not_a_successful_playback_check(self):
        with patch.dict(sys.modules, {
            "sounddevice": SimpleNamespace(query_devices=lambda: []),
        }), patch("builtins.print") as printed:
            self.assertEqual(main(["--list-output-devices"]), 1)
            self.assertEqual(json.loads(printed.call_args.args[0]),
                             {"output_devices": []})

    def test_cli_refuses_run_until_license_reviewed(self):
        with patch("modules.voice_acceptance.preflight") as pre, \
             patch("modules.voice_acceptance.probe") as run:
            with self.assertRaises(SystemExit) as err:
                main(["--model-root", str(self.root),
                      "--model", "female.onnx", "--voice-id", "tr_kadin"])
            self.assertEqual(err.exception.code, 2)
            pre.assert_not_called()
            run.assert_not_called()

    def test_cli_can_verify_exact_piper_rate_without_altering_voice_selection(self):
        args = [
            "--model-root", str(self.root), "--model", "female.onnx",
            "--voice-id", "tr_kadin", "--rate", "-20", "--license-reviewed",
        ]
        with patch("modules.voice_acceptance.preflight") as preflight, \
             patch("modules.voice_acceptance.probe",
                   return_value={"voice_id": "tr_kadin", "verdict": "not_verified"}) as check, \
             patch("builtins.print") as print_json:
            self.assertEqual(main(args), 1)
        spec = preflight.call_args.args[1]
        self.assertEqual(spec.voice_id, "tr_kadin")
        self.assertEqual(spec.asset_id, "female.onnx")
        self.assertEqual(spec.speaking_rate, -20)
        self.assertIs(check.call_args.args[0], spec)
        self.assertIn('"requested_rate": -20', print_json.call_args.args[0])

    def test_cli_rejects_out_of_range_rate_before_audio_or_profile_change(self):
        for rate in ("-41", "41", "hızlı"):
            with self.subTest(rate=rate), \
                 patch("modules.voice_acceptance.preflight") as preflight, \
                 patch("modules.voice_acceptance.probe") as probe:
                with self.assertRaises(SystemExit) as exc:
                    main([
                        "--model-root", str(self.root), "--model", "female.onnx",
                        "--voice-id", "tr_kadin", "--rate", rate,
                        "--license-reviewed",
                    ])
                self.assertEqual(exc.exception.code, 2)
                preflight.assert_not_called()
                probe.assert_not_called()

    def test_cli_returns_nonzero_when_no_human_hearing_proof(self):
        args = ["--model-root", str(self.root), "--model", "female.onnx",
                "--voice-id", "tr_kadin", "--license-reviewed"]
        with patch("modules.voice_acceptance.preflight"), \
             patch("modules.voice_acceptance.probe",
                   return_value={"voice_id": "tr_kadin", "verdict": "not_verified"}):
            self.assertEqual(main(args), 1)


if __name__ == "__main__":
    unittest.main()
