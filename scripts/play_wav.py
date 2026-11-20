"""Play one PCM WAV on the speaker from its own process.

Why a separate process: on this PC the microphone listener and Windows' MCI player
share one audio device, and MCI playback measured ~27% slower than the audio it
carries (7.08 s of speech took 9.0 s), which the user hears as stuttering. Playing
through the same Python audio stack in-process was worse (12.9 s and 21.5 s for
3.7 s and 7.0 s of speech) because the input stream starved the output stream.

This child owns its own audio stack, so the parent's microphone capture cannot
starve it. It prints exactly one line when real playback has started, then exits
when the audio has actually been written to the device. The parent treats that
line as the player boundary and a clean exit as the outcome; anything else is a
failure, never a silent success.
"""
from __future__ import annotations

import io
import sys
import wave


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("kullanım: play_wav.py <dosya.wav>", file=sys.stderr)
        return 2
    path = argv[1]
    try:
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            width = handle.getsampwidth()
            frames = handle.getnframes()
            if width != 2 or channels not in (1, 2) or not 8_000 <= rate <= 48_000:
                print("desteklenmeyen ses biçimi", file=sys.stderr)
                return 3
            data = handle.readframes(frames)
    except (OSError, wave.Error, EOFError) as exc:
        print(f"ses dosyası okunamadı: {type(exc).__name__}", file=sys.stderr)
        return 3
    if not data:
        print("ses boş", file=sys.stderr)
        return 3
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice kurulu değil", file=sys.stderr)
        return 4
    block = 1024 * max(channels, 1) * 2
    try:
        with sd.RawOutputStream(samplerate=rate, channels=channels, dtype="int16") as stream:
            stream.write(data[:block])
            print("playing", flush=True)      # the real device boundary
            for start in range(block, len(data), block):
                stream.write(data[start:start + block])
    except Exception as exc:                  # noqa: BLE001 - report, never claim success
        print(f"çalma başarısız: {type(exc).__name__}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
