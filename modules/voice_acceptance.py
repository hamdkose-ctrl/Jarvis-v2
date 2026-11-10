"""VOICE-02B: human-confirmed local Piper output check, never automatic activation.

Usage (Jarvis stopped, model license reviewed by the operator):
python -m modules.voice_acceptance --model-root PATH --model voice.onnx \
    --voice-id tr_kadin --license-reviewed

This tool is intentionally interactive and does NOT modify voice_core.json,
the user's voice preference, download assets, or announce a passing result from
a Windows watcher. Successful synthesis/playback return is NOT proof of sound.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import threading
from typing import Callable

from modules.diagnostics import record_failure as _record_failure
from modules.voice_core import VoiceSpec
from modules.voice_offline import (
    OfflineVoiceUnavailable, PiperSynthesizer, WavePlayer, _validate_wave,
)

_PHRASE = (
    "Merhaba. Bu Jarvis Türkçe ses çıkışı testidir. "
    "Türkçe karakterleri dinleyin: ç, ğ, ı, ö, ş, ü."
)


def preflight(synth: PiperSynthesizer, spec: VoiceSpec) -> None:
    """Validate exact local model and accompanying Piper metadata, no downloads."""
    model = synth._model(spec)
    metadata = Path(str(model) + ".json")
    if not metadata.is_file() or metadata.is_symlink():
        raise OfflineVoiceUnavailable("Selected voice .onnx.json is missing.")
    if not 2 <= metadata.stat().st_size <= 64_000:
        raise OfflineVoiceUnavailable("Selected voice metadata size is invalid.")
    try:
        data = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OfflineVoiceUnavailable("Selected voice metadata cannot be read.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("audio"), dict):
        raise OfflineVoiceUnavailable("Selected voice metadata has no Piper audio field.")
    hz = data["audio"].get("sample_rate")
    if type(hz) is not int or not 8000 <= hz <= 48000:
        raise OfflineVoiceUnavailable("Selected voice sample rate is unsupported.")
    if not shutil.which("piper"):
        raise OfflineVoiceUnavailable("Piper executable is not installed.")


def probe(
    spec: VoiceSpec,
    synthesize: Callable,
    play: Callable,
    confirm_heard: Callable[[], str],
) -> dict:
    """Report stages separately; only a human's explicit yes means audible."""
    result = {
        "voice_id": spec.voice_id,
        "synthesis": "not_run",
        "playback": "not_run",
        "human_heard": None,
        "verdict": "not_verified",
    }
    cancel = threading.Event()
    try:
        audio = synthesize(spec, _PHRASE, cancel)
        _validate_wave(audio)
    except Exception:
        _record_failure("modules/voice_acceptance.py:synthesis")
        result["synthesis"] = "failed"
        return result
    result["synthesis"] = "valid_pcm"
    try:
        play(audio, cancel)
    except Exception:
        _record_failure("modules/voice_acceptance.py:playback")
        result["playback"] = "failed"
        return result
    result["playback"] = "returned"
    try:
        answer = confirm_heard().strip().casefold()
    except (EOFError, KeyboardInterrupt):
        return result
    if answer in ("evet", "e", "yes", "y"):
        result["human_heard"] = True
        result["verdict"] = "human_confirmed"
    elif answer in ("hayır", "hayir", "h", "no", "n"):
        result["human_heard"] = False
        result["verdict"] = "not_audible"
    return result


def available_output_devices() -> list[dict]:
    """List Windows/PortAudio output devices locally, without playing or recording."""
    import sounddevice as sd
    devices = []
    for index, row in enumerate(sd.query_devices()):
        if row["max_output_channels"] > 0:
            devices.append({
                "index": index,
                "name": str(row["name"])[:160],
                "channels": row["max_output_channels"],
            })
    return devices


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Local Piper output: operator-confirmed, no automatic pass."
    )
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--model",
                        help="Relative .onnx filename inside model-root.")
    parser.add_argument("--voice-id",
                        help="Exact selected voice ID, not an inferred replacement.")
    parser.add_argument("--device-index", type=int,
                        help="Optional sounddevice output device index.")
    parser.add_argument("--list-output-devices", action="store_true",
                        help="List output device indices without model/license setup.")
    parser.add_argument(
        "--license-reviewed", action="store_true",
        help="Operator explicitly reviewed the model and training-data rights.",
    )
    args = parser.parse_args(argv)
    if args.list_output_devices:
        try:
            devices = available_output_devices()
        except (ImportError, OSError, RuntimeError, ValueError):
            print(json.dumps({"verdict": "output_device_query_failed"}))
            return 2
        print(json.dumps({"output_devices": devices}, ensure_ascii=False))
        return 0 if devices else 1
    if args.model_root is None or not args.model or not args.voice_id:
        parser.error("--model-root, --model and --voice-id are required for playback.")
    if not args.license_reviewed:
        parser.error("The operator must review voice-model and dataset rights first.")
    spec = VoiceSpec(args.voice_id, args.voice_id, "piper", args.model)
    synthesizer = PiperSynthesizer(args.model_root)
    try:
        preflight(synthesizer, spec)
    except (OSError, ValueError, OfflineVoiceUnavailable):
        print(json.dumps({
            "voice_id": spec.voice_id, "synthesis": "not_run",
            "playback": "not_run", "human_heard": None,
            "verdict": "preflight_failed",
        }))
        return 2

    print("Jarvis'i kapatın; seçilen hoparlörün sesinin açık olduğundan emin olun.")
    print("Bu test ağ bağlantısı kullanmaz ve profil ses tercihini değiştirmez.")
    result = probe(
        spec, synthesizer, WavePlayer(device=args.device_index),
        lambda: input("Doğru Türkçe sesi gerçekten hoparlörden duydunuz mu? [e/h]: "),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verdict"] == "human_confirmed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
